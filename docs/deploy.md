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

DB와 서류 폴더를 **같은 시점으로** 받습니다. DB만 되돌리면 서류 목록·점검 결과(폴더의 파일)와 어긋납니다.
그래서 **백업부터 3단계 반영이 끝날 때까지 FastAPI를 멈춥니다.** 켜 둔 채 받으면 DB를 받은 뒤 서류를 받는 사이에 업로드·판단 저장이 끼어 둘이 다른 시점이 됩니다(승준님 #225). 이 동안 화면은 서버에 닿지 않습니다.

```bash
mkdir -p ~/backup && TS=$(date +%Y%m%d-%H%M) && echo $TS    # TS는 되돌릴 때 쓰니 적어 둔다
$C stop fastapi
$C exec -T mysql mysqldump --defaults-extra-file=/run/secrets/mysql_health_cnf \
  --single-transaction --default-character-set=utf8mb4 closure_agent > ~/backup/db-$TS.sql
# 멈춘 컨테이너에는 exec를 못 쓴다. 같은 볼륨을 붙인 임시 컨테이너로 묶는다
$C run --rm --no-deps -T fastapi tar czf - -C /data/documents . > ~/backup/documents-$TS.tgz

# 제대로 받았는지
tail -n 1 ~/backup/db-$TS.sql              # "-- Dump completed on …"이 나와야 한다
tar tzf ~/backup/documents-$TS.tgz | head
```

`~/backup`은 EC2 디스크 안이라 EC2가 망가지면 같이 잃습니다. 큰 배포 전에는 내 컴퓨터로도 한 부 받아 둡니다.
배포를 여기서 그만두면 `$C start fastapi`로 다시 켭니다.

## 3. 반영

한 줄이라도 실패하면 다음 줄로 넘어가지 않게 `&&`로 잇습니다. SQL이 실패했는데 새 코드가 켜지면 옛 표에 새 코드가 붙습니다(현종님·승준님 #225).

```bash
# 표가 바뀌지 않는 배포(1단계에서 새 00N_*.sql 없음)
git pull && $C up -d --build

# 새 00N_*.sql이 있으면 번호 순서대로 이어서, 전부 성공했을 때만 켠다
git pull && \
  $MYSQL closure_agent < backend/sql/00N_xxx.sql && \
  $C up -d --build
```

중간에 멈추면 FastAPI는 멈춘 채로 남습니다. 원인을 고치고 다시 하거나, 5단계로 되돌립니다.

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

**DB·서류까지 되돌리기** — DB·서류가 백업 시점으로 **통째로** 바뀝니다. 백업 뒤에 사장님이 넣은 내용은 사라집니다.

- FastAPI를 먼저 멈추고, 코드를 백업 시점의 커밋으로 옮깁니다. 표가 바뀐 배포였다면 새 코드가 옛 표를 읽다 깨집니다(다물님 #225)
- 두 백업 파일이 온전한지 **둘 다 먼저** 보고, 하나라도 아니면 아무것도 지우지 않고 멈춥니다
- FastAPI는 DB·서류 복원이 모두 성공한 뒤에만 켭니다. 복원 도중 요청이 들어와 쓰지 않게 하려는 것입니다(승준님 #225)

```bash
TS=<2단계에서 적은 값>
$C stop fastapi
git checkout <1단계에서 적은 커밋>
tail -n 1 ~/backup/db-$TS.sql | grep -q '^-- Dump completed' && \
  tar tzf ~/backup/documents-$TS.tgz > /dev/null && \
  $MYSQL closure_agent < ~/backup/db-$TS.sql && \
  $C run --rm --no-deps -T fastapi sh -c 'find /data/documents -mindepth 1 -delete && tar xzf - -C /data/documents' \
    < ~/backup/documents-$TS.tgz && \
  $C up -d --build
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

끝에 나오는 `case_id`가 `NULL`이면 지운 게 없습니다(번호를 안 넘겼거나, Case가 없는 회원이거나, 판단이 도는 중).
판단 중(`PENDING`)이면 일부러 지우지 않습니다. 뒤에서 돌던 판단이 지워진 기록에 저장하려다 실패하기 때문입니다(#224). 홈에서 판단이 끝난 걸 보고 다시 넣습니다.

### 새 서버에 처음 띄울 때

위 1~5단계는 이미 돌고 있는 서버를 갱신하는 순서입니다. 새 서버는 설정 파일 두 개가 git에 없어서 먼저 만들어야 MySQL이 뜹니다(현종님·승준님 #225). 기존 서버에서 이 파일들을 덮어쓰지 않습니다.

1. `.env.prod`: `.env.prod.example`을 복사해 실제 값을 채웁니다. AI 연결 값은 루트 `.env.example`을 보고 같은 파일에 넣습니다. 값은 문서·PR에 적지 않습니다
2. `mysql_health.cnf`: `docker-compose.prod.yml` 머리말대로 만들고 `chmod 600`. 비밀번호는 `.env.prod`의 `MYSQL_ROOT_PASSWORD`와 같아야 합니다
3. MySQL만 먼저 켜서 준비될 때까지 기다린 뒤 표를 만들고, 그다음 FastAPI를 켭니다. `001`은 이미 표가 있으면 "already exists"로 멈추고 아무것도 지우지 않습니다

```bash
cp .env.prod.example .env.prod        # 그다음 값을 채운다
chmod 600 mysql_health.cnf            # 머리말대로 만든 뒤
$C up -d --wait mysql && \
  $MYSQL closure_agent < backend/sql/001_schema.sql && \
  $C up -d --build fastapi            # 절차 기준 표는 서버가 켜질 때 채운다
```

### 검수 자료 버전을 올렸을 때

절차조회는 Case 근거의 버전이 지금 검수 자료 버전과 같은 것만 고릅니다. 버전을 올리면 기존 Case도 재적재해야 그 Case가 "자료 없음"이 되지 않습니다. #246부터 기존 스크립트가 배포 이미지에 포함돼 있습니다.

백업과 변경 전·후 자료 버전을 확인하고, 대상 Case 목록을 먼저 조회·확정합니다. 아래 명령은 **Case 하나**를 받으므로 확인한 대상마다 실행합니다. 소스를 생략하면 이미지에 포함된 검수 자료를 사용합니다.

```bash
$C exec -T fastapi python -m scripts.import_reviewed_procedures --help
$C exec -T fastapi python -m scripts.import_reviewed_procedures --case-id <확인한_Case_ID>
```

같은 버전을 재실행해도 근거를 중복 추가하지 않고, 과거 판단의 근거는 덮어쓰지 않습니다. 실패하면 다음 대상을 진행하지 말고 해당 Case의 결과를 확인합니다. 실제 이미지·격리 DB 검증과 운영 반영 범위는 #239에서 추적합니다.
