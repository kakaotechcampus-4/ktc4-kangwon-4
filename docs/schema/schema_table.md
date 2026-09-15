# 이전 경로 안내: BE 저장 계약

> 상태: `[REDIRECT_ONLY][NON_NORMATIVE]`
>
> 기준일: 2026-09-15

이 파일의 물리 테이블·컬럼 초안은 실제 migration이 없는 추측성 설계였으므로 폐기했다. BE가 검토할 logical persistence 요구사항은 [`../be-agent-integration-requirements.md`](../be-agent-integration-requirements.md) 한 곳으로 통합했다.

이 경로는 `CLAUDE.md`와 `hero-scenario.md`의 기존 링크를 깨뜨리지 않기 위해 남겨 둔다. 여기에 테이블명, 컬럼 타입, enum, 관계를 새로 추가하지 않는다.

우선순위는 다음과 같다.

1. 공동 승인 후 BE가 작성하는 migration과 ORM model
2. DB constraint·transaction을 확인하는 통합 test
3. 승인 전에는 `be-agent-integration-requirements.md`의 `[PROPOSED_SHARED][NOT_APPROVED]` logical invariant

현재 저장소에는 Agent용 persistence model과 migration이 없다. `ERD.png`도 기존 물리 초안을 표현한 **legacy·non-normative 참고 자산**으로, 구현 기준으로 사용하면 안 된다.
