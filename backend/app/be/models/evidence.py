from datetime import datetime

from sqlalchemy import JSON, BigInteger, Column, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlmodel import Field, Relationship

from app.be.models.mixins import CreatedAtMixin


class OfficialDocument(CreatedAtMixin, table=True):
    """공식 자료 본문. 문서 한 건의 한 버전마다 한 줄이고, 한 번 적으면 고치지 않는다.

    전에는 이 본문을 Case마다 evidence에 복사했다. 사장님이 늘수록 같은 국세청 안내문이
    그만큼 쌓였고, 문서를 고치려면 Case 수만큼 다시 써야 했다. 그 수단이 Case를 하나씩
    지정하는 수동 스크립트(scripts/import_reviewed_procedures.py)라, 빠뜨려도 에러가 아니라
    조용히 "자료 없음"이 됐다.

    버전을 올릴 때는 이 줄을 고치는 것이 아니라 새 줄을 넣는다. 그래야 예전 Case가 예전
    줄을 계속 가리켜서, 그 Case가 무엇을 보고 판단했는지가 나중에도 그대로 남는다.

    다만 이것이 재적재를 없애지는 않는다. 절차조회는 Case 근거의 source_version이 지금
    검수 목록 버전과 같은 것만 고르므로(stored_tool.py:73), 목록 버전이 올라가면 예전
    Case는 자료를 못 찾는다. 예전 Case를 새 버전으로 옮기려면 여전히 다시 적재해야 한다
    (scripts/import_reviewed_procedures.py). 이 표가 없애는 것은 본문 복제뿐이다.
    """

    __tablename__ = "official_document"
    __table_args__ = (
        # 같은 문서의 같은 버전을 두 번 적재하지 않는다. 두 줄이 되면 Case마다 다른 줄을
        # 가리키게 되어, 본문을 한곳에 둔 뜻이 사라진다.
        UniqueConstraint("source_ref", "source_version", name="uq_official_document_source_version"),
    )

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    source_ref: str = Field(max_length=500, description="출처 참조(원문 URL)")
    source_version: str = Field(max_length=100, description="출처 버전")
    excerpt: str = Field(sa_column=Column(Text, nullable=False), description="본문")
    content_hash: str = Field(max_length=64, description="본문 해시. Case 쪽 값과 대조한다")
    published_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True), description="원본 게시 시각"
    )
    retrieved_at: datetime = Field(sa_column=Column(DateTime, nullable=False), description="수집 시각")


class Evidence(CreatedAtMixin, table=True):
    __tablename__ = "evidence"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    evidence_id: str = Field(
        max_length=100, unique=True, description="opaque 근거 ID — id와 별개의 비즈니스 키"
    )
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False), description="소유 케이스")

    source_type: str = Field(
        sa_column=Column(
            Enum(
                "USER_INPUT",
                "EXPERT_CONFIRMATION",
                "REVIEWED_WIKI",
                "OFFICIAL_DOCUMENT",
                "OFFICIAL_API",
                "CALCULATION_RESULT",
                "SYSTEM_RECORD",
                name="evidence_source_type_enum",
            ),
            nullable=False,
        )
    )
    source_ref: str = Field(max_length=500, description="출처 참조")
    source_version: str | None = Field(default=None, max_length=100, description="출처 버전")
    locator: str | None = Field(default=None, max_length=255, description="출처 내 위치")
    # 사장님이 쓴 글은 Case마다 진짜로 다르므로 여기에 그대로 둔다.
    # 공식 자료는 본문을 official_document 한 줄에 두고 아래 official_document_id로 가리킨다.
    excerpt: str | None = Field(default=None, sa_column=Column(Text, nullable=True), description="발췌 내용")
    official_document_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey("official_document.id"), nullable=True),
        description="공식 자료일 때 본문이 있는 줄. 이 값이 있으면 excerpt는 비어 있다",
    )
    published_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True), description="원본 게시 시각"
    )
    retrieved_at: datetime = Field(sa_column=Column(DateTime, nullable=False), description="수집 시각")
    freshness_status: str = Field(
        sa_column=Column(Enum("CURRENT", "STALE", "UNKNOWN", name="freshness_status_enum"), nullable=False)
    )
    content_hash: str | None = Field(default=None, max_length=64, description="내용 해시")

    case: "Case" = Relationship(back_populates="evidence_records")


class EvidenceLineage(CreatedAtMixin, table=True):
    """EVIDENCE 간 파생 관계 (N:M 접합 테이블).

    다른 모든 테이블과 동일하게 surrogate id를 PK로 쓰고, "중복 파생 관계 방지"는
    UniqueConstraint로 강제한다 (나중에 이 관계에 컬럼이 추가되거나 다른 테이블/API가
    특정 lineage 행을 참조해야 할 때 복합 PK → surrogate PK 마이그레이션 비용을 피하기 위함).

    두 컬럼 모두 EVIDENCE.id를 참조하는 자기참조 패턴이라, StepDependency와 동일하게
    Relationship()은 걸지 않는다 (양쪽 FK를 구분해서 자동 매핑할 명확한 기준이 없음).
    """

    __tablename__ = "evidence_lineage"
    __table_args__ = (
        UniqueConstraint("evidence_id", "parent_evidence_id", name="uk_evidence_lineage"),
    )

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    evidence_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("evidence.id"), nullable=False),
        description="파생된 근거(child) — EVIDENCE.id 참조 (evidence.evidence_id 아님)",
    )
    parent_evidence_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("evidence.id"), nullable=False),
        description="원본 근거(parent) — EVIDENCE.id 참조",
    )


