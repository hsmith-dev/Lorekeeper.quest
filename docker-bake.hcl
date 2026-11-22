# =============================================================================
# Lorekeeper — the images built from source (E0-Platform.9)
#
#   docker buildx bake --load                       # native platform, for this host
#   LOREKEEPER_TAG=v1.2 docker buildx bake --load   # tagged lorekeeper-<svc>:v1.2
#   docker buildx bake --set '*.platform=linux/amd64,linux/arm64'   # both arches
#
# The same four images docker-compose.prod.yml runs (web is also the worker's
# image). stt is always its `cpu` target here; the `gpu` target is local-only
# (docker-compose.gpu.yml) and never part of this file.
#
# Distribution is source only: nothing here pushes, and no target names a
# registry. scripts/deploy-oci.sh builds these on the host;
# .github/workflows/images.yml builds them for amd64 and arm64 on every PR.
# =============================================================================

variable "LOREKEEPER_TAG" {
  default = "latest"
}

# Empty (default): nginx on the same host proxies /api (see docker-compose.prod.yml).
variable "VITE_API_URL" {
  default = ""
}

group "default" {
  targets = ["web", "ml", "stt", "nginx"]
}

target "web" {
  context    = "src/backend"
  dockerfile = "Dockerfile.prod"
  tags       = ["lorekeeper-web:${LOREKEEPER_TAG}"]
}

target "ml" {
  context    = "src/services/ml"
  dockerfile = "Dockerfile"
  tags       = ["lorekeeper-ml:${LOREKEEPER_TAG}"]
}

target "stt" {
  context    = "src/services/stt"
  dockerfile = "Dockerfile"
  target     = "cpu"
  tags       = ["lorekeeper-stt:${LOREKEEPER_TAG}"]
}

target "nginx" {
  context    = "."
  dockerfile = "nginx/Dockerfile"
  args = {
    VITE_API_URL = "${VITE_API_URL}"
  }
  tags = ["lorekeeper-nginx:${LOREKEEPER_TAG}"]
}
