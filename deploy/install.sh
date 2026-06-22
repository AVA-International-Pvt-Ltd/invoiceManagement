#!/usr/bin/env bash
# Account team — Mac/Linux install (Docker required).
# Usage: ./install.sh
#    or: ./install.sh yashjeetamai/invoice-finintel:1.0.0

set -euo pipefail
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="yashjeetamai/invoice-finintel:latest"
PORT="${PORT:-8080}"

if [[ -f "$DEPLOY_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  source "$DEPLOY_DIR/.env"
fi

if [[ -n "${1:-}" ]]; then
  IMAGE="$1"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install from https://docs.docker.com/get-docker/"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker, then run this script again."
  exit 1
fi

if [[ -z "${IMAGE:-}" ]]; then
  echo "Usage: ./install.sh [yashjeetamai/invoice-finintel:latest]"
  exit 1
fi

echo "Pulling $IMAGE ..."
docker pull "$IMAGE"

export IMAGE PORT
cd "$DEPLOY_DIR"
docker compose up -d

echo ""
echo "Invoice app is running."
echo "Open: http://localhost:${PORT}"
echo ""
echo "Useful commands:"
echo "  docker compose -f \"$DEPLOY_DIR/docker-compose.yml\" logs -f"
echo "  docker compose -f \"$DEPLOY_DIR/docker-compose.yml\" stop"
echo "  docker compose -f \"$DEPLOY_DIR/docker-compose.yml\" down"
