#!/usr/bin/env bash
# 下載官方 Dockerfile 至 docker/Dockerfile.airflow（見 docs/IMPLEMENTATION_PLAN.md 2.2）
set -e

: "${AIRFLOW_DOCKERFILE_REF:=main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
mkdir -p "$PROJECT_ROOT/docker"
url="https://raw.githubusercontent.com/apache/airflow/${AIRFLOW_DOCKERFILE_REF}/Dockerfile"
echo "Downloading Dockerfile from $url"
curl -sSf -o "$PROJECT_ROOT/docker/Dockerfile.airflow" "$url"
echo "Saved to docker/Dockerfile.airflow"
