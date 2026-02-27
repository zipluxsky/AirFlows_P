# AirFlow

依方案 A 從 Apache Airflow 源碼建置自訂映像，並以多個 Docker 容器運行（不使用 docker-compose、不使用 Container Registry）。

- **建置**：自 https://github.com/apache/airflow 下載源碼 → 移除無用部分 → 以 repo 內 Dockerfile 自建 image；或可選僅下載 Dockerfile 從 PyPI 建置。
- **執行**：以 Shell 腳本啟動 metadata-db、scheduler、webserver（及可選 worker/flower）。
- **CI/CD**：GitLab CI、shell executor、不推送到 Registry。

完整步驟與檢查清單見 [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)。
