#!/bin/sh
# Runs automatically before nginx starts (nginx:alpine executes every *.sh in
# /docker-entrypoint.d/). nginx.conf points at /etc/nginx/certs/*.pem; this
# script guarantees those files exist so nginx can ALWAYS boot:
#
#   1. A mounted Let's Encrypt cert (any domain under /etc/letsencrypt/live/)
#      wins — real deployments behave exactly as before.
#   2. Otherwise a self-signed cert is generated once and reused. Browsers
#      show a warning to click through, but the stack comes up on any machine
#      with zero TLS setup — previously a fresh clone crash-looped here
#      because the hardcoded letsencrypt paths didn't exist.

CERT_DIR=/etc/nginx/certs
mkdir -p "$CERT_DIR"

LIVE=$(find /etc/letsencrypt/live -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -n 1)
if [ -n "$LIVE" ] && [ -f "$LIVE/fullchain.pem" ] && [ -f "$LIVE/privkey.pem" ]; then
    ln -sf "$LIVE/fullchain.pem" "$CERT_DIR/fullchain.pem"
    ln -sf "$LIVE/privkey.pem" "$CERT_DIR/privkey.pem"
    echo "[lorekeeper] TLS: using Let's Encrypt certificate from $LIVE"
    exit 0
fi

if [ -f "$CERT_DIR/fullchain.pem" ] && [ -f "$CERT_DIR/privkey.pem" ]; then
    echo "[lorekeeper] TLS: reusing existing self-signed certificate"
    exit 0
fi

echo "[lorekeeper] TLS: no certificate mounted — generating a self-signed one"
echo "[lorekeeper]      (browsers will show a one-time warning; fine for local/LAN use."
echo "[lorekeeper]      For a real domain, mount Let's Encrypt certs — see README.)"
if openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
    -keyout "$CERT_DIR/privkey.pem" -out "$CERT_DIR/fullchain.pem" \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null; then
    echo "[lorekeeper] TLS: self-signed certificate ready"
else
    echo "[lorekeeper] TLS: FAILED to generate a certificate — nginx will not start" >&2
    exit 1
fi
