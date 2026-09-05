# Multi-stage: build React app then serve with nginx
# Stage 1 — build frontend
FROM node:20-alpine AS builder
WORKDIR /app
COPY src/frontend/package*.json ./
RUN npm ci --include=dev
COPY src/frontend/ .
# VITE_API_URL: leave empty when nginx proxies /api on the same host.
# Set to your backend URL only when the frontend and backend are on different origins.
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# Stage 2 — nginx with built assets
FROM nginx:1.27-alpine
# openssl: the entrypoint script generates a self-signed cert when no real
# one is mounted, so the stack boots on any machine with zero TLS setup.
RUN apk add --no-cache openssl
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/locations.conf /etc/nginx/locations.conf
COPY nginx/proxy_common.conf /etc/nginx/proxy_common.conf
COPY nginx/ensure-certs.sh /docker-entrypoint.d/40-ensure-certs.sh
RUN chmod +x /docker-entrypoint.d/40-ensure-certs.sh
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80 443
