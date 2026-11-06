# 배포 순서 (EC2)

실서버에 develop을 올릴 때 이 순서대로 칩니다. 명령은 모두 EC2의 `/home/ubuntu/app`(저장소, `docker-compose.prod.yml`이 있는 곳)에서 칩니다.

- 서버 구성: Caddy(80·443, `Caddyfile`) → FastAPI(`127.0.0.1:8000`) → MySQL `8.0.46`(`127.0.0.1:3306`). 서류 파일은 `document_data` 볼륨(`/data/documents`)에 있습니다
- 운영은 `ENVIRONMENT=prod`라 **서버를 켜도 표를 만들거나 지우지 않습니다**(`backend/app/main.py`). 표를 만들고 고치는 건 `backend/sql/`의 SQL로 합니다
- 명령을 짧게 쓰려고 아래 두 변수를 먼저 만들어 둡니다. `C`는 compose, `MYSQL`은 DB 컨테이너 안의 mysql 클라이언트입니다

```bash
cd /home/ubuntu/app
C="docker compose -f docker-compose.prod.yml"
MYSQL="$C exec -T mysql mysql --defaults-extra-file=/run/secrets/mysql_health_cnf --default-character-set=utf8mb4"
```

## 1. 배포 전 확인

```bash
git log -1 --oneline                 # 지금 올라가 있는 커밋. 되돌릴 때 쓰니 적어 둔다
grep '^ENVIRONMENT' .env.prod        # prod여야 한다. dev면 서버를 켤 때마다 표가 전부 지워진다
```

**표가 바뀌는 배포인지 본다.** 지금 커밋과 올릴 develop 사이에 모델이 바뀌었으면 SQL이 필요합니다.

```bash
git fetch origin
git diff --stat HEAD origin/develop -- backend/app/be/models backend/sql
```

- 모델에서 칸·ENUM 값이 바뀌었는데(`001_schema.sql`도 같이 바뀜) 새 `00N_*.sql`이 없으면, **운영 DB를 고칠 SQL이 빠진 것**입니다. 배포를 멈추고 PR을 확인합니다. CI는 이걸 잡지 못합니다(`001` 머리말)
- 새 `00N_*.sql`이 있으면 3단계에서 넣습니다

## 2. 백업

DB와 서류 폴더를 **같은 시각에 같이** 받습니다. DB만 되돌리면 서류 목록·점검 결과(폴더의 파일)와 어긋납니다. 서류는 fastapi 컨테이너 안의 `tar`로 받아서 fastapi가 떠 있어야 합니다.

```bash
mkdir -p ~/backup && TS=$(date +%Y%m%d-%H%M) && echo $TS    # TS는 되돌릴 때 쓰니 적어 둔다
$C exec -T mysql mysqldump --defaults-extra-file=/run/secrets/mysql_health_cnf \
  --single-transaction --default-character-set=utf8mb4 closure_agent > ~/backup/db-$TS.sql
$C exec -T fastapi tar czf - -C /data/documents . > ~/backup/documents-$TS.tgz

# 제대로 받았는지
tail -n 1 ~/backup/db-$TS.sql              # "-- Dump completed on …"이 나와야 한다
tar tzf ~/backup/documents-$TS.tgz | head
```

`~/backup`은 EC2 디스크 안이라 EC2가 망가지면 같이 잃습니다. 큰 배포 전에는 내 컴퓨터로도 한 부 받아 둡니다.

## 3. 반영

```bash
git pull

# 1단계에서 새 00N_*.sql이 있었을 때만, 번호 순서대로
$MYSQL closure_agent < backend/sql/00N_xxx.sql

$C up -d --build
```

