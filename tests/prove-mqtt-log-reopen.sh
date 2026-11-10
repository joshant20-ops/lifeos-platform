#!/usr/bin/env bash
# Disposable broker on a GitHub-hosted runner, using only synthetic data.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_ENVIRONMENT:-}" == github-hosted ]]
image=$(awk '$1 == "image:" { print $2 }' ansible/desired/compose/mosquitto/docker-compose.yml)
[[ "$image" =~ ^eclipse-mosquitto@sha256:[0-9a-f]{64}$ ]]
work=$(mktemp -d)
broker=
cleanup() {
    if [[ -n "$broker" ]]; then
        docker logs --tail 30 "$broker" >&2 || true
        docker rm -f "$broker" >/dev/null || true
    fi
    rm -rf -- "$work"
}
trap cleanup EXIT
chmod 0777 "$work"
cat > "$work/proof.conf" <<'CONFIG'
listener 1883 127.0.0.1
allow_anonymous true
persistence false
log_dest file /proof/broker.log
log_dest stdout
log_type all
CONFIG
docker pull "$image"
version=$(docker run --rm --network none --entrypoint mosquitto "$image" -h 2>&1 |
    awk '/^mosquitto version / { print $3 }')
[[ "$version" =~ ^2\.[0-9]+\.[0-9]+$ ]]
signal=log-rotate
printf 'MOSQUITTO_VERSION=%s\nREOPEN_SIGNAL=%s\n' "$version" "$signal"

broker=$(docker run -d --network none --read-only --cap-drop ALL --user 1883:1883 \
    --mount "type=bind,src=$work,dst=/proof" --entrypoint mosquitto "$image" -c /proof/proof.conf)
publish() {
    timeout 5s docker exec "$broker" mosquitto_pub -h 127.0.0.1 -t proof/log -m "$1"
}
for attempt in {1..10}; do
    if publish before; then break; fi
    sleep 1
done
test -s "$work/broker.log"
original=$(docker inspect -f '{{.State.Pid}}:{{.State.StartedAt}}:{{.RestartCount}}' "$broker")

# Keep a client connected across the rename and signal.
timeout 30s docker exec "$broker" mosquitto_sub -h 127.0.0.1 -t proof/log -C 2 -W 25 > "$work/received" &
subscriber=$!
for attempt in {1..10}; do
    if grep -q 'Received SUBSCRIBE' "$work/broker.log"; then break; fi
    sleep 1
done
grep -q 'Received SUBSCRIBE' "$work/broker.log"
publish pre-rotation
mv -- "$work/broker.log" "$work/retained.log"
timeout 5s docker exec "$broker" mosquitto_signal -p 1 "$signal"
for attempt in {1..10}; do
    if [[ -f "$work/broker.log" ]]; then break; fi
    sleep 1
done
test -f "$work/broker.log"
retained_size=$(stat -c %s "$work/retained.log")
publish post-rotation
wait "$subscriber"
printf 'pre-rotation\npost-rotation\n' | cmp - "$work/received"
grep -q 'Received PUBLISH' "$work/broker.log"
test "$retained_size" = "$(stat -c %s "$work/retained.log")"
test "$original" = "$(docker inspect -f '{{.State.Pid}}:{{.State.StartedAt}}:{{.RestartCount}}' "$broker")"
echo 'MQTT_LOG_REOPEN_AND_SUBSCRIPTION_CONTINUITY=PASS'
