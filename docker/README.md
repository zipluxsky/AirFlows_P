# Docker 建置用檔案

## Dockerfile.airflow

方案 A1（僅 Dockerfile + PyPI）需先下載官方 Dockerfile：

```bash
# 指定版本（請依 apache/airflow 實際 tag 調整，例如 2.10.0、3.1.7）
curl -o docker/Dockerfile.airflow "https://raw.githubusercontent.com/apache/airflow/main/Dockerfile"
```

或指定分支／tag：

```bash
curl -o docker/Dockerfile.airflow "https://raw.githubusercontent.com/apache/airflow/2.10.0/Dockerfile"
```

下載後在專案根目錄執行 `./scripts/build.sh`。