- `.env.prod`만 바꿨을 때도 `restart`가 아니라 `$C up -d fastapi`입니다. `restart`는 바뀐 환경 변수를 읽지 않습니다
- 서버가 켜질 때 지난번에 꺼지며 남은 판단(`PENDING`)을 실패(`RETRY`)로 풀어 줍니다(#194). 사장님은 홈의 [다시 판단하기]로 이어 갈 수 있습니다

## 4. 확인

```bash
$C ps                                                # fastapi·mysql 둘 다 healthy
curl -s https://reborn-ktc.duckdns.org/health        # {"status":"ok"}
$C logs --tail 50 fastapi                            # 시작 오류가 없는지
```

- `/health`는 DB에 `SELECT 1`까지 보냅니다(#219). DB가 안 되면 503 `{"status":"unavailable"}`이고 fastapi가 `unhealthy`로 보입니다. 그때는 `$C logs mysql`부터 봅니다
- 화면에서 로그인 → 홈까지 한 번 들어가 봅니다

## 5. 문제가 생기면 되돌리기

**코드만 되돌리기** — 표를 바꾸지 않은 배포면 이것으로 충분합니다.

```bash
git checkout <1단계에서 적은 커밋>
$C up -d --build
# 고친 뒤 다시 올릴 때는 git checkout develop && git pull
```

**DB·서류까지 되돌리기** — 그 시점으로 **통째로** 바뀝니다. 백업 뒤에 사장님이 넣은 내용은 사라집니다. 백업 파일이 온전한지 먼저 보고, 아니면 지우기 전에 멈춥니다.

```bash
TS=<2단계에서 적은 값>
tail -n 1 ~/backup/db-$TS.sql | grep -q '^-- Dump completed' \
  && $MYSQL closure_agent < ~/backup/db-$TS.sql
tar tzf ~/backup/documents-$TS.tgz > /dev/null \
  && $C exec -T fastapi sh -c 'find /data/documents -mindepth 1 -delete && tar xzf - -C /data/documents' \
       < ~/backup/documents-$TS.tgz
$C restart fastapi
```

- 잘린 DB 백업을 넣으면 앞쪽 표만 지우고 다시 만든 채 멈춰 일부 표가 빕니다. 그래서 마지막 줄을 먼저 봅니다
- 서류는 지우고 나서 풀다 깨지면 이미 늦어서, 풀기 전에 `tar tzf`로 읽어 봅니다(#224)

## 그 밖에

### 시연 계정을 가입 전으로

그 회원의 Case와 딸린 기록만 지웁니다. 회원은 남아서 같은 카카오 계정으로 로그인하면 진단부터 시작합니다(`backend/sql/reset_member_case.sql`).

```bash
$MYSQL closure_agent -e "SELECT m.id, m.nickname, c.id AS case_id FROM members m LEFT JOIN \`case\` c ON c.member_id = m.id;"
$C exec -T mysql mysql --defaults-extra-file=/run/secrets/mysql_health_cnf \
  --init-command="SET @member_id = 7" closure_agent < backend/sql/reset_member_case.sql
```

끝에 나오는 `case_id`가 `NULL`이면 지운 게 없습니다(번호를 안 넘겼거나 Case가 없는 회원).

### 빈 DB에 처음 만들 때

새 서버이거나 DB를 통째로 다시 만들 때만 씁니다. 이미 표가 있으면 "already exists"로 멈추고 아무것도 지우지 않습니다.

```bash
$MYSQL closure_agent < backend/sql/001_schema.sql
$C restart fastapi     # 절차 기준 표는 서버가 켜질 때 채운다
```

### 검수 자료 버전을 올렸을 때

절차조회는 Case 근거의 버전이 지금 검수 자료 버전과 같은 것만 고릅니다. 버전을 올리면 기존 Case를 옮겨야 그 Case가 "자료 없음"이 되지 않습니다(`backend/scripts/import_reviewed_procedures.py`, `docs/hero-scenario.md`). 이 스크립트는 배포 이미지에 들어 있지 않아서, 필요할 때 AI팀과 실행 방법을 같이 정합니다.
