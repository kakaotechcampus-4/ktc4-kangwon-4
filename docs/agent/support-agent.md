# 지원금(Support) Agent

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
