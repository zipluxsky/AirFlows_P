# Airflow Source Code Requirement（本專案所需源碼說明）

本文件說明在本專案中，**從 Apache Airflow 官方倉庫取得的 source code 的用途**，以及建置 production Docker image 時**必須保留**與**可選移除**的目錄與檔案。

---

## 一、在本專案中的用途

本專案使用 Airflow 源碼的唯一用途為：**從 source 建置自訂的 Airflow Docker image**（即 **BUILD_MODE=source** 之主流程）。

- **建置方式**：在 clone 下來的 Airflow 源碼**根目錄**執行 `docker build`，使用該倉庫內的 **Dockerfile**，並傳入：
  - `AIRFLOW_INSTALLATION_METHOD=.`
  - `AIRFLOW_SOURCES_FROM=.`
  - `AIRFLOW_SOURCES_TO=/opt/airflow`
- **腳本**：由本專案 `scripts/build.sh` 在設定 `BUILD_MODE=source` 且 `AIRFLOW_SOURCE_DIR` 指向源碼目錄時執行上述建置。
- **源碼擺放位置**：可置於本專案外（例如 `airflow-src/`）或本專案內（例如 `source/` 或 `AirFlow_P/source`），建置時以 `AIRFLOW_SOURCE_DIR` 指定路徑即可。

本專案**不**在 source 上做二次開發或修改 Airflow 核心程式；僅**讀取**源碼並交給官方 Dockerfile 建出 image。

---

## 二、建置時必須保留的目錄與檔案（Required）

以下為 production image 建置時，Dockerfile 或建置流程會**引用或 COPY** 的內容，**不可刪除**。

| 類型 | 目錄／檔案 | 說明 |
|------|------------|------|
| 建置入口 | `Dockerfile` | 官方多階段 Dockerfile，建置時 `-f Dockerfile` 指定。 |
| 建置腳本 | `scripts/` | 內含 `scripts/docker/` 等，Dockerfile 內嵌或呼叫的腳本（如 install_os_dependencies.sh、依賴安裝等）。 |
| 核心程式 | `airflow-core/` | Airflow 核心套件。 |
| 提供者 | `providers/` | 各類 provider 套件，建置時一併安裝。 |
| 專案設定 | `pyproject.toml` | 依賴與專案定義，建置時會使用。 |
| 依賴約束 | `constraints/` | 依賴版本約束檔，pip/uv 建置時會參考。 |
| 倉庫忽略清單 | `.dockerignore` | 官方倉庫內建，縮小 build context，建置時會依此排除檔案。 |

以上為**本專案從 source 建 image 時必須存在**的內容；缺少任一部分可能導致 `docker build` 失敗或結果不完整。

---

## 三、可選移除的目錄與檔案（Optional，縮小 build context）

以下與 **production image 建置無關**，可於 clone 後、`docker build` 前**選擇性刪除**以縮小 build context 與磁碟佔用。若刪除後建置失敗，應還原或改為僅依賴倉庫內 `.dockerignore` 不手動刪除。詳見 [IMPLEMENTATION_PLAN.md 2.4](IMPLEMENTATION_PLAN.md#24-移除無用檔案縮小-build-context保持專案簡潔)。

| 類型 | 目錄／檔案 | 說明 |
|------|------------|------|
| CI / 開發 | `.github/` | GitHub Actions，建 image 不需。 |
| 文件 | `docs/`、`contributing-docs/`、`RELEASE_NOTES.rst`、`BREEZE.rst`、`CONTRIBUTING.rst` 等 | 建 image 不需。 |
| 測試 | `airflow-ctl-tests/`、`airflow-e2e-tests/`、`docker-tests/`、`helm-tests/`、`kubernetes-tests/`、`task-sdk-integration-tests/` | 建 production image 不需。 |
| 開發工具 | `.devcontainer/`、`.pre-commit-config.yaml`、`.editorconfig`、`.gitpod.yml`、`performance/` | 建 image 不需。 |
| 其他 | `chart/`、`manifests/`、`clients/`、`go-sdk/`、`task-sdk/`、`generated/` 等 | 多數 production 建置不需；若 Dockerfile 或腳本有引用則不可刪。 |

---

## 四、本專案不使用的 Airflow 源碼內容

以下與本專案**建置與運行 Airflow 容器**無關，僅供說明：

- **DAG 檔**：本專案之 DAG 來自專案內 `dags/` 目錄，執行時以 volume 掛載至容器，**不**使用 Airflow 倉庫內的 example dags 作為正式 DAG。
- **Helm / K8s / 其他部署**：本專案以 Shell 腳本起停容器，不使用 Airflow 倉庫內的 `chart/`、`manifests/` 等部署檔。
- **開發 / 貢獻流程**：本專案不修改 Airflow 核心或提交 patch，故不需 BREEZE、contributing-docs、pre-commit 等開發用檔案。

---

## 五、摘要

| 項目 | 說明 |
|------|------|
| 源碼用途 | 僅供「從 source 建置 Airflow Docker image」使用。 |
| 必須保留 | `Dockerfile`、`scripts/`、`airflow-core/`、`providers/`、`pyproject.toml`、`constraints/`、`.dockerignore`。 |
| 可選移除 | 見第三節表列（.github、docs、各類 tests、開發工具、chart、manifests、clients、go-sdk、task-sdk、generated 等）。 |
| 本專案不使用 | 倉庫內 DAG、Helm/K8s 部署、開發貢獻流程相關檔案。 |

建置步驟與變數請依 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) 第二章執行；目錄結構與腳本說明見 [ARCHITECTURE.md](ARCHITECTURE.md)。
