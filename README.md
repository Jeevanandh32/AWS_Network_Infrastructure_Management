# ProbePulse
**Container Network Monitoring & Operator-Approved Recovery**

A six-service Docker Compose lab for diagnosing container connectivity, monitoring HTTP availability, and recovering a stopped service with human approval.

**Local benchmark:** 5/5 verified recoveries, 36.95-second median alert detection, and 351 ms median post-approval recovery to HTTP 200.

## Architecture

<img width="1017" height="758" alt="Screenshot 2026-09-27 at 2 33 43 AM" src="https://github.com/user-attachments/assets/08d2c062-7bc1-4c53-a424-3c16778230f0" />


| Service | Purpose |
|---|---|
| `client` | Shared client network namespace |
| `lab-http` | NGINX HTTP target |
| `diagnostics` | Custom Alpine image with tcpdump, curl, dig, ip, and ping |
| `blackbox` | HTTP probes with the http_2xx module |
| `prometheus` | Metrics collection; seven-day retention |
| `grafana` | Dashboards, alert evaluation, and email |

Diagnostics and Blackbox Exporter share the client's network namespace. Captures observe that network location, not every container's traffic. Diagnostics retains only the NET_RAW capability; Blackbox drops all capabilities. Grafana and Prometheus publish ports on host loopback.

## Features

- Three diagnostic scenarios: successful HTTP, wrong-port connection failure, and DNS resolution failure.
- ICMP, DNS, and HTTP packet analysis.
- HTTP availability and total probe-duration panels.
- Four provisioned Grafana components: data source, dashboard, contact point, and alert rule.
- Operator-approved recovery with container-state checks and HTTP verification.
- Python benchmark separating detection, approval delay, and recovery time.

Recovery handles a stopped target container. It does not repair arbitrary DNS, firewall, or application faults. Email notifications do not execute recovery scripts.

## Requirements and setup

Requirements: Docker Desktop or Docker Engine with Compose v2, Git, Python 3 for benchmarking, an SMTP account for email, and local ports 3000/9090 available.

The recorded tests ran on an Apple Silicon Mac with Docker Desktop and Grafana 13.2.2. Some images use mutable tags, so future pulls can differ from the tested environment.

```bash
git clone https://github.com/Jeevanandh32/ProbePulse.git
cd ProbePulse
mkdir -p captures
touch .env.smtp
chmod 600 .env.smtp
nano .env.smtp
```

For Gmail SMTP with an app password, enter the following using your own values:

```dotenv
GF_SMTP_ENABLED=true
GF_SMTP_HOST=smtp.gmail.com:587
GF_SMTP_USER=YOUR_EMAIL_ADDRESS
GF_SMTP_PASSWORD=YOUR_APP_PASSWORD
GF_SMTP_FROM_ADDRESS=YOUR_EMAIL_ADDRESS
GF_SMTP_FROM_NAME=ProbePulse Alerts
GF_SMTP_STARTTLS_POLICY=MandatoryStartTLS
ALERT_EMAIL=YOUR_RECIPIENT_ADDRESS
```

Replace all placeholders. This file is ignored by Git. Keep credentials out of exports and commits.

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl -fsS http://localhost:3000/api/health
```

Allow Grafana time to start before checking health.

- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090

For a fresh Grafana volume with this configuration, sign in with admin/admin and change the password when prompted. Existing volumes retain the configured password.

Open **Network Lab → Service Availability Copy**. The alert is **Jeevs → HTTP Service Availability**, routed to **Point Of Contact**. Test that contact point before running an outage.

These instructions match the committed configuration; a separate empty-volume reproduction test remains pending.

## Connectivity diagnostics

Run each command separately; the failure scenarios intentionally return nonzero exit codes.

```bash
# Expected: DNS resolves and HTTP returns 200.
docker compose exec diagnostics sh /usr/local/bin/diagnose.sh lab-http 80

# Expected: DNS resolves, but connection fails on an unused port.
docker compose exec diagnostics sh /usr/local/bin/diagnose.sh lab-http 8080

# Expected: DNS resolution fails.
docker compose exec diagnostics sh /usr/local/bin/diagnose.sh missing-service.invalid 80
```

The diagnostic script reports HTTP responses without requiring status 200: inspect the returned status code. The recovery script separately requires HTTP 200.

## Packet capture

In terminal 1:

```bash
docker compose exec diagnostics tcpdump -i eth0 -p -nn -U \
  -w /captures/http-demo.pcap 'tcp port 80'
