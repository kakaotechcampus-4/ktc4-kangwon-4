from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlmodel import Field, Relationship

from app.be.models.mixins import CreatedAtMixin


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
    excerpt: str | None = Field(default=None, sa_column=Column(Text, nullable=True), description="발췌 내용")
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

    canonical_field: str = Field(max_length=100, description="충돌이 발생한 필드")
    committed_value: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True), description="기존 값"
    )
    proposed_value: str = Field(max_length=1000, description="새로 제안된 값")
    conflict_digest: str | None = Field(default=None, max_length=255, description="충돌 내용 다이제스트")
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False), description="만료 시각")
    used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True), description="사용(1회) 시각"
    )

    case: "Case" = Relationship(back_populates="conflict_references")


class DecisionRecord(CreatedAtMixin, table=True):
    __tablename__ = "decision_record"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(BigInteger, ForeignKey("case.id"), nullable=False), description="대상 케이스")

    run_id: str = Field(max_length=100, description="실행 단위 ID")
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
