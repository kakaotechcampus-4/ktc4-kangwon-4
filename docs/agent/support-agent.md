# 지원금(Support) Agent

> **현재 상태: 만들었지만 연결하지 않음.**
> 코드와 테스트는 남아 있지만, 지금 서비스의 판단 경로(절차조회 → 정보분석 → Supervisor → Review)에서는 이 Agent를 부르지 않습니다.
> 2026-10-07 [#69](https://github.com/kakaotechcampus-4/ktc4-kangwon-4/pull/69)에서 판단 경로를 폐업 절차 중심으로 좁히면서 뺐습니다.
>
> **왜 뺐나.** 이유는 두 가지입니다.
>
> 1. **지원사업을 찾아 주는 곳은 이미 있습니다.** 정부24의 보조금24, 기업마당, 소상공인24가 내게 맞는 지원사업을 찾아 줍니다. 사장님에게 남는 어려움은 찾은 다음입니다. 순서를 지키고 서류를 빠짐없이 갖춰서 실제로 받아 내는 일입니다. 리본은 "찾아 주기"가 아니라 **"놓치지 않고 받게 돕기"** 에 집중했습니다.
> 2. **자격 판단은 틀리면 사장님이 돈을 잃습니다.** 팀 원칙상 AI는 지원 자격을 혼자 판단하지 않고, 정책 자료는 사람이 공고를 검수해서 넣습니다. 서비스에 넣을 만큼 검수를 마친 지원사업 목록이 아직 없으므로, 연결하면 근거 없이 비교하게 됩니다.
>
> **대신 리본이 하는 일: 신청한 지원금을 놓치지 않게 돕기.** 점포철거비를 대표 사례로 다룹니다.
> - **순서 때문에 생기는 실수를 미리 막습니다.** 철거 전 사진처럼 철거한 뒤에는 다시 만들 수 없는 증빙과, 공고가 요구하는 전자세금계산서·계좌이체 내역을, 철거를 권하는 시점에 공고 근거와 함께 안내합니다.
> - 로드맵의 "점포철거비 조건 확인" 할 일로 공고 원문을 직접 확인하게 합니다.
> - "1차 적격심사 결과 확인"은 기관에서 받은 결과를 사장님이 기록합니다(`PUT /cases/support-approval`). AI가 자격을 대신 판단하지 않습니다.
> - 제출 전에 서류 Tool이 정산 서류의 누락과 서류끼리의 금액 불일치를 찾습니다. 문제가 있으면 제출용 ZIP을 만들지 않고 무엇을 고칠지 알려 줍니다.
>
> **다시 연결할 조건.** 검수한 지원사업 자료가 갖춰지고, 찾고 비교하고 다시 찾는 반복이 필요해지면 별도 Agent로 연결할지 다시 정합니다.
> 이 Agent를 따로 평가한 결과는 서비스 실적에 넣지 않습니다([모니터링 기록](./monitoring-results.md)). 아래 내용은 다시 연결할 때를 위한 설명입니다.

Case의 확인된 사실과 검수된 지원사업 조건을 비교한다. 자격·지급액을 확정하지 않고,
조회 자체로 신청 이력(`SUPPORT_ITEM_APPLICATION`)을 만들지 않는다.

## 입력 → 출력

`DiscoverSupportInput`(현재 유일한 입력 형태) → `SupportAnalysisResult`(`support_checks` 목록).
카탈로그(`ReviewedSupportCatalog`)는 호출자가 주입한다 — MVP는 소량 전체를 비교한다
(절차별로 미리 걸러내지 않는다).

## 조건의 유일한 원천은 검수 Wiki

`SUPPORT_ITEM.uuid`에 연결된 검수 Wiki가 조건의 원천이다. `catalog`는 그 Wiki의 사본이지
독립 원천이 아니다. `support_wiki`(선택 주입)로 정확한 ID·UUID를 조회하면 그 결과가
우선한다 — 조회 실패는 `PARTIAL`/`NO_CANDIDATE`로 남기고 catalog 규칙으로 대체하지 않는다.

## `match_status` (schema_table.md의 `SUPPORT_MATCH.match_status`와 동일)

`POSSIBLY_RELEVANT` / `NEEDS_CONFIRMATION` / `NOT_RELEVANT` / `STALE` / `UNVERIFIABLE`.
`freshness_status=STALE`인 조건은 `match_status`도 반드시 `STALE`이어야 한다(그 반대로 우회 못 함).

## 비교 규칙

- 확인된 값만 충족/불충족 비교에 쓴다. 모르는 값은 추가 확인으로 남긴다
- 대소 비교는 숫자·날짜에만 허용한다. 업종 문자열을 임의 코드로 치환하지 않는다
- 원문에 없는 사업명·조건·금액·기한을 만들지 않는다

코드: [`support_agent/agent.py`](../../backend/app/agent/support_agent/agent.py)
(Wiki 조회는 `_resolve_wiki`), 자료 타입: [`support_agent/models.py`](../../backend/app/agent/support_agent/models.py),
프롬프트: [`prompts.py`](../../backend/app/agent/prompts.py)의 `support_messages`.
