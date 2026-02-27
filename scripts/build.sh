#!/usr/bin/env bash
# 封裝 docker build，供本機與 CI 使用（見 docs/IMPLEMENTATION_PLAN.md 2.2 / 2.3）
set -e

: "${AIRFLOW_VERSION:=3.2.0}"
: "${AIRFLOW_IMAGE_TAG:=${AIRFLOW_VERSION}-custom}"
: "${BUILD_MODE:=A1}"
# BUILD_MODE: A1 = 僅 Dockerfile + PyPI（需先下載 docker/Dockerfile.airflow）；source = 從 clone 源碼建置

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export DOCKER_BUILDKIT=1

# 若在 Apple Silicon Mac 建置且映像要在 Rocky Linux 使用，設 PLATFORM=linux/amd64
PLATFORM_EXTRA=()
if [[ -n "${DOCKER_PLATFORM:-}" ]]; then
  PLATFORM_EXTRA=(--platform "$DOCKER_PLATFORM")
fi

if [[ "$BUILD_MODE" == "source" ]]; then
  # 主流程：需在 clone 後的 airflow 源碼目錄執行，或由 CI 先 clone 再呼叫此腳本並傳 CONTEXT
  BUILD_CONTEXT="${AIRFLOW_SOURCE_DIR:-.}"
  DOCKERFILE="${AIRFLOW_SOURCE_DIR:-.}/Dockerfile"
  if [[ -n "${AIRFLOW_SOURCE_DIR:-}" ]]; then
    cd "$AIRFLOW_SOURCE_DIR"
  fi
  docker build "${PLATFORM_EXTRA[@]}" -f Dockerfile \
    --build-arg AIRFLOW_INSTALLATION_METHOD=. \
    --build-arg AIRFLOW_SOURCES_FROM=. \
    --build-arg AIRFLOW_SOURCES_TO=/opt/airflow \
    --build-arg AIRFLOW_VERSION="$AIRFLOW_VERSION" \
    -t "airflow:${AIRFLOW_IMAGE_TAG}" \
    .
else
  # A1：使用 docker/Dockerfile.airflow，從 PyPI 建置
  if [[ ! -f docker/Dockerfile.airflow ]]; then
    echo "Missing docker/Dockerfile.airflow. Download with:"
    echo "  curl -o docker/Dockerfile.airflow 'https://raw.githubusercontent.com/apache/airflow/${AIRFLOW_VERSION}/Dockerfile'"
    exit 1
  fi
  BUILD_ARGS=(
    -f docker/Dockerfile.airflow
    --build-arg AIRFLOW_VERSION="$AIRFLOW_VERSION"
    --build-arg AIRFLOW_PYTHON_VERSION="${AIRFLOW_PYTHON_VERSION:-3.12.12}"
    -t "airflow:${AIRFLOW_IMAGE_TAG}"
  )
  [[ -d docker/context ]] && BUILD_ARGS+=(--build-arg DOCKER_CONTEXT_FILES=docker/context)
  docker build "${PLATFORM_EXTRA[@]}" "${BUILD_ARGS[@]}" .
fi

echo "Built image: airflow:${AIRFLOW_IMAGE_TAG}"
