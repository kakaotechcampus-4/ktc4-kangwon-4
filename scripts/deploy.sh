#!/usr/bin/env bash
# 운영 EC2에 정한 커밋 하나를 올린다. docs/deploy.md 1~4단계를 그대로 옮긴 것이다.
#
#   bash scripts/deploy.sh <커밋>      # EC2의 /home/ubuntu/app에서, root로
#   CHECK_ONLY=1 bash scripts/deploy.sh <커밋>   # 1단계 확인만 하고 서버는 건드리지 않는다
#
# GitHub Actions(deploy.yml)가 Session Manager로 부르고, 서버에서 손으로 돌려도 똑같다.
# 어느 단계든 실패하면 거기서 멈춘다. SQL이 필요한 배포는 하지 않는다 — 손으로 deploy.md를 따른다.
set -euo pipefail

TARGET=${1:?올릴 커밋을 넘겨 주세요}
APP=/home/ubuntu/app
BACKUP=/home/ubuntu/backup
HEALTH=https://reborn-ktc.duckdns.org/health
C="docker compose -f docker-compose.prod.yml"
cd "$APP"

fail() { echo "실패: $*"; exit 1; }

# 백업부터 반영까지는 FastAPI가 멈춰 있다. 중간에 실패하면 원래 컨테이너라도 다시 켜서 서비스를 살린다
stopped=""
on_exit() { if [ $? -ne 0 ] && [ -n "$stopped" ]; then echo "멈췄던 FastAPI를 다시 켭니다"; $C start fastapi || true; fi; }
trap on_exit EXIT

echo "== 1/4 확인 =="
grep -q '^ENVIRONMENT=prod' .env.prod || fail ".env.prod가 prod가 아닙니다. dev로 켜면 표가 전부 지워집니다"
git fetch --quiet origin
SHA=$(git rev-parse --verify "${TARGET}^{commit}") || fail "커밋 ${TARGET}을 찾지 못했습니다"
BEFORE=$(git rev-parse --short HEAD)
git merge-base --is-ancestor "$SHA" origin/develop || fail "develop에 머지된 커밋만 올립니다"
git merge-base --is-ancestor HEAD "$SHA" || fail "지금 커밋(${BEFORE})보다 앞선 커밋입니다. 되돌리기는 deploy.md 5단계로 합니다"
[ "$(git rev-parse HEAD)" != "$SHA" ] || { echo "이미 ${BEFORE}이 올라가 있습니다. 할 일이 없습니다"; exit 0; }
# 표가 바뀌는 배포는 SQL을 넣고 켜야 해서 자동으로 하지 않는다(11/9 SQL005)
changed=$(git diff --name-only HEAD "$SHA" -- backend/sql backend/app/be/models)
[ -z "$changed" ] || fail "DB 표가 바뀌는 배포라 자동으로 하지 않습니다. docs/deploy.md대로 손으로 올려 주세요:
$changed"
echo "지금 ${BEFORE} → 올릴 $(git rev-parse --short "$SHA")"
[ -z "${CHECK_ONLY:-}" ] || { echo "확인만 했습니다. 서버는 그대로입니다"; exit 0; }

echo "== 2/4 백업 (FastAPI 멈춤) =="
mkdir -p "$BACKUP"
TS=$(date +%Y%m%d-%H%M)
$C logs --no-color fastapi > "$BACKUP/fastapi-$TS.log"
stopped=1
$C stop fastapi
$C exec -T mysql mysqldump --defaults-extra-file=/run/secrets/mysql_health_cnf \
  --single-transaction --default-character-set=utf8mb4 closure_agent > "$BACKUP/db-$TS.sql"
$C run --rm --no-deps -T fastapi tar czf - -C /data/documents . > "$BACKUP/documents-$TS.tgz"
tail -n 1 "$BACKUP/db-$TS.sql" | grep -q '^-- Dump completed' || fail "DB 백업이 끝까지 받아지지 않았습니다"
tar tzf "$BACKUP/documents-$TS.tgz" > /dev/null || fail "서류 백업 파일이 깨졌습니다"
echo "백업 $TS (되돌릴 때 씁니다)"

echo "== 3/4 반영 =="
git merge --ff-only "$SHA"
VERSION=$(git rev-parse --short HEAD)
GIT_SHA=$VERSION $C up -d --build
stopped=""

echo "== 4/4 /health 확인 =="
for _ in $(seq 1 30); do
  if curl -fsS -m 5 "$HEALTH" | grep -q "\"version\":\"$VERSION\""; then
    echo "배포 끝: ${BEFORE} → ${VERSION}, 백업 $TS"
    exit 0
  fi
  sleep 3
done
$C ps
$C logs --tail 50 fastapi
fail "90초 안에 /health가 ${VERSION}을 보여 주지 않았습니다. 되돌리기는 deploy.md 5단계(되돌릴 커밋 ${BEFORE}, 백업 $TS)"
