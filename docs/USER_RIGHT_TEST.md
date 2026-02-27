# 伺服器權限測試（User Right Test）

本文件用於在**實際執行 CI 或跑 Airflow 的伺服器**上，確認當前使用者是否具備足夠權限執行建置、啟動與測試。請以 **CI Runner 會使用的同一個使用者**（或部署帳號）登入後，依序執行下列檢查。

---

## 一、使用者與群組

在伺服器上執行下列指令，確認身分與是否在 `docker` 群組（Docker 通常需 docker 群組才能無 sudo 執行）。

| # | 指令 | 預期／說明 |
|---|------|------------|
| 1.1 | `whoami` | 顯示目前使用者（請記錄，CI 時應為同一使用者） |
| 1.2 | `id` | 查看 uid、gid 及所屬群組 |
| 1.3 | `groups` | 清單中應包含 **docker**（若無，需將使用者加入 docker 群組：`sudo usermod -aG docker <user>`，並重新登入） |

---

## 二、Docker 權限

以下皆**不需 sudo**，若出現 "permission denied" 或 "Cannot connect to the Docker daemon"，通常是未加入 docker 群組或 Docker 未啟動。

| # | 指令 | 預期／說明 |
|---|------|------------|
| 2.1 | `docker --version` | 顯示版本（建議 23.0+） |
| 2.2 | `docker info` | 可正常輸出，無權限錯誤 |
| 2.3 | `docker run --rm hello-world` | 能拉取並執行後自動刪除，無權限錯誤 |
| 2.4 | `docker network create test-net-$$ && docker network rm test-net-$$` | 可建立並刪除 network（`$$` 為 PID，避免重複） |
| 2.5 | `docker ps -a` | 可列出容器（含其他使用者的容器，依 Docker 設定而定） |
| 2.6 | `DOCKER_BUILDKIT=1 docker build --help \| head -1` | 支援 BuildKit（建置腳本會用到） |

---

## 三、專案目錄與腳本

假設專案位於 `$PROJECT_ROOT`（例如 `/path/to/AirFlow` 或 CI 的 `$CI_PROJECT_DIR`）。在該目錄下執行：

| # | 指令 | 預期／說明 |
|---|------|------------|
| 3.1 | `cd "$PROJECT_ROOT" && pwd` | 能進入專案根目錄 |
| 3.2 | `test -r scripts/build.sh && echo OK || echo FAIL` | 輸出 OK（可讀） |
| 3.3 | `test -x scripts/build.sh && echo OK || echo FAIL` | 輸出 OK（可執行） |
| 3.4 | `test -x scripts/start-airflow.sh && test -x scripts/stop-airflow.sh && echo OK || echo FAIL` | 輸出 OK |
| 3.5 | `test -d dags && echo OK || echo FAIL` | 輸出 OK（dags 目錄存在） |
| 3.6 | `test -r config/env.example && echo OK || echo FAIL` | 輸出 OK（可讀設定範例） |

若 3.3 / 3.4 為 FAIL，可執行：`chmod +x scripts/*.sh`

---

## 四、建置所需權限（模擬 CI build stage）

在專案根目錄執行。此段會**實際下載 Dockerfile 並執行 build**（耗時較久），僅在需要驗證「建置權限」時執行。

| # | 指令 | 預期／說明 |
|---|------|------------|
| 4.1 | `./scripts/download-dockerfile.sh` | 成功下載至 `docker/Dockerfile.airflow`，無權限錯誤 |
| 4.2 | `export DOCKER_BUILDKIT=1; export AIRFLOW_IMAGE_TAG=right-test; ./scripts/build.sh` | 能完成 `docker build` 並產出 `airflow:right-test`（可選，建置時間長） |

若僅要快速確認「docker build 權限」而不建完整映像，可改為：

```bash
docker build -f docker/Dockerfile.airflow --build-arg AIRFLOW_VERSION=3.2.0 -t airflow:right-test . 2>&1 | head -20
```

能開始建置且無 "permission denied" 即表示具建置權限（可隨後 `docker rmi airflow:right-test` 或 Ctrl+C 中斷）。

---

## 五、執行與網路埠（模擬 start / integration）

以下確認：能建立 network、拉取/使用映像、綁定埠、以及本機 curl。**執行前請確認 5432、8080 未被佔用**（或先跑 `./scripts/stop-airflow.sh` 清理舊容器）。

