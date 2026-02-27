# AirFlow 架構說明

本文件描述當前專案的架構、元件與流程。實作步驟與檢查清單見 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)。

---

## 一、概述與目標

- **目標**：從 Apache Airflow 源碼或指定版本建置自訂 Docker 映像，以**多個獨立容器**運行（不使用 docker-compose），並以 GitLab CI 做建置與整合測試。
- **約束**：GitLab 使用 **shell executor**、**不推送至 Container Registry**；建置與執行在同一台 Runner 主機完成。
- **自建映像**：僅 **1 個** Airflow 映像，供 scheduler、webserver、worker、flower 共用；PostgreSQL 與 Redis 使用官方映像。

---

## 二、架構概覽

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                  Docker Network: airflow-net            │
                    │                                                         │
  ┌─────────────────┤  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
  │  Host dags/      │  │ airflow-db   │  │ airflow-     │  │ airflow-    │  │
  │  (volume mount)  │  │ (PostgreSQL) │  │ scheduler    │  │ webserver   │  │
  └────────┬────────┘  │ postgres:15  │  │              │  │             │  │
           │           └──────┬───────┘  │ airflow:xxx  │  │ airflow:xxx │  │
           │                  │          └──────┬───────┘  └──────┬──────┘  │
           │                  │                 │                 │         │
           │                  │          ┌──────┴───────┐  ┌──────┴──────┐  │
           └──────────────────┼─────────►│ /opt/airflow │  │ :8080       │  │
                              │          │ /dags        │  │             │  │
                              │          └──────────────┘  └──────────────┘  │
                              │                                                 │
                    │  CeleryExecutor 時額外：                                  │
                    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
                    │  │ airflow-redis│  │ celery-worker│  │ airflow-     │   │
                    │  │ redis:7     │  │ airflow:xxx  │  │ flower :5555 │   │
                    │  └──────────────┘  └──────────────┘  └──────────────┘   │
                    └─────────────────────────────────────────────────────────┘
```

---

## 三、元件說明

### 3.1 Docker 映像

| 映像 | 來源 | 用途 |
|------|------|------|
| `airflow:<tag>` | 本專案 `scripts/build.sh` 建置 | Scheduler、Webserver、Celery Worker、Flower（同一映像） |
| `postgres:15-alpine` | Docker Hub | Metadata 資料庫（airflow-db） |
| `redis:7-alpine` | Docker Hub | Celery broker（僅 CeleryExecutor 時使用） |

**重要**：新增或修改 DAG 時**不需重新建置** Airflow 映像；DAG 透過 volume 掛載 `dags/`，更新檔案即可。

### 3.2 容器與埠

| 容器名稱 | 映像 | 埠（主機） | 說明 |
|----------|------|------------|------|
| airflow-db | postgres:15-alpine | 5432 | PostgreSQL，存放 metadata |
| airflow-scheduler | airflow:xxx | — | 排程 DAG 與 task |
| airflow-webserver | airflow:xxx | 8080 | Web UI |
| airflow-redis | redis:7-alpine | 6379 | 僅 CeleryExecutor |
| airflow-celery-worker | airflow:xxx | — | 僅 CeleryExecutor，執行 task |
| airflow-flower | airflow:xxx | 5555 | 僅 CeleryExecutor，監控 Celery |

容器名稱可由環境變數覆寫（如 `AIRFLOW_DB_CONTAINER`、`AIRFLOW_WEBSERVER_CONTAINER` 等）。

### 3.3 網路

- 所有容器接在 **bridge 網路** `airflow-net`（可透過 `AIRFLOW_NETWORK` 覆寫）。
- 資料庫連線字串以容器名稱為 host（例如 `airflow-db:5432`），不需對外暴露埠即可互通。

---

## 四、執行模式（Executor）

由環境變數 `AIRFLOW__CORE__EXECUTOR` 決定。

### 4.1 LocalExecutor（預設）

- **設定**：`AIRFLOW__CORE__EXECUTOR=LocalExecutor`
- **容器**：airflow-db、airflow-scheduler、airflow-webserver
- **特點**：不需 Redis，task 在 scheduler 所在進程內執行，適合單機、輕量。

### 4.2 CeleryExecutor

- **設定**：`AIRFLOW__CORE__EXECUTOR=CeleryExecutor`，並設定 `AIRFLOW__CELERY__BROKER_URL`、`AIRFLOW__CELERY__RESULT_BACKEND`
- **容器**：上述三者 + airflow-redis、airflow-celery-worker、airflow-flower
- **特點**：可水平擴展多個 worker；Flower 提供 http://localhost:5555 監控介面。

範例環境變數見 `config/env.example`。

---

## 五、目錄與關鍵檔案

```
AirFlow/
├── .dockerignore           # 建置 context 排除清單
├── .gitlab-ci.yml          # CI：build → integration（MR 觸發）
├── README.md
├── docker/
│   ├── Dockerfile.airflow  # 官方 Dockerfile（可由 download-dockerfile.sh 下載）
│   ├── README.md           # Dockerfile 下載說明
│   └── context/
│       └── requirements.txt  # 可選，自訂 PyPI 依賴
├── scripts/
│   ├── build.sh            # 建置 Airflow 映像（A1 或 source 模式）
│   ├── download-dockerfile.sh  # 下載 Dockerfile 至 docker/Dockerfile.airflow
│   ├── start-airflow.sh    # 建立 network、依序啟動 DB → (Redis) → init → scheduler → webserver → (worker, flower)
│   └── stop-airflow.sh     # 停止所有上述容器並移除 network
├── dags/                   # DAG 目錄，執行時掛載至容器 /opt/airflow/dags
│   └── .gitkeep
├── config/
│   └── env.example         # 環境變數範例（DB、Executor、Celery）
└── docs/
    ├── ARCHITECTURE.md     # 本文件
    └── IMPLEMENTATION_PLAN.md
