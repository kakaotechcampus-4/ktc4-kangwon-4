# 폐업 절차 지식을 어디서 읽는가

> 소유: AI · 기준일: 2026-09-19
>
> 이 문서의 책임: 절차 정보의 출처, 갱신 방법, DB로 옮길 때 바꿀 곳.

## 1. 먼저 보는 결론

- **사용자 요청 경로는 인터넷을 쓰지 않습니다.** 미리 받아 팀이 검수한 스냅샷에서만 읽습니다.
- 공식 사이트를 받아오는 코드는 **그대로 있습니다.** 다만 별도 갱신 명령에서만 돕니다.
- 검수되지 않은 자료는 `UNKNOWN`으로 나갑니다. 그러면 정보분석이 단정하지 못하고 Review가 막습니다.
- 지금 저장소는 **JSON 파일**입니다. DB가 준비되면 **읽는 통로 구현만** 바꾸면 됩니다.

## 2. 왜 이렇게 바꿨나

전에는 요청이 들어올 때마다 공식 사이트 3곳을 직접 받아왔습니다. 멘토 리뷰(PR #14)에서:

> 사용자 요청이 들어왔을 때 마다 공식 문서를 fetch하는 구조는 오히려 신뢰도가 떨어질 수 있습니다.
> 공식 문서 서버가 다운되었다거나, 잦은 요청으로 본 서비스가 차단 당했을 경우 공식문서 접근이
> 불가하고, 적절한 절차를 안내할 수 없게 될 수도 있습니다. (…) MVP 때는 미리 저장된 절차만을
> 서비스하고 시간이 남으면 crawler를 구현하는 것도 좋은 생각인 것 같습니다.

지식원이 하나여야 한다는 점도 같이 짚어주셨습니다. 지금은 **요청 시점의 지식원이 하나**입니다 —
검수 스냅샷. 갱신 경로는 그 스냅샷을 만드는 절차이지, 판단에 쓰이는 두 번째 출처가 아닙니다.

## 3. 요청 경로

```
Graph → StoredProcedureLookupTool → 검수 스냅샷(메모리)
                                    └ 네트워크 호출 없음, 디스크 읽기 없음
```

스냅샷은 프로세스가 뜰 때 한 번 읽어 메모리에 둡니다. 요청 중에는 조회만 합니다.
실측에서 절차조회가 **1밀리초**입니다([`runtime-limits.md`](./runtime-limits.md) §2).

조회어와 문서를 맞추는 규칙은 기존 공식 URL registry와 **같습니다.**
그래서 출처를 인터넷에서 스냅샷으로 옮겨도 어떤 조회어가 어떤 문서를 찾는지는 바뀌지 않습니다.

맞는 문서가 없으면 **`NO_RESULTS`로 끝냅니다.** 비슷한 걸 내놓지 않습니다.

## 4. 검수 상태가 곧 신뢰도

레코드 하나에 `reviewed_by`와 `reviewed_at`이 있습니다. 이 두 칸이 최신성을 정합니다.

| 상태 | 최신성 | 결과 |
|---|---|---|
| 검수 안 됨 (`reviewed_by`가 비어 있음) | `UNKNOWN` | 정보분석이 `UNDETERMINED`로만 판단. Review가 단정을 막음 |
| 검수됨, 유효기간 안 | `CURRENT` | 정상 사용 |
| 검수됨, 유효기간 지남 | `STALE` | 경고와 함께 나가고 확정형 판단에 못 씀 |

**사람이 읽지 않은 자료는 `CURRENT`가 될 수 없습니다.** 갱신 명령이 만든 초안은 전부
검수 안 된 상태로 나옵니다. 자동으로 받아온 내용이 저절로 신뢰도를 얻는 일은 없습니다.

`review_valid_days`는 기본 90일입니다. 지나면 자동으로 `STALE`이 됩니다.

## 5. 갱신하는 법

**요청 경로가 아닙니다.** 사람이 직접 돌립니다.

```bash
PYTHONPATH=backend backend/.venv/bin/python \
  -m app.agent.procedure_tool.refresh --out /tmp/reviewed-procedures.draft.json
```

공식 출처에서 받아 초안을 만듭니다. 그 다음이 **사람이 하는 일**입니다.

1. 레코드마다 `excerpt`를 읽습니다. 그 페이지에서 **실제 절차 본문**이 담겼는지 봅니다
2. 아니면 발췌를 고칩니다 — 받아온 본문 안의 다른 구간으로 바꿉니다.
   본문에 없는 문장을 새로 쓰면 안 됩니다
3. 맞으면 `reviewed_by`와 `reviewed_at`을 채웁니다
4. `backend/app/agent/procedure_tool/data/reviewed-procedures.ko-KR.json`에 반영합니다

### 현재 스냅샷 상태 (2026-09-19)

공식 출처 3곳에서 받았고 **아직 아무도 검수하지 않았습니다.** 전부 `UNKNOWN`입니다.
확인해 보니 **2건은 그대로 쓰면 안 됩니다.**

| 레코드 | 출처 | 상태 |
|---|---|---|
| `TAX_BUSINESS_CLOSURE` | 찾기쉬운 생활법령 | 본문은 맞습니다(부가가치세법 제8조 폐업신고). 다만 페이지 제목이 "인터넷쇼핑몰 창업자 >" 하위라 카페 사용자에게 보여줄 제목으로는 어색합니다 |
| `FOOD_SERVICE_CLOSURE` | 찾기쉬운 생활법령 (커피전문점 폐업 신고) | **발췌가 절차 본문이 아니라 좌측 메뉴 목록입니다.** 발췌를 고쳐야 합니다 |
| `WORKPLACE_INSURANCE_CLOSURE` | 국민연금공단 | 내용은 관련 있지만 문장 중간부터 시작합니다 |

발췌를 고르는 코드가 질의어 밀도로 구간을 잡는데, 메뉴가 많은 페이지에서 메뉴를 고르는
경우가 있습니다. 검수 단계에서 걸러집니다. 코드 쪽 개선은
[`open-decisions.md`](./open-decisions.md)에 남깁니다.

## 6. DB로 옮길 때 바꿀 곳

읽는 통로가 한 겹 분리돼 있습니다.

```
StoredProcedureLookupTool
    └ ReviewedProcedureStore (통로)
         ├ JsonFileProcedureStore   ← 지금
         └ (DB 구현)                 ← 나중
```

DB 구현 하나만 추가하면 됩니다. `ReviewedProcedureStore`가 요구하는 건 두 가지뿐입니다 —
스냅샷 버전과 레코드 목록. **그 위의 코드는 아무것도 바뀌지 않습니다.**

접속 주소가 MySQL이든 SQLite든 이 통로 위 코드는 같습니다. 중요한 건 엔진이 아니라
**테이블이 한 벌이어야 한다**는 점입니다.

선행 조건은 [`be-requests.md`](./be-requests.md) 1·2·6번입니다. 특히 2번 —
절차 원문의 출처(URL·발췌·해시·수집시각)를 담을 자리가 지금 DB에 없습니다.
그게 없으면 DB에서 절차를 읽어도 근거를 못 붙여서 "확인 필요"로만 답하게 됩니다.

## 7. 저장소 근거

- 통로와 레코드 정의: `backend/app/agent/procedure_tool/store.py`
- JSON 구현: `backend/app/agent/procedure_tool/json_store.py`
- 요청 경로 조회: `backend/app/agent/procedure_tool/stored_tool.py`
- 갱신 명령: `backend/app/agent/procedure_tool/refresh.py`
- 공식 출처 registry와 직접 조회(갱신 전용): `backend/app/agent/procedure_tool/tool.py`
- 테스트: `backend/tests/agent/test_procedure_store.py`
