#!/usr/bin/env bash
# Certbot pre-renewal hook — installed into
# /etc/letsencrypt/renewal-hooks/pre/ on the instance. Certbot's standalone
# auth method (used for the initial cert, since nginx runs in a container
# rather than on the host — see docs/OCI_DEPLOYMENT.md's TLS section) needs
# port 80 free to answer the ACME HTTP-01 challenge, so nginx has to step
# aside for the duration of each renewal too, not just the first issuance.
set -euo pipefail
cd /home/ubuntu/lorekeeper
docker compose -f docker-compose.prod.yml stop nginx