class ConflictReference(CreatedAtMixin, table=True):
    __tablename__ = "conflict_reference"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    conflict_ref: str = Field(
        max_length=100, unique=True, description="opaque 참조값 — id와 별개의 비즈니스 키"
    )
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False), description="대상 케이스")
    case_history_id: int = Field(
        sa_column=Column(BigInteger, ForeignKey("case_history.id"), nullable=False),
        description="이 충돌을 일으킨 제출(raw_input)의 이력 — /confirm이 '이번에 하신 말씀'을 보여줄 때 씀",
    )

    canonical_field: str = Field(max_length=100, description="충돌이 발생한 필드")
    committed_value: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True), description="기존 값"
    )
    proposed_value: str = Field(max_length=1000, description="새로 제안된 값")
    conflict_digest: str | None = Field(default=None, max_length=255, description="충돌 내용 다이제스트")
    candidate_payload: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description=(
            "AI가 보낸 충돌 후보 원본(ConflictCandidate) 전체. 사용자가 고른 뒤 그대로 돌려줘야 "
            "AI가 내용 다이제스트를 대조해 받아준다. 위 칸들은 화면에 보여주려고 글자로 바꾼 "
            "값이라 숫자·참거짓·빈 값을 되돌릴 수 없다"
        ),
    )
    status: str = Field(
        default="PENDING",
        sa_column=Column(
            # REJECTED는 연결 이력이 FAILED면 시스템 미채택, 검수 통과(DONE/NEEDS_MORE_INFO,
            # 절차 안내 종료도 DONE)면 사용자가 기존 값 유지를 고른 것이다.
            Enum("PENDING", "CONFIRMED", "REJECTED", name="conflict_reference_status_enum"), nullable=False
        ),
        description="PENDING=아직 결정 안 됨, CONFIRMED=새 값 채택, REJECTED=기존 값 유지",
    )
    decided_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True), description="결정된 시각. 결정 전엔 NULL"
    )
    resolved_by_case_history_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("case_history.id", use_alter=True, name="fk_conflict_reference_resolved_by"),
            nullable=True,
        ),
        description=(
            "이 충돌을 닫은 결정 이력. 위 case_history_id(충돌을 일으킨 제출)와 짝이다."
            " 결정 이력에는 글이 없어 과거 고정 표식의 출처를 확인할 때 이 칸으로 제출을"
            " 추적한다(services.unmasking). 화면 원문 복원은 하지 않는다. 결정 전이거나 이 칸이"
            " 생기기 전에 닫힌 충돌은 NULL"
        ),
    )

    case: "Case" = Relationship(back_populates="conflict_references")
    # case_history로 가는 외래키가 둘이라(충돌을 일으킨 제출, 그 충돌을 닫은 결정) 어느 쪽을
    # 따라갈지 적어 준다. 이 관계는 "이번에 하신 말씀"을 보여줄 때 쓰는 제출 쪽이다.
    case_history: "CaseHistory" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "ConflictReference.case_history_id"}
    )


class DecisionRecord(CreatedAtMixin, table=True):
    __tablename__ = "decision_record"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False), description="대상 케이스")
    case_history_id: int = Field(
        sa_column=Column(
            BigInteger, ForeignKey("case_history.id"), nullable=False, comment="이 판단을 일으킨 입력 이력"
        )
    )

    run_id: str = Field(max_length=100, description="실행 단위 ID")
    snapshot_id: str = Field(max_length=36, description="판단에 사용한 Case 상태 스냅샷 ID(UUID)")
    trace_id: str | None = Field(default=None, max_length=100, description="추적 ID")
    review_subject_id: str = Field(max_length=100, description="리뷰 대상 ID")
    review_attempt: int = Field(default=1, description="리뷰 시도 횟수")
    subject_digest: str | None = Field(default=None, max_length=255, description="리뷰 대상 다이제스트")
    verdict: str = Field(max_length=50, description="판정 결과 (ENUM 아님, 현재는 PASS만 규정)")
    decision_type: str = Field(
        max_length=50, description="ACTION(블로커+다음액션) / NEEDS_MORE_INFO(추가 질문) — ENUM 아님"
    )
    summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True), description="판단 요약")
    human_confirmation_required: bool = Field(default=False, description="사람 확인 필요 여부")
    reviewed_at: datetime = Field(sa_column=Column(DateTime, nullable=False), description="리뷰 완료 시각")

    case: "Case" = Relationship(back_populates="decision_records")
