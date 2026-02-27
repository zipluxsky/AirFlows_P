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

echo "=============================================="
echo "  Server Permission / User Right Test"
echo "  Project root: $PROJECT_ROOT"
echo "=============================================="

echo ""
echo "=== 1. User & groups ==="
whoami
id
if groups | grep -q docker; then
  pass "User is in group 'docker'"
else
  fail "User not in group 'docker' (Docker may require it)"
fi

echo ""
echo "=== 2. Docker ==="
if docker --version; then
  pass "docker --version"
else
  fail "docker --version"
fi
if docker info &>/dev/null; then
  pass "docker info"
else
  fail "docker info (permission or daemon)"
fi
if docker run --rm hello-world &>/dev/null; then
  pass "docker run --rm hello-world"
else
  fail "docker run (pull/run permission)"
fi
NET_NAME="test-net-$$"
if docker network create "$NET_NAME" &>/dev/null && docker network rm "$NET_NAME" &>/dev/null; then
  pass "docker network create/rm"
else
  fail "docker network create/rm"
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
if docker run --rm -v "$(pwd)/dags:/opt/airflow/dags:ro" alpine ls /opt/airflow/dags &>/dev/null; then
  pass "Volume mount dags (read-only)"
else
  fail "Volume mount dags"
fi

echo ""
echo "=== 5. Network & ports (quick check) ==="
if docker network create airflow-net &>/dev/null 2>&1; then
  pass "docker network create airflow-net"
  if docker run -d --rm --name airflow-db-test -e POSTGRES_PASSWORD=p -e POSTGRES_USER=u -e POSTGRES_DB=d --network airflow-net -p 5432:5432 postgres:15-alpine &>/dev/null; then
    sleep 2
    if docker exec airflow-db-test pg_isready -U u &>/dev/null; then
      pass "PostgreSQL container run & pg_isready"
    else
      fail "pg_isready"
    fi
    docker stop airflow-db-test &>/dev/null || true
  else
    fail "PostgreSQL container run (pull/port?)"
  fi
  docker network rm airflow-net &>/dev/null || true
else
  # network may already exist from previous run
  if docker network inspect airflow-net &>/dev/null; then
    pass "airflow-net exists (inspect OK)"
  else
    fail "docker network create airflow-net"
  fi
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