```

Generate a request in terminal 2:

```bash
docker compose exec diagnostics curl --noproxy '*' -sS -o /dev/null http://lab-http:80/
```

Stop capture with Control+C, then inspect:

```bash
docker compose exec diagnostics tcpdump -nn -r /captures/http-demo.pcap
```

Open the host file `captures/http-demo.pcap` in Wireshark if desired. For DNS capture, use `-i any` to include the Docker embedded resolver's loopback traffic. PCAP files are excluded from Git.

## Monitoring configuration

Dashboard queries:

```promql
probe_success{job="http-probe", monitored_service="lab-http"}
```

```promql
probe_duration_seconds{job="http-probe", monitored_service="lab-http"} * 1000
```

Probe success describes the target check; Prometheus `up` describes whether the exporter scrape succeeded. Probe duration is total probe time, not necessarily successful application-request latency.

| Setting | Value |
|---|---|
| Scrape interval / timeout | 10 s / 8 s |
| Blackbox timeout | 5 s |
| Alert evaluation / pending period | 10 s / 20 s |
| Failure condition | Probe success below 1 |
| Notification group wait / interval | 10 s / 30 s |
| Repeat notification interval | 5 min |

Grouping and SMTP delivery add delay beyond alert detection. A resolved notification means the failure condition cleared.

Active provisioning is in `monitoring/grafana/provisioning/`; dashboard content is in `monitoring/grafana/dashboards/`. The file in `monitoring/grafana/alerting/` is an earlier export, not the active provisioned rule.

## Outage and approved recovery

```bash
docker compose stop lab-http
```

Observe the alert move to firing. After the outage notification, run:

```bash
sh scripts/recover-http.sh
```

Type `APPROVE` to start the stopped container; other input cancels. The script rechecks identity/state after approval, starts the container, and verifies HTTP 200 from the diagnostics container with bounded retries. Confirm the dashboard recovers and a resolved notification arrives.

## Benchmark and results

```bash
python3 scripts/benchmark-recovery.py
```

Enter the Grafana admin password privately. Press Enter to begin each outage and type APPROVE when prompted. Each attempt begins with healthy HTTP and an inactive alert. Grafana is polled once per second; the benchmark waits for the alert to clear between runs.

Results are written to timestamped `benchmark-results/` directories as CSV and JSONL. Credentials are not written to those results.

### Recorded results: September 27, 2026 UTC

| Run | Detection (s) | Approval delay (s) | Post-approval recovery (s) | Result |
|---|---:|---:|---:|---|
| 1 | 34.954 | 26.861 | 0.385 | Verified |
| 2 | 36.950 | 15.122 | 0.351 | Verified |
| 3 | 37.944 | 15.444 | 0.336 | Verified |
| 4 | 33.899 | 14.262 | 0.357 | Verified |
| 5 | 39.001 | 4.213 | 0.345 | Verified |

- Verified recoveries: **5/5 attempted**.
- Detection median: **36.950 s**; range **33.899–39.001 s**.
- Post-approval recovery median: **0.351 s**; range **0.336–0.385 s**.

[Raw CSV](benchmark-results/20260927T055507Z/results.csv) · [Event evidence](benchmark-results/20260927T055507Z/)

### Measurement boundaries

- Detection starts before the stop command and ends when polling first observes firing. It includes shutdown time and polling/API latency.
- Approval delay includes script startup, initial checks, operator input, and recording the approval marker.
- Recovery measures approval-marker to HTTP-verification-marker time, including state rechecks, Docker commands, verification, and instrumentation overhead.
- Durations use the host monotonic clock; UTC timestamps identify runs. Displayed precision does not establish equivalent accuracy.
- Email arrival is not timed. Five local tests demonstrate one stopped-container recovery path, not production availability or improvement over a measured manual baseline.
- If interrupted, inspect the target state and recover it manually with the approval script. Automatic cleanup after interruption is not guaranteed.

## Troubleshooting and shutdown

```bash
docker compose ps -a
docker compose logs --tail=60 grafana
docker compose logs --tail=60 prometheus
```

- **Daemon unavailable:** start Docker Desktop and wait for its engine.
- **Duplicate data-source UID:** provisioning must match the existing name, UID, and organization. This lab uses lowercase `prometheus`, UID `dfz920kwdu4n4a`, org 1.
- **No email:** check SMTP settings, ALERT_EMAIL, and the contact-point test. Environment changes require `docker compose up -d --no-deps --force-recreate grafana`.
- **Dashboard editing disabled:** the provider uses `allowUiUpdates: false`; edit the version-controlled JSON.

Stop while preserving containers and data:

```bash
docker compose stop
```

Resume with `docker compose up -d`. `docker compose down` removes containers/network but normally retains named volumes. Adding `--volumes` deletes monitoring data and stored Grafana settings.

## Remaining work

- Validate deployment with an independent empty Grafana volume.
- Pin container versions or digests.
- Align the alert's dashboard link (`adwb45k`) with the provisioned dashboard UID (`adctrlk`). Evaluation works, but the old link may not resolve on a fresh instance.
- Keep AWS, Terraform, and Kubernetes development in the separate multi-region project.

## Development approach

GPT-assisted scripting supported Bash/Python development. The workflow was exercised manually and benchmarked across five local runs. Recovery uses deterministic scripts with human approval, not an autonomous AI agent.

## Repositories

- [GitHub](https://github.com/Jeevanandh32/ProbePulse)
- [Bitbucket](https://bitbucket.org/jeeva07/probepulse)