```

---

## 六、建置與部署流程

### 6.1 建置 Airflow 映像

- **方案 A1（預設）**：使用 `docker/Dockerfile.airflow`（可先執行 `./scripts/download-dockerfile.sh`），從 PyPI 安裝指定版本。
  - 本機：`./scripts/build.sh`
  - 產出：`airflow:${AIRFLOW_IMAGE_TAG}`（預設 `airflow:3.2.0-custom`）
- **方案 source**：從 GitHub clone 源碼後，在該目錄以 `BUILD_MODE=source` 與 `AIRFLOW_SOURCE_DIR` 呼叫 build.sh，從源碼建置。
- **跨平台**：在 Apple Silicon 建給 Rocky Linux 時：`DOCKER_PLATFORM=linux/amd64 ./scripts/build.sh`

### 6.2 啟動與停止

- **啟動**：在專案根目錄執行 `./scripts/start-airflow.sh`（可先 `source config/env.example` 或設定所需環境變數）。
- **停止**：`./scripts/stop-airflow.sh`（依序停止 flower → worker → webserver → scheduler → redis → db，並移除 network）。

DAG 目錄由 `DAGS_MOUNT` 決定（預設 `$PROJECT_ROOT/dags`）；CI 中會使用 `$CI_PROJECT_DIR/dags`。

---

## 七、CI/CD（GitLab）

- **觸發**：Merge Request 時（`rules: if: $CI_PIPELINE_SOURCE == "merge_request_event"`）。
- **Stages**：
  1. **build**：下載 Dockerfile → 執行 `scripts/build.sh`，tag 為 `airflow:${CI_COMMIT_SHA}`。
  2. **integration**：`scripts/start-airflow.sh` → 輪詢 http://localhost:8080/health → 執行 `airflow dags list` → `after_script` 執行 `scripts/stop-airflow.sh`。
- **Runner**：需使用 **shell executor**、具 Docker 權限；build 與 integration 須在同一台（相同 `tags: [shell]`），不推送映像至 Registry。

---

## 八、小結

| 項目 | 說明 |
|------|------|
| 自建映像數 | 1 個（Airflow），其餘為官方 postgres/redis |
| DAG 更新 | 僅更新 `dags/` 檔案，不需重建映像 |
| 執行模式 | LocalExecutor（預設）或 CeleryExecutor（需 Redis + worker + flower） |
| 部署方式 | Shell 腳本起停，無 docker-compose |
| CI | 單一 pipeline：build → integration，MR 觸發，shell runner、無 Registry |

更細的建置步驟、檢查表與風險見 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)。
