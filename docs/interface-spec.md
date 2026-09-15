# Legacy 안내 — 이 파일은 API 명세가 아닙니다

> **구현 기준으로 사용하지 마세요.**
>
> 상태: 이전 링크를 유지하기 위한 안내 파일 · 기준일: 2026-09-15

이 파일에 있던 HTTP endpoint와 응답 DTO 초안은 한 문서로 통합했습니다. 현재 FastAPI app과 route는 구현돼 있지 않으며, 이 파일은 승인된 API 계약이나 구현 근거가 아닙니다.

## 무엇을 봐야 하나요?

- **외부 연동을 위해 함께 검토할 요청사항**: [`be-agent-integration-requirements.md`](./be-agent-integration-requirements.md)
- **현재 Agent·Tool 공개 호출 입·출력**: [`agent-tool-io-schema.md`](./agent-tool-io-schema.md)
- **현재 호출 구조와 책임**: [`architecture.md`](./architecture.md)

`be-agent-integration-requirements.md`의 HTTP와 DTO도 아직 검토 제안이며 승인되거나 구현된 계약이 아닙니다. 공동 승인 전에는 endpoint, payload와 HTTP status를 확정된 계약처럼 구현하면 안 됩니다.

## 앞으로의 구현 기준

1. 공동 승인 후 생성되는 OpenAPI와 공유 DTO/JSON Schema
2. 실제 FastAPI route와 contract/integration test
3. 승인 전 검토 단계에서는 `be-agent-integration-requirements.md`의 제안

이 경로는 `CLAUDE.md`와 `hero-scenario.md`의 기존 링크를 깨뜨리지 않기 위해서만 남겨 둡니다. endpoint, JSON 예시, status mapping을 이 파일에 다시 추가하지 않습니다.

## 5. 이전 참조 호환 안내

기존 코드 주석의 `interface-spec.md §5`는 삭제된 API 초안을 가리킵니다. 다음 항목은 아직 확정되지 않았으며, 구현 전에 [`be-agent-integration-requirements.md`의 P0 결정](./be-agent-integration-requirements.md#4-구현-전에-닫아야-할-p0-결정)에서 함께 정해야 합니다.

- `expectedVersion`을 포함한 Case 동시성 보호와 충돌 응답
- 사용자 입력 원문을 응답에 다시 포함할지 여부
- 확인된 변경을 제출하는 endpoint와 request DTO
- `UPDATED`, `NO_CHANGE`, `NEEDS_MORE_INFO`, `CONFLICT` 등 외부 outcome mapping

이 절은 기존 참조를 찾기 위한 호환 안내일 뿐이며 API 계약이 아닙니다.
