# Docker 建置用檔案

## Dockerfile.airflow

方案 A1（僅 Dockerfile + PyPI）需先下載官方 Dockerfile。

**建置請一律使用 `./scripts/build.sh`**，並以環境變數 `AIRFLOW_VERSION`（預設 3.2.0）指定版本。若直接使用 `docker build -f docker/Dockerfile.airflow`，請傳入 `--build-arg AIRFLOW_VERSION=<版本>` 與腳本預設一致（例如 `3.2.0`）。

下載 Dockerfile 時可指定分支／tag（建議與建置版本一致）：

```bash
# 與 scripts/build.sh 預設版本一致（3.2.0）
export AIRFLOW_VERSION=3.2.0
curl -o docker/Dockerfile.airflow "https://raw.githubusercontent.com/apache/airflow/${AIRFLOW_VERSION}/Dockerfile"
# 或使用 download-dockerfile.sh：AIRFLOW_DOCKERFILE_REF=3.2.0 ./scripts/download-dockerfile.sh
```

或指定其他版本（請依 apache/airflow 實際 tag 調整，例如 2.10.0、3.1.7）：

```bash
curl -o docker/Dockerfile.airflow "https://raw.githubusercontent.com/apache/airflow/2.10.0/Dockerfile"
```

下載後在專案根目錄執行 `./scripts/build.sh`（腳本會依是否在 docker 群組自動使用 `docker` 或 `sudo docker`）。
