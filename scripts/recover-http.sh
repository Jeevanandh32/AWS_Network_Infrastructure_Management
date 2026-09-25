#!/bin/sh
set -eu

# Run from the project directory, regardless of where we launch it.
cd "$(dirname "$0")/.."

container_id=$(docker compose ps -a -q lab-http)

if [ -z "$container_id" ]; then
    echo "No lab-http container exists. Nothing to restart."
    exit 1
fi

state=$(docker inspect --format '{{.State.Status}}' "$container_id")
echo "Current lab-http state: $state"

if [ "$state" != "exited" ]; then
    echo "This script only handles stopped containers."
    echo "Investigate DNS, connectivity, or application health separately."
    exit 1
fi

echo "Proposed action: start the stopped lab-http container."
printf "Type APPROVE to continue: "
read -r approval

if [ "$approval" != "APPROVE" ]; then
    echo "Cancelled. No changes made."
    exit 0
fi

# Check again in case the container changed while awaiting approval.
current_id=$(docker compose ps -a -q lab-http)
current_state=$(docker inspect --format '{{.State.Status}}' "$container_id")

if [ "$current_id" != "$container_id" ] || [ "$current_state" != "exited" ]; then
    echo "Container changed. Run the script again to reassess."
    exit 1
fi

docker compose start lab-http

echo "Checking HTTP from the client network..."

attempt=1
while [ "$attempt" -le 10 ]; do
    status=$(
        docker compose exec -T diagnostics \
            curl --noproxy '*' -sS \
            --connect-timeout 2 --max-time 3 \
            -o /dev/null -w '%{http_code}' \
            http://lab-http:80/ 2>/dev/null
    ) || status="failed"

    if [ "$status" = "200" ]; then
        echo "Recovery verified: HTTP 200."
        echo "Grafana should resolve the alert after its next evaluations."
        exit 0
    fi

    echo "Attempt $attempt: HTTP check returned $status."
    sleep 2
    attempt=$((attempt + 1))
done

echo "HTTP recovery could not be verified. Investigate further."
exit 1
