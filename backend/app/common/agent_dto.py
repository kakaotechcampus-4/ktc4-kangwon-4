"""BE ↔ AI 입출력 DTO. 기존 모델과 검증 규칙을 그대로 공개한다.

BE는 이 모듈에서 import하며, 필드 이름은 snake_case를 사용한다.
필드 정의와 검증은 app.agent.schemas 한 곳에서 관리한다.

요청 — AgentGraphInput
    trigger: CaseCreatedTrigger / ResultSubmittedTrigger / ConflictConfirmedTrigger.
    case_snapshot: BE가 접근 권한을 확인한 Case의 현재 값·진행 상태·근거.
    trace_id: 호출 추적용 식별자. 없으면 None.
    미확인 사실은 status="UNKNOWN", value=None, evidence_refs=[]로 보낸다.
    충돌 확인 후보는 클라이언트 입력이 아닌 BE가 보관한 원본을 사용한다.

응답 — AgentGraphOutput (outcome_type으로 구분)
    REVIEWED_PLAN: review_subject.supervisor_draft의 decision과 mutations,
        review_proof를 함께 반환한다. mutations는 아직 저장하지 않은 후보다.
        decision_type=NEEDS_MORE_INFO이면 next_action=None과 확인 질문이 온다.
        ACTION에서 막는 조건이 없으면 blocker=None과 Next Action 1개 반환.
        이때 새 BLOCKER 행 미생성, 해당 CASE_HISTORY.priority_blocker_id=NULL 처리.
        전체 Case 완료나 기존 BLOCKER의 RESOLVED 자동 전이를 의미하지 않음.
        BE는 저장 직전 outcome.assert_integrity()와 현재 Case 상태를 재확인한다.
    CONFLICT: conflicts와 evidence_records를 보관하고 사용자 확인을 받는다.
        확인 전에는 Case를 변경하지 않는다.
    SAFE_FAILURE: failure_code / retryable / recovery_action_code를 처리한다.
        검수되지 않은 판단이나 변경 후보는 반환하지 않는다.

호출 예 (권한·입력 정제·근거 준비를 마친 BE 코드에서):
    request = AgentGraphInput.model_validate(payload)
    outcome: AgentGraphOutput = await runtime.run_planning(request)

DB 칸에 맞추기
    Agent가 만드는 값은 BE가 그대로 DB에 넣으므로, 칸의 길이·형식은 schemas.py의
    타입에 박혀 있다. 넘치는 값은 MySQL이 자르기 전에 Agent에서 먼저 막힌다.
    EVIDENCE.content_hash는 VARCHAR(64)라 "sha256:" 접두사 없이 64자 hex만 담는다.
    restoration_status / restoration_scope / demolition_required의 UNKNOWN은
    Agent에서 status="UNKNOWN", value=None으로 표현한다. BE는 저장할 때 "UNKNOWN"
    문자열로 바꾸고, snapshot을 만들 때 다시 status="UNKNOWN", value=None으로 되돌린다.

JSON 응답을 다시 읽을 때는 Pydantic TypeAdapter(AgentGraphOutput)을 쓴다.
이 DTO는 내부 Python 호출용이며 FE HTTP 응답이나 DB 저장 완료를 뜻하지 않는다.
"""

from app.agent.schemas import (
    AgentGraphInput,
    AgentGraphOutput,
    CaseCreatedTrigger,
    CaseFact,
    CaseSnapshot,
    ConflictCandidate,
    ConflictConfirmedTrigger,
    ConflictOutcome,
    EvidenceRecord,
    ProcedureProgress,
    RedactedInput,
    Redaction,
    ResultSubmittedTrigger,
    ReviewedPlanOutcome,
    SafeFailureOutcome,
)

__all__ = [
    "AgentGraphInput",
    "AgentGraphOutput",
    "CaseCreatedTrigger",
    "CaseFact",
    "CaseSnapshot",
    "ConflictCandidate",
    "ConflictConfirmedTrigger",
    "ConflictOutcome",
    "EvidenceRecord",
    "ProcedureProgress",
    "RedactedInput",
    "Redaction",
    "ResultSubmittedTrigger",
    "ReviewedPlanOutcome",
    "SafeFailureOutcome",
]
