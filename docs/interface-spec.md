# 이전 경로 안내: BE HTTP 계약

> 상태: `[REDIRECT_ONLY][NON_NORMATIVE]`
>
> 기준일: 2026-09-15

이 파일에 있던 HTTP endpoint·응답 DTO 초안은 [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)로 통합했다. **BE가 검토할 문서는 그 파일 하나다.**

이 경로는 `CLAUDE.md`와 `hero-scenario.md`의 기존 링크를 깨뜨리지 않기 위해 남겨 둔다. 여기에 endpoint, JSON 예시, status mapping을 새로 추가하지 않는다.

우선순위는 다음과 같다.

1. 공동 승인 후 생성되는 OpenAPI와 공유 DTO/JSON Schema
2. 실제 FastAPI route와 통합 test
3. 승인 전에는 `be-agent-integration-requirements.md`의 `[PROPOSED_SHARED][NOT_APPROVED]` 제안

현재 FastAPI app·route는 구현돼 있지 않으며, 이 파일 자체는 승인된 API 명세나 구현 근거가 아니다.
