#!/usr/bin/env bash
# 伺服器權限測試（User Right Test）
# 用於確認當前使用者是否具備執行 build / start / stop 與 CI 所需權限。
# 詳見 docs/USER_RIGHT_TEST.md
set -e

PASS=0
FAIL=0

pass() { echo "  OK   $*"; ((PASS++)) || true; }
fail() { echo "  FAIL $*"; ((FAIL++)) || true; }

# 專案根目錄（腳本在 prerequirement/ 下，上一層為根目錄）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 若在 docker 群組則不用 sudo，否則用 sudo 執行 docker（與 build/start/stop 腳本一致）
if groups | grep -qw docker; then DOCKER_CMD="docker"; else DOCKER_CMD="sudo docker"; fi

echo "=============================================="
echo "  Server Permission / User Right Test"
echo "  Project root: $PROJECT_ROOT"
echo "  Docker command: $DOCKER_CMD"
echo "=============================================="

echo ""
echo "=== 1. User & groups ==="
whoami
id
if groups | grep -qw docker; then
  pass "User is in group 'docker' (will use docker without sudo)"
else
  pass "User not in docker group (will use sudo docker)"
fi

echo ""
echo "=== 2. Docker ==="
if $DOCKER_CMD --version; then
  pass "$DOCKER_CMD --version"
else
  fail "$DOCKER_CMD --version"
fi
if $DOCKER_CMD info &>/dev/null; then
  pass "$DOCKER_CMD info"
else
  fail "$DOCKER_CMD info (permission or daemon)"
fi
if $DOCKER_CMD run --rm hello-world &>/dev/null; then
  pass "$DOCKER_CMD run --rm hello-world"
else
  fail "$DOCKER_CMD run (pull/run permission)"
fi
NET_NAME="test-net-$$"
if $DOCKER_CMD network create "$NET_NAME" &>/dev/null && $DOCKER_CMD network rm "$NET_NAME" &>/dev/null; then
  pass "$DOCKER_CMD network create/rm"
else
  fail "$DOCKER_CMD network create/rm"
fi

echo ""
echo "=== 3. Project & scripts ==="
cd "$PROJECT_ROOT"
for f in scripts/build.sh scripts/start-airflow.sh scripts/stop-airflow.sh scripts/download-dockerfile.sh; do
  if [[ -x "$f" ]]; then
    pass "$f executable"
  else
    fail "$f not executable or missing"
  fi
done
if [[ -d dags ]]; then
  pass "dags/ exists"
else
  fail "dags/ missing"
fi
if [[ -r config/env.example ]]; then
  pass "config/env.example readable"
else
  fail "config/env.example not readable"
fi

echo ""
echo "=== 4. Volume mount (dags) ==="
if $DOCKER_CMD run --rm -v "$(pwd)/dags:/opt/airflow/dags:ro" alpine ls /opt/airflow/dags &>/dev/null; then
  pass "Volume mount dags (read-only)"
else
  fail "Volume mount dags"
fi

echo ""
echo "=== 5. Network & ports (quick check) ==="
NET_CREATED=false
if $DOCKER_CMD network create airflow-net &>/dev/null 2>&1; then
  pass "$DOCKER_CMD network create airflow-net"
  NET_CREATED=true
else
  # network already exists: try to stop leftover test containers, remove network, recreate
  if $DOCKER_CMD network inspect airflow-net &>/dev/null; then
    $DOCKER_CMD stop airflow-db-test airflow-db-test-$$ 2>/dev/null || true
    if $DOCKER_CMD network rm airflow-net &>/dev/null && $DOCKER_CMD network create airflow-net &>/dev/null 2>&1; then
      pass "airflow-net recreated (was existing)"
      NET_CREATED=true
    else
      # network in use (e.g. Airflow running): run Postgres check on existing network without removing it
      pass "airflow-net exists (inspect OK)"
      NET_CREATED=true
    fi
  else
    fail "$DOCKER_CMD network create airflow-net"
  fi
fi
if [[ "$NET_CREATED" == true ]]; then
  DB_TEST_NAME="airflow-db-test-$$"
  # Do not bind host port 5432 so this works when airflow-net already has containers (e.g. Airflow running)
  if $DOCKER_CMD run -d --rm --name "$DB_TEST_NAME" -e POSTGRES_PASSWORD=p -e POSTGRES_USER=u -e POSTGRES_DB=d --network airflow-net postgres:15-alpine &>/dev/null; then
    sleep 2
    if $DOCKER_CMD exec "$DB_TEST_NAME" pg_isready -U u &>/dev/null; then
      pass "PostgreSQL container run & pg_isready"
    else
      fail "pg_isready"
    fi
    $DOCKER_CMD stop "$DB_TEST_NAME" &>/dev/null || true
  else
    fail "PostgreSQL container run (pull/port?)"
  fi
  $DOCKER_CMD network rm airflow-net &>/dev/null || true
fi
if command -v curl &>/dev/null; then
  pass "curl available"
else
  fail "curl not found (health check needs it)"
fi

echo ""
echo "=== 6. CI env (optional) ==="
if [[ -n "${CI_PROJECT_DIR:-}" ]]; then
  pass "CI_PROJECT_DIR=$CI_PROJECT_DIR"
else
  echo "  skip CI_PROJECT_DIR (not in CI)"
fi

echo ""
echo "=============================================="
echo "  Result: $PASS passed, $FAIL failed"
echo "=============================================="
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
