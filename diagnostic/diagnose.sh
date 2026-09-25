#!/bin/sh
set -u

HOST="${1:-lab-http}"
PORT="${2:-80}"

printf 'Time: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'Target: %s:%s\n\n' "$HOST" "$PORT"

echo "=== DNS lookup ==="
dig "$HOST" A +time=2 +tries=1 +noall +comments +answer

echo
echo "=== HTTP connection test ==="
curl --noproxy '*' \
    --connect-timeout 3 \
    --max-time 8 \
    --silent --show-error \
    --output /dev/null \
    --write-out 'Remote IP: %{remote_ip}\nHTTP status: %{http_code}\nTotal time: %{time_total}s\n' \
    "http://${HOST}:${PORT}/"

RESULT=$?

echo
case "$RESULT" in
    0)
        echo "An HTTP response was received. Check its status code."
        ;;
    6)
        echo "FAILED: curl could not resolve the hostname."
        ;;
    7)
        echo "FAILED: curl could not establish a connection."
        echo "Check the destination port, listener, and network controls."
        ;;
    28)
        echo "FAILED: the operation timed out."
        echo "A timeout alone does not identify the root cause."
        ;;
    *)
        printf 'FAILED: curl exit code %s. Review the error above.\n' "$RESULT"
        ;;
esac

exit "$RESULT"