| # | 指令 | 預期／說明 |
|---|------|------------|
| 5.1 | `docker network create airflow-net` | 成功建立（若已存在會報錯，可改為 `docker network inspect airflow-net` 確認可存取） |
| 5.2 | `docker run -d --rm --name airflow-db -e POSTGRES_PASSWORD=p -e POSTGRES_USER=u -e POSTGRES_DB=d --network airflow-net -p 5432:5432 postgres:15-alpine` | 能拉取 postgres 映像並啟動，無權限錯誤 |
| 5.3 | `sleep 3; docker exec airflow-db pg_isready -U u` | 輸出含 "accepting connections" |
| 5.4 | `docker stop airflow-db` | 成功停止（`--rm` 會自動刪除容器） |
| 5.5 | `docker network rm airflow-net` | 成功刪除 network |
| 5.6 | `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/health 2>/dev/null || echo "no service"` | 若 Airflow 未運行，可能為 000 或 "no service"；若有跑 webserver，應為 200。此項主要確認**本機可對 8080 發請求**（CI 健康檢查會用 curl localhost:8080） |
| 5.7 | `nc -z 127.0.0.1 8080 2>/dev/null && echo PORT_IN_USE || echo PORT_FREE` | 未啟動 Airflow 時應為 PORT_FREE，避免與既有服務衝突 |

---

## 六、Volume 掛載（DAG 目錄）

腳本會將主機的 `dags/` 掛載進容器，需確認該目錄可被讀取（CI 通常為唯讀）。

| # | 指令 | 預期／說明 |
|---|------|------------|
| 6.1 | `cd "$PROJECT_ROOT" && docker run --rm -v "$(pwd)/dags:/opt/airflow/dags:ro" alpine ls -la /opt/airflow/dags` | 能列出 dags 目錄內容，無 "permission denied"（`:ro` 表示唯讀，與 CI 情境一致） |
| 6.2 | `docker run --rm -v "$(pwd)/dags:/opt/airflow/dags" alpine touch /opt/airflow/dags/.write-test 2>&1; rm -f dags/.write-test 2>/dev/null; echo DONE` | 若需在 dags 內寫入（例如測試），確認可寫；不需寫入則可略過 |

---

## 七、CI 環境變數（僅在 GitLab Runner 上檢查）

若在 **GitLab Shell Runner** 的 job 環境中執行，可確認 CI 專案路徑與變數：

| # | 指令 | 預期／說明 |
|---|------|------------|
| 7.1 | `echo "CI_PROJECT_DIR=$CI_PROJECT_DIR"` | 有值（專案目錄路徑） |
| 7.2 | `test -n "$CI_COMMIT_SHA" && echo "CI_COMMIT_SHA is set"` | 在 pipeline 中應有值 |
| 7.3 | `cd "$CI_PROJECT_DIR" && ./scripts/start-airflow.sh` | 能依序啟動容器（需已有 build 產出的 airflow 映像，或先以本機 build 的 tag 設定 AIRFLOW_IMAGE） |

---

## 八、快速檢查腳本

專案內已提供一鍵檢查腳本，在專案根目錄執行（腳本會自動辨識專案根目錄）：

```bash
./prerequirement/test.sh
```

腳本會依序檢查：使用者與 docker 群組、Docker 權限、專案與 scripts 可執行、dags volume 掛載、network 與 postgres 試跑、curl 可用性、以及 CI 變數（若在 Runner 環境）。最後輸出通過／失敗數量，任一失敗則 exit code 為 1。

---

## 九、檢查結果記錄表

可依下表在伺服器上逐項執行並打勾，方便留存與排查。

| 章節 | 項目 | 通過 ✓ / 失敗 ✗ | 備註 |
|------|------|------------------|------|
| 一 | 使用者與群組（含 docker 群組） | | |
| 二 | Docker 權限（run、network、info） | | |
| 三 | 專案目錄與腳本可讀可執行 | | |
| 四 | 建置權限（可選） | | |
| 五 | 建立 network、run 容器、埠與 curl | | |
| 六 | DAG 目錄 volume 掛載 | | |
| 七 | CI 變數（僅 Runner 環境） | | |

若所有與你使用情境相關的項目均通過，則該使用者在該伺服器上具備執行本專案 **build、start、stop 與 CI 整合測試** 所需的權限。
