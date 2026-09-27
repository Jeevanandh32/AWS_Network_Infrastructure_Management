import base64
import csv
import getpass
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

# Verify the recovery script has our optional timing markers.
recovery = ROOT / "scripts/recover-http.sh"
assert "benchmark_event approved" in recovery.read_text(), \
    "Install the recovery timing markers first."

password = getpass.getpass("Grafana admin password: ")
auth = base64.b64encode(f"admin:{password}".encode()).decode()
del password

endpoint = "http://localhost:3000/api/prometheus/grafana/api/v1/rules"
rule_name = "HTTP Service Availability"

folder = ROOT / "benchmark-results" / datetime.now(
    timezone.utc
).strftime("%Y%m%dT%H%M%SZ")
folder.mkdir(parents=True, exist_ok=False)

fields = [
    "run", "stop_issued_utc", "result",
    "detection_seconds", "approval_delay_seconds",
    "recovery_seconds", "error"
]
results = []


def command(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def alert_state():
    request = urllib.request.Request(
        endpoint, headers={"Authorization": f"Basic {auth}"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)

    matches = [
        rule
        for group in payload["data"]["groups"]
        for rule in group["rules"]
        if rule.get("name") == rule_name
    ]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one matching alert rule.")

    rule = matches[0]
    if rule.get("health") != "ok":
        raise RuntimeError(f"Alert evaluation unhealthy: {rule.get('lastError')}")
    return rule["state"]


def wait_for(state, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if alert_state() == state:
            return time.monotonic()
        time.sleep(1)
    raise TimeoutError(f"Alert did not become {state} within {timeout}s")


def verify_http():
    result = command(
        "docker", "compose", "exec", "-T", "diagnostics",
        "curl", "--noproxy", "*", "-sS",
        "--connect-timeout", "2", "--max-time", "5",
        "-o", "/dev/null", "-w", "%{http_code}",
        "http://lab-http:80/",
        capture_output=True, text=True
    )
    if result.stdout.strip() != "200":
        raise RuntimeError("Baseline HTTP check did not return 200.")


def save_results():
    with (folder / "results.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)


for number in range(1, 6):
    # Establish a healthy baseline before counting an attempt.
    try:
        verify_http()
        wait_for("inactive")
    except Exception as error:
        print(f"Baseline check failed: {error}")
        break

    input(f"\nRun {number}/5: press Enter to begin the outage.")
    row = {key: "" for key in fields}
    row.update(run=number, result="failed")
    events_file = folder / f"run-{number}-events.jsonl"

    try:
        row["stop_issued_utc"] = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()
        events_file.write_text(json.dumps({
            "event": "stop_issued", "monotonic": t0,
            "utc": row["stop_issued_utc"]
        }) + "\n")

        command("docker", "compose", "stop", "lab-http")
        print("Waiting for Grafana to report firing...")
        t1 = wait_for("firing")
        with events_file.open("a") as file:
            file.write(json.dumps({
                "event": "firing_observed", "monotonic": t1
            }) + "\n")
        row["detection_seconds"] = round(t1 - t0, 3)

        print("Alert firing. Recovery will now request your approval.")
        environment = os.environ.copy()
        environment["BENCHMARK_LOG"] = str(events_file)
        command("sh", str(recovery), env=environment)

        events = [
            json.loads(line)
            for line in events_file.read_text().splitlines()
        ]
        t2 = next(
            event["monotonic"] for event in events
            if event["event"] == "approved"
        )
        t3 = next(
            event["monotonic"] for event in events
            if event["event"] == "http_verified"
        )

        row["approval_delay_seconds"] = round(t2 - t1, 3)
        row["recovery_seconds"] = round(t3 - t2, 3)
        row["result"] = "success"

    except Exception as error:
        row["error"] = str(error)

    results.append(row)
    save_results()
    print(json.dumps(row, indent=2))

    if row["result"] != "success":
        print("Stopping the benchmark. Inspect the failure before retrying.")
        print("If lab-http is stopped, run: ./scripts/recover-http.sh")
        break

    print("Waiting for the alert to clear...")
    try:
        wait_for("inactive")
    except Exception as error:
        print(f"HTTP recovered, but alert reset failed: {error}")
        break

successful = [row for row in results if row["result"] == "success"]
print(f"\nVerified recoveries: {len(successful)}/{len(results)} attempted")
for field in ("detection_seconds", "recovery_seconds"):
    values = [row[field] for row in successful]
    if values:
        print(
            f"{field}: median={statistics.median(values):.3f}s; "
            f"range={min(values):.3f}–{max(values):.3f}s"
        )
print(f"Results saved to: {folder}")
