# Legacy 안내 — 이 파일은 DB 스키마 명세가 아닙니다

> **테이블·migration 구현 기준으로 사용하지 마세요.**
>
> 상태: 이전 링크를 유지하기 위한 안내 파일 · 기준일: 2026-09-15

이 파일에 있던 물리 테이블·컬럼 초안은 실제 migration이 없는 추측성 설계였으므로 폐기했습니다. 현재 저장소에는 Agent용 persistence model과 migration이 없습니다.

## 무엇을 봐야 하나요?

- **외부 연동을 위해 함께 검토할 저장 요구사항**: [`../be-agent-integration-requirements.md`](../be-agent-integration-requirements.md)
- **현재 Agent가 읽고 반환하는 내부 schema**: [`../agent-tool-io-schema.md`](../agent-tool-io-schema.md)
- **현재 실행 경계와 목표 생산 흐름**: [`../architecture.md`](../architecture.md)

`be-agent-integration-requirements.md`의 저장 조건도 아직 검토 제안이며 승인되거나 구현되지 않았습니다. `CASES`, version/CAS, progress cardinality, append-only history 등은 함께 검토할 논리 요구사항이며 실제 table, column, constraint 또는 migration이 아닙니다.

## 앞으로의 구현 기준

1. 공동 승인 후 BE가 작성하는 migration과 ORM model
2. DB constraint·transaction을 검증하는 integration test
3. 승인 전 검토 단계에서는 `be-agent-integration-requirements.md`의 logical invariant 제안

이 경로는 `CLAUDE.md`와 `hero-scenario.md`의 기존 링크를 깨뜨리지 않기 위해서만 남겨 둡니다. 테이블명, 컬럼 타입, enum, 관계를 이 파일에 다시 추가하지 않습니다.

`ERD.png`도 폐기된 물리 초안을 표현한 **이전 참고 이미지**입니다. 현재 구현 기준으로 사용하면 안 됩니다.

## 기존 참조 호환 안내

`CLAUDE.md`와 `hero-scenario.md`가 이 경로를 가리키더라도, 이 파일 자체를 물리 DB 명세로 해석하면 안 됩니다. DB 변경 전에는 먼저 [`be-agent-integration-requirements.md`의 persistence 논리 요구사항](../be-agent-integration-requirements.md#7-persistence-논리-요구사항)을 공동 검토하고, 승인된 migration·ORM model·integration test를 새 구현 기준으로 만들어야 합니다.
