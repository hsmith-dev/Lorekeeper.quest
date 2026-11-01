#!/usr/bin/env bash
# CI-5 sidecar smoke: start a sidecar image with no network at all and wait
# for its Docker HEALTHCHECK to report healthy. Proves the weights are baked
# into the image (nothing can be downloaded with --network none) and that the
# models load inside the image's own runtime.
#
#   scripts/sidecar_smoke.sh <service> [image]
#
#   service  sidecar name, e.g. ml (used for the default image and the
#            container name)
#   image    image to run; default lorekeeper-<service>:latest
#
# SMOKE_TIMEOUT_S (default 300) bounds the wait. On anything but `healthy`
# the container's logs are dumped and the script exits non-zero. The
# container is always removed.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <service> [image]" >&2
  exit 2
fi

service="$1"
image="${2:-lorekeeper-${service}:latest}"
timeout_s="${SMOKE_TIMEOUT_S:-300}"
name="smoke-${service}-$$"

cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

fail() {
  echo "sidecar smoke FAILED for ${service} (${image}): $1" >&2
  echo "----- docker logs ${name} -----" >&2
  docker logs "$name" >&2 || true
  exit 1
}

echo "starting ${image} as ${name} with --network none (timeout ${timeout_s}s)"
docker run -d --network none --name "$name" "$image" >/dev/null

if [[ "$(docker inspect -f '{{if .State.Health}}yes{{end}}' "$name")" != "yes" ]]; then
  fail "image has no HEALTHCHECK"
fi

deadline=$(( $(date +%s) + timeout_s ))
while :; do
  running="$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || echo false)"
  health="$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null || echo unknown)"
  case "$health" in
    healthy)
      echo "${service}: healthy"
      exit 0
      ;;
    unhealthy)
      fail "container reported unhealthy"
      ;;
  esac
  [[ "$running" == "true" ]] || fail "container exited before turning healthy"
  (( $(date +%s) < deadline )) || fail "not healthy after ${timeout_s}s (last status: ${health})"
  sleep 3
done
