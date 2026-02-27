# AirFlow

依方案 A 從 Apache Airflow 源碼建置自訂映像，並以多個 Docker 容器運行（不使用 docker-compose、不使用 Container Registry）。

- **建置**：自 https://github.com/apache/airflow 下載源碼 → 移除無用部分 → 以 repo 內 Dockerfile 自建 image；或可選僅下載 Dockerfile 從 PyPI 建置。
- **執行**：以 Shell 腳本啟動 metadata-db、scheduler、webserver（及可選 worker/flower）。使用 **CeleryExecutor** 或自訂 DB 連線時，請先 `source config/env.example`（或複製為 `.env` 後 source）再執行 `./scripts/start-airflow.sh`。
- **CI/CD**：GitLab CI、shell executor、不推送到 Registry。
- **Docker 權限**：腳本會先檢查是否在 **docker 群組**；**若在則直接執行 `docker`**，**若不在則以 `sudo docker` 執行**。Runner 或本機使用者若不在 docker 群組，需具備無密碼 sudo docker 權限。

完整步驟與檢查清單見 [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)。
