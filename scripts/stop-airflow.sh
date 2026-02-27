#!/usr/bin/env bash
# 停止並刪除 Airflow 相關容器與 network（見 docs/IMPLEMENTATION_PLAN.md 四）
# 含 LocalExecutor / CeleryExecutor（redis、worker、flower）
set -e

: "${AIRFLOW_NETWORK:=airflow-net}"
: "${AIRFLOW_DB_CONTAINER:=airflow-db}"
: "${AIRFLOW_REDIS_CONTAINER:=airflow-redis}"
: "${AIRFLOW_SCHEDULER_CONTAINER:=airflow-scheduler}"
: "${AIRFLOW_WEBSERVER_CONTAINER:=airflow-webserver}"
: "${AIRFLOW_WORKER_CONTAINER:=airflow-celery-worker}"
: "${AIRFLOW_FLOWER_CONTAINER:=airflow-flower}"

for c in "$AIRFLOW_FLOWER_CONTAINER" "$AIRFLOW_WORKER_CONTAINER" \
         "$AIRFLOW_WEBSERVER_CONTAINER" "$AIRFLOW_SCHEDULER_CONTAINER" \
         "$AIRFLOW_REDIS_CONTAINER" "$AIRFLOW_DB_CONTAINER"; do
  if docker ps -q -f name="^${c}$" | grep -q .; then
    docker stop "$c"
  fi
done

docker network rm "$AIRFLOW_NETWORK" 2>/dev/null || true
echo "Airflow stack stopped."
