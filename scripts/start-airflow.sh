#!/usr/bin/env bash
# 建立 network、啟動 metadata-db、scheduler、webserver；可選 Redis + worker + flower（CeleryExecutor）
# 見 docs/IMPLEMENTATION_PLAN.md 四
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

: "${AIRFLOW_IMAGE:=airflow:3.2.0-custom}"
: "${AIRFLOW_NETWORK:=airflow-net}"
: "${AIRFLOW_DB_CONTAINER:=airflow-db}"
: "${AIRFLOW_REDIS_CONTAINER:=airflow-redis}"
: "${AIRFLOW_SCHEDULER_CONTAINER:=airflow-scheduler}"
: "${AIRFLOW_WEBSERVER_CONTAINER:=airflow-webserver}"
: "${AIRFLOW_WORKER_CONTAINER:=airflow-celery-worker}"
: "${AIRFLOW_FLOWER_CONTAINER:=airflow-flower}"
: "${POSTGRES_USER:=airflow}"
: "${POSTGRES_PASSWORD:=airflow}"
: "${POSTGRES_DB:=airflow}"
: "${SQL_ALCHEMY_CONN:=postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${AIRFLOW_DB_CONTAINER}:5432/${POSTGRES_DB}}"
: "${EXECUTOR:=${AIRFLOW__CORE__EXECUTOR:-LocalExecutor}}"
: "${CELERY_BROKER_URL:=redis://${AIRFLOW_REDIS_CONTAINER}:6379/0}"
: "${CELERY_RESULT_BACKEND:=db+postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${AIRFLOW_DB_CONTAINER}:5432/${POSTGRES_DB}}"
: "${DAGS_MOUNT:=$PROJECT_ROOT/dags}"

# 若在 CI 中，可用 $CI_PROJECT_DIR
if [[ -n "${CI_PROJECT_DIR:-}" ]]; then
  DAGS_MOUNT="${CI_PROJECT_DIR}/dags"
fi

# CeleryExecutor 時需傳給所有 Airflow 容器的環境變數（傳回 -e key=val ... 供 docker run 使用）
CELERY_ENV_ARGS=()
if [[ "$EXECUTOR" == "CeleryExecutor" ]]; then
  CELERY_ENV_ARGS=(
    -e "AIRFLOW__CELERY__BROKER_URL=${CELERY_BROKER_URL}"
    -e "AIRFLOW__CELERY__RESULT_BACKEND=${CELERY_RESULT_BACKEND}"
  )
fi

# 1. 建立 network
docker network inspect "$AIRFLOW_NETWORK" &>/dev/null || docker network create "$AIRFLOW_NETWORK"

# 2. 啟動 PostgreSQL（metadata-db）
docker run -d --rm \
  --name "$AIRFLOW_DB_CONTAINER" \
  --network "$AIRFLOW_NETWORK" \
  -e POSTGRES_USER="$POSTGRES_USER" \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  -e POSTGRES_DB="$POSTGRES_DB" \
  -p 5432:5432 \
  postgres:15-alpine

# 3. 等待 DB 就緒
echo "Waiting for DB..."
until docker exec "$AIRFLOW_DB_CONTAINER" pg_isready -U "$POSTGRES_USER"; do
  sleep 2
done

# 3b. CeleryExecutor 時啟動 Redis 並等待就緒
if [[ "$EXECUTOR" == "CeleryExecutor" ]]; then
  docker run -d --rm \
    --name "$AIRFLOW_REDIS_CONTAINER" \
    --network "$AIRFLOW_NETWORK" \
    -p 6379:6379 \
    redis:7-alpine
  echo "Waiting for Redis..."
  until docker exec "$AIRFLOW_REDIS_CONTAINER" redis-cli ping 2>/dev/null | grep -q PONG; do
    sleep 1
  done
fi

# 4. 初始化 DB（僅需跑一次；已有 DB 時可改為 airflow db migrate）
docker run --rm \
  --network "$AIRFLOW_NETWORK" \
  -e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="$SQL_ALCHEMY_CONN" \
  -e AIRFLOW__CORE__EXECUTOR="$EXECUTOR" \
  "${CELERY_ENV_ARGS[@]}" \
  "$AIRFLOW_IMAGE" \
  airflow db init

# 5. 建立 admin 使用者（可選，首次可手動或略過）
# docker run --rm --network ... -e ... "$AIRFLOW_IMAGE" airflow users create ...

# 6. 啟動 scheduler
docker run -d --rm \
  --name "$AIRFLOW_SCHEDULER_CONTAINER" \
  --network "$AIRFLOW_NETWORK" \
  -e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="$SQL_ALCHEMY_CONN" \
  -e AIRFLOW__CORE__EXECUTOR="$EXECUTOR" \
  "${CELERY_ENV_ARGS[@]}" \
  -v "$DAGS_MOUNT:/opt/airflow/dags" \
  "$AIRFLOW_IMAGE" \
  airflow scheduler

# 7. 啟動 webserver
docker run -d --rm \
  --name "$AIRFLOW_WEBSERVER_CONTAINER" \
  --network "$AIRFLOW_NETWORK" \
  -e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="$SQL_ALCHEMY_CONN" \
  -e AIRFLOW__CORE__EXECUTOR="$EXECUTOR" \
  "${CELERY_ENV_ARGS[@]}" \
  -v "$DAGS_MOUNT:/opt/airflow/dags" \
  -p 8080:8080 \
  "$AIRFLOW_IMAGE" \
  airflow webserver

# 8. CeleryExecutor 時啟動 worker 與 flower
if [[ "$EXECUTOR" == "CeleryExecutor" ]]; then
  docker run -d --rm \
    --name "$AIRFLOW_WORKER_CONTAINER" \
    --network "$AIRFLOW_NETWORK" \
    -e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="$SQL_ALCHEMY_CONN" \
    -e AIRFLOW__CORE__EXECUTOR="$EXECUTOR" \
    "${CELERY_ENV_ARGS[@]}" \
    -v "$DAGS_MOUNT:/opt/airflow/dags" \
    "$AIRFLOW_IMAGE" \
    airflow celery worker

  docker run -d --rm \
    --name "$AIRFLOW_FLOWER_CONTAINER" \
    --network "$AIRFLOW_NETWORK" \
    -e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="$SQL_ALCHEMY_CONN" \
    -e AIRFLOW__CORE__EXECUTOR="$EXECUTOR" \
    "${CELERY_ENV_ARGS[@]}" \
    -p 5555:5555 \
    "$AIRFLOW_IMAGE" \
    airflow celery flower

  echo "Airflow started (CeleryExecutor). Webserver: http://localhost:8080  Flower: http://localhost:5555"
else
  echo "Airflow started (LocalExecutor). Webserver: http://localhost:8080"
fi
