#!/usr/bin/env bash
# Certbot post-renewal hook — installed into
# /etc/letsencrypt/renewal-hooks/post/ on the instance. Brings nginx back up
# after certbot-pre-hook.sh stopped it for the renewal. Runs even if renewal
# failed (certbot always runs post-hooks), so this can't be skipped and
# leave the site down.
set -euo pipefail
cd /home/ubuntu/lorekeeper
docker compose -f docker-compose.prod.yml start nginx
