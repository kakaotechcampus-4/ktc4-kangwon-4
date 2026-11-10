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

# 같은 서버에서 배포가 겹치지 않게 한다. Actions가 20분 뒤 끝나도 이 스크립트는 계속 돌고 있을 수
# 있고, 그때 큐에 있던 다음 배포가 시작되면 둘이 같은 저장소·백업·Compose를 건드린다(승준님 #321)
exec 9>/var/lock/reborn-deploy.lock
flock -n 9 || fail "이 서버에서 다른 배포가 돌고 있습니다. 끝난 뒤에 다시 해 주세요"

# 백업부터 반영까지는 FastAPI가 멈춰 있다. 중간에 실패하면 원래 컨테이너라도 다시 켜서 서비스를 살린다
stopped=""
on_exit() { if [ $? -ne 0 ] && [ -n "$stopped" ]; then echo "멈췄던 FastAPI를 다시 켭니다"; $C start fastapi || true; fi; }
trap on_exit EXIT

echo "== 1/4 확인 =="
# .env.prod를 글자로 검사하지 않는다. 같은 이름이 여러 줄이면 마지막 값이 적용되는데,
# ' ENVIRONMENT=dev' · 'ENVIRONMENT =dev' · 'export ENVIRONMENT=dev'는 어떤 grep 규칙을 써도
# 앞줄만 보고 통과시킬 수 있고 Compose는 dev로 읽는다(승준님 #337, 세 형식 모두 재현).
# 그래서 Compose가 해석한 fastapi의 ENVIRONMENT를 직접 읽는다. 컨테이너를 만들지 않으므로
# CHECK_ONLY가 "서버를 건드리지 않는다"는 약속도 지킨다(현석님 #337). 그 한 칸만 꺼내 변수에
# 담고 출력하지 않아 다른 환경값·비밀값은 로그에 남지 않는다.
# dev로 켜면 main.py가 reset_all_tables()로 운영 표를 전부 지운다.
REAL_ENV=$($C config --format json fastapi \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["fastapi"].get("environment",{}).get("ENVIRONMENT",""))') \
  || fail "compose 설정을 읽지 못했습니다. docker compose가 이 파일을 읽을 수 있는지 먼저 확인해 주세요"
[ "$REAL_ENV" = "prod" ] \
  || fail "fastapi가 ENVIRONMENT=${REAL_ENV:-없음}으로 뜹니다. prod가 아니면 켤 때 표가 전부 지워집니다"
git fetch --quiet origin
SHA=$(git rev-parse --verify "${TARGET}^{commit}") || fail "커밋 ${TARGET}을 찾지 못했습니다"
BEFORE=$(git rev-parse --short HEAD)
git merge-base --is-ancestor "$SHA" origin/develop || fail "develop에 머지된 커밋만 올립니다"
git merge-base --is-ancestor HEAD "$SHA" || fail "지금 커밋(${BEFORE})보다 앞선 커밋입니다. 되돌리기는 deploy.md 5단계로 합니다"
# 저장소만 보면 안 된다. 지난 배포가 merge 뒤 빌드에서 멈췄으면 저장소는 새 커밋, 서버는 옛 커밋이다(현종님 #321).
# 올릴 커밋이 무엇이든 먼저 본다 — 같은 커밋일 때만 보면, 더 새 커밋을 지정했을 때 그냥 지나간다(승준님 #321)
RUNNING=$(curl -fsS -m 5 "$HEALTH" | sed -n 's/.*"version":"\([^"]*\)".*/\1/p') \
  || fail "/health를 읽지 못했습니다. 서버가 떠 있는지 먼저 확인해 주세요"
[ "$RUNNING" = "$BEFORE" ] \
  || fail "저장소는 ${BEFORE}인데 서버는 ${RUNNING}입니다. 지난 배포가 반영 중에 멈춘 것 같습니다. deploy.md 3단계부터 손으로 이어 가 주세요"
if [ "$(git rev-parse HEAD)" = "$SHA" ]; then
  echo "이미 ${BEFORE}이 올라가 있습니다. 할 일이 없습니다"
  exit 0
fi
# 손으로 고친 추적 파일(Caddyfile 등)이 있으면 merge가 거부된다. FastAPI를 멈추기 전에 여기서 막는다(현종님 #321)
git diff --quiet HEAD || fail "서버에 손으로 고친 파일이 있습니다. 먼저 정리해 주세요:
$(git diff --name-only HEAD)"
# 표가 바뀌는 배포는 SQL을 넣고 켜야 해서 자동으로 하지 않는다(11/9 SQL005)
changed=$(git diff --name-only HEAD "$SHA" -- backend/sql backend/app/be/models)
[ -z "$changed" ] || fail "DB 표가 바뀌는 배포라 자동으로 하지 않습니다. docs/deploy.md대로 손으로 올려 주세요:
$changed"
echo "지금 ${BEFORE} → 올릴 $(git rev-parse --short "$SHA")"
[ -z "${CHECK_ONLY:-}" ] || { echo "확인만 했습니다. 서버는 그대로입니다"; exit 0; }

echo "== 2/4 백업 (FastAPI 멈춤) =="
mkdir -p "$BACKUP"
# 초 단위 이름으로는 모자란다. 같은 초에 실패한 뒤 바로 다시 돌리면 이름이 겹쳐 앞 백업을 덮어쓴다
# (flock은 동시에 도는 것만 막지, 실패 뒤 재시도는 못 막는다 — 승준님 #337).
# mktemp -d로 실행마다 새 폴더를 원자적으로 만든다. 이미 있으면 만들지 않으므로 덮어쓸 수 없다.
RUN_DIR=$(mktemp -d "$BACKUP/$(date +%Y%m%d-%H%M%S)-XXXXXX") \
  || fail "백업 폴더를 만들지 못했습니다: $BACKUP"
TS=$(basename "$RUN_DIR")
$C logs --no-color fastapi > "$RUN_DIR/fastapi.log"
stopped=1
$C stop fastapi
$C exec -T mysql mysqldump --defaults-extra-file=/run/secrets/mysql_health_cnf \
  --single-transaction --default-character-set=utf8mb4 closure_agent > "$RUN_DIR/db.sql"
$C run --rm --no-deps -T fastapi tar czf - -C /data/documents . > "$RUN_DIR/documents.tgz"
tail -n 1 "$RUN_DIR/db.sql" | grep -q '^-- Dump completed' || fail "DB 백업이 끝까지 받아지지 않았습니다"
tar tzf "$RUN_DIR/documents.tgz" > /dev/null || fail "서류 백업 파일이 깨졌습니다"
echo "백업 $BACKUP/$TS (되돌릴 때 씁니다)"

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
