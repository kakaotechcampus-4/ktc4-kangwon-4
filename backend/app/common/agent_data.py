"""Adapters and a bundled-file loader for the Agent's reviewed input contracts.

This module never opens a database session. Importers use the caller's session
and leave commit/rollback to the caller. Adapters do not fill missing review
data, Evidence, versions, or timestamps.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from sqlmodel import Session

from app.agent.action_catalog import ProcedureBindings, resolve_procedure_bindings
from app.agent.procedure_tool.store import (
    ProcedureStoreError,
    ReviewedProcedureRecord,
    ReviewedProcedureSnapshot,
    ReviewedProcedureStore,
)
from app.agent.schemas import (
    KnownProcedureStep,
    ProcedureDependency,
    ProcedureEligibility,
    ProcedureStepRef,
    validate_procedure_registry,
)
from app.agent.support_agent.models import ReviewedSupportCatalog
from app.be.crud import case as case_crud
from app.be.crud import evidence as evidence_crud
from app.be.models.evidence import Evidence
from app.be.models.mixins import KST
from app.be.models.procedure_step import (
    ProcedureStep,
    StepDependency,
    StepEligibility,
)
from app.be.models.support_item import SupportItem

__all__ = [
    "InMemoryReviewedProcedureStore",
    "build_known_procedure_steps",
    "build_reviewed_procedure_store",
    "build_reviewed_support_catalog",
    "import_reviewed_procedures",
    "load_reviewed_procedure_store",
    "load_reviewed_procedures",
    "load_reviewed_support_catalog",
]


@dataclass(frozen=True, slots=True)
class InMemoryReviewedProcedureStore:
    """Immutable-by-copy implementation of ``ReviewedProcedureStore``."""

    _snapshot_version: str
    _records: tuple[ReviewedProcedureRecord, ...]

    @classmethod
    def from_snapshot(
        cls, snapshot: ReviewedProcedureSnapshot
    ) -> InMemoryReviewedProcedureStore:
        # Re-parse model instances too.  Pydantic may otherwise return the same
        # instance and skip nested validation after an external mutation.
        validated = ReviewedProcedureSnapshot.model_validate(
            snapshot.model_dump(mode="python")
        )
        return cls(
            _snapshot_version=validated.snapshot_version,
            _records=tuple(validated.records),
        )

    @property
    def snapshot_version(self) -> str:
        return self._snapshot_version

    def records(self) -> Sequence[ReviewedProcedureRecord]:
        # ReviewedProcedureRecord is assignment-validating but not frozen.  Do
        # not expose the store's canonical copies to request-path consumers.
        return tuple(record.model_copy(deep=True) for record in self._records)


def build_known_procedure_steps(
    procedure_steps: Sequence[ProcedureStep],
    dependencies: Sequence[StepDependency],
    eligibility_conditions: Sequence[StepEligibility],
    *,
    db_timezone: tzinfo,
) -> list[KnownProcedureStep]:
    """Map one complete procedure-registry read into the Agent DTO.

    ``db_timezone`` is mandatory because the current SQLModel columns return
    naive datetimes.  The caller must state which timezone those values use;
    this adapter will not guess UTC or the host timezone.
    """

    if not isinstance(db_timezone, tzinfo):
        raise TypeError("db_timezone must be an explicit datetime.tzinfo")

    steps_by_id: dict[int, ProcedureStep] = {}
    for step in procedure_steps:
        step_id = _persisted_id(step.id, "procedure_step.id")
        if step_id in steps_by_id:
            raise ValueError(f"duplicate procedure_step.id: {step_id}")
        steps_by_id[step_id] = step
    for step_id, step in steps_by_id.items():
        if step.replaced_by_procedure_step_id is not None:
            _known_step_id(
                step.replaced_by_procedure_step_id,
                steps_by_id,
                f"procedure_step[{step_id}].replaced_by_procedure_step_id",
            )

    dependencies_by_step: defaultdict[int, list[ProcedureDependency]] = defaultdict(
        list
    )
    dependency_keys: set[tuple[int, int, str]] = set()
    for dependency in dependencies:
        step_id = _known_step_id(
            dependency.procedure_step_id,
            steps_by_id,
            "step_dependency.procedure_step_id",
        )
        prerequisite_id = _known_step_id(
            dependency.prerequisite_procedure_step_id,
            steps_by_id,
            "step_dependency.prerequisite_procedure_step_id",
        )
        key = (step_id, prerequisite_id, dependency.dependency_type)
        if key in dependency_keys:
            raise ValueError(f"duplicate step dependency: {key}")
        dependency_keys.add(key)
        dependencies_by_step[step_id].append(
            ProcedureDependency(
                prerequisite_procedure_step_id=prerequisite_id,
                dependency_type=dependency.dependency_type,
            )
        )

    eligibility_by_step: defaultdict[int, list[ProcedureEligibility]] = defaultdict(
        list
    )
    eligibility_keys: set[tuple[int, str, str]] = set()
    for condition in eligibility_conditions:
        step_id = _known_step_id(
            condition.procedure_step_id,
            steps_by_id,
            "step_eligibility.procedure_step_id",
        )
        key = (step_id, condition.condition_key, condition.condition_value)
        if key in eligibility_keys:
            raise ValueError(f"duplicate step eligibility: {key}")
        eligibility_keys.add(key)
        eligibility_by_step[step_id].append(
            ProcedureEligibility(
                condition_key=condition.condition_key,
                condition_value=condition.condition_value,
            )
        )

    known_steps: list[KnownProcedureStep] = []
    for step_id in sorted(steps_by_id):
        step = steps_by_id[step_id]
        aliases = step.utterance_aliases
        if aliases is not None and not isinstance(aliases, list):
            raise ValueError(
                f"procedure_step {step_id} utterance_aliases must be a JSON list"
            )
        known_steps.append(
            KnownProcedureStep(
                procedure_step=ProcedureStepRef(
                    procedure_step_id=step_id,
                    step_code=step.step_code,
                ),
                step_name=step.step_name,
                utterance_aliases=[] if aliases is None else list(aliases),
                registry_version=step.registry_version,
                applicable_business_type=step.applicable_business_type,
                deprecated_at=_attach_db_timezone(
                    step.deprecated_at,
                    db_timezone=db_timezone,
                    field_name=f"procedure_step[{step_id}].deprecated_at",
                ),
                dependencies=sorted(
                    dependencies_by_step[step_id],
                    key=lambda item: (
                        item.prerequisite_procedure_step_id,
                        item.dependency_type,
                    ),
                ),
                eligibility_conditions=sorted(
                    eligibility_by_step[step_id],
                    key=lambda item: (item.condition_key, item.condition_value),
                ),
            )
        )

    validate_procedure_registry(known_steps)
    return known_steps


def load_reviewed_procedure_store(
    payload: ReviewedProcedureSnapshot | Mapping[str, object],
) -> InMemoryReviewedProcedureStore:
    """Validate a complete reviewed snapshot without deriving missing fields."""

    source = (
        payload.model_dump(mode="python")
        if isinstance(payload, ReviewedProcedureSnapshot)
        else payload
    )
    snapshot = ReviewedProcedureSnapshot.model_validate(source)
    return InMemoryReviewedProcedureStore.from_snapshot(snapshot)


def load_reviewed_procedures() -> InMemoryReviewedProcedureStore:
    """동봉된 검수 원본을 읽는다. DB 적재 및 조회 자료의 검수 확인에 사용한다."""
    path = Path(__file__).with_name("reviewed-procedures.ko-KR.json")
    try:
        return load_reviewed_procedure_store(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ProcedureStoreError("검수 절차 파일을 읽거나 검증하지 못했습니다.") from exc


def build_reviewed_procedure_store(
    snapshots_by_step: Mapping[str, Mapping[str, object]],
    *,
    known_procedure_steps: Sequence[KnownProcedureStep],
    procedure_bindings: ProcedureBindings | None = None,
) -> InMemoryReviewedProcedureStore:
    """Join DB JSON values keyed by actual step_code; never query SQL or files.

    BE extracts non-null reviewed_source_snapshot values from ProcedureStep.
    The proposed column stays BE-owned. Logical document codes are retained;
    lookup translates them using the same validated bindings as the runtime.
    """
    validate_procedure_registry(known_procedure_steps)
    bindings = resolve_procedure_bindings(known_procedure_steps, procedure_bindings)
    if not snapshots_by_step:
        raise ProcedureStoreError("DB에 검수 절차 자료가 없습니다.")
    metadata: dict[str, object] | None = None
    records: list[ReviewedProcedureRecord] = []
    try:
        for step_code, payload in snapshots_by_step.items():
            snapshot = ReviewedProcedureSnapshot.model_validate(payload)
            current = snapshot.model_dump(mode="python", exclude={"records"})
            if metadata is not None and metadata != current:
                raise ProcedureStoreError("DB 절차 자료의 버전·생성 시각·언어가 다릅니다.")
            metadata = current
            if not snapshot.records:
                raise ProcedureStoreError("DB 절차 자료의 문서 목록이 비어 있습니다.")
            for record in snapshot.records:
                if record.reviewed_by is None or record.reviewed_at is None:
                    raise ProcedureStoreError("개발자가 검수·승인한 자료만 사용할 수 있습니다.")
                if any(code not in bindings for code in record.step_codes):
                    raise ProcedureStoreError("DB 자료의 논리 절차 코드에 대응값이 없습니다.")
                related = {bindings[code].step_code for code in record.step_codes}
                if step_code not in related:
                    raise ProcedureStoreError("DB 절차 행과 문서의 절차 대응이 다릅니다.")
            records.extend(snapshot.records)
        # Keep the collected-body hash as supplied; an excerpt is not that body.
        return load_reviewed_procedure_store({**metadata, "records": records})
    except ValueError as exc:
        raise ProcedureStoreError("DB 검수 절차 자료를 검증하지 못했습니다.") from exc


def import_reviewed_procedures(
    session: Session,
    case_id: int,
    store: ReviewedProcedureStore,
    *,
    as_of: date,
) -> list[Evidence]:
    """검수 자료를 기존 Case에 저장한다. commit/rollback은 호출자가 수행한다.

    같은 버전의 같은 자료는 다시 쓰지 않으며, 변경하려면 새 버전이 필요하다.
    MySQL DATETIME의 초 정밀도와 BE의 KST 저장 규칙에 맞춰 시각을 저장한다.
    """
    if type(case_id) is not int or case_id <= 0:
        raise ValueError("case_id must be a positive integer")
    if type(as_of) is not date:
        raise TypeError("as_of must be a date")
    version = store.snapshot_version
    if not isinstance(version, str) or not version:
        raise ProcedureStoreError("검수 자료 버전이 필요합니다.")
    rows: list[Evidence] = []
    seen: set[str] = set()
    for item in store.records():
        record = ReviewedProcedureRecord.model_validate(item.model_dump(mode="python"))
        if record.reviewed_by is None or record.reviewed_at is None:
            raise ProcedureStoreError("사람이 검수한 자료만 저장할 수 있습니다.")
        identity = json.dumps([case_id, version, record.record_id], ensure_ascii=False)
        evidence_id = "procedure:" + sha256(identity.encode("utf-8")).hexdigest()
        if evidence_id in seen:
            raise ProcedureStoreError("검수 자료 식별자가 중복됐습니다.")
        seen.add(evidence_id)
        payload = {
            "evidence_id": evidence_id,
            "case_id": case_id,
            "source_type": "OFFICIAL_DOCUMENT",
            "source_ref": record.canonical_url,
            "source_version": version,
            "locator": record.canonical_url,
            "excerpt": record.excerpt,
            "published_at": _procedure_db_time(record.published_at),
            "retrieved_at": _procedure_db_time(record.retrieved_at),
            "freshness_status": record.freshness(as_of).value,
            "content_hash": record.content_hash.removeprefix("sha256:"),
        }
        for field, value in payload.items():
            limit = getattr(Evidence.__table__.c[field].type, "length", None)
            if isinstance(value, str) and limit is not None and len(value) > limit:
                raise ProcedureStoreError(f"검수 자료가 DB 필드 길이를 초과했습니다: {field}")
        rows.append(Evidence.model_validate(payload))

    # Reads must not flush unrelated pending work before all input is validated.
    with session.no_autoflush:
        if case_crud.get_case_by_id(session, case_id) is None:
            raise ProcedureStoreError("자료를 저장할 Case가 없습니다.")
        existing = {
            row.evidence_id: row
            for row in evidence_crud.get_evidence_by_case_id(session, case_id)
        }
    for row in rows:
        previous = existing.get(row.evidence_id)
        if previous is not None:
            fields = row.model_dump(exclude={"id", "created_at"})
            if any(getattr(previous, key) != value for key, value in fields.items()):
                raise ProcedureStoreError("같은 검수 자료 ID에 다른 내용이 저장돼 있습니다.")
    return [
        existing[row.evidence_id]
        if row.evidence_id in existing
        else evidence_crud.create_evidence(session, row)
        for row in rows
    ]


def _procedure_db_time(value: datetime | None) -> datetime | None:
    return (
        None
        if value is None
        else value.astimezone(KST).replace(tzinfo=None, microsecond=0)
    )


def load_reviewed_support_catalog(
    payload: ReviewedSupportCatalog | Mapping[str, object],
) -> ReviewedSupportCatalog:
    """Validate and detach a complete reviewed support-catalog payload."""

    source = (
        payload.model_dump(mode="python")
        if isinstance(payload, ReviewedSupportCatalog)
        else payload
    )
    return ReviewedSupportCatalog.model_validate(source).model_copy(deep=True)


def build_reviewed_support_catalog(
    support_items: Sequence[SupportItem],
    reviewed_catalog: ReviewedSupportCatalog | Mapping[str, object],
) -> ReviewedSupportCatalog:
    """Bind reviewed programs to persisted BE IDs by their exact Wiki UUID."""

    catalog = load_reviewed_support_catalog(reviewed_catalog)
    items_by_uuid: dict[UUID, tuple[int, SupportItem]] = {}
    seen_ids: set[int] = set()
    for item in support_items:
        item_id = _persisted_id(item.id, "support_item.id")
        if item_id in seen_ids:
            raise ValueError(f"duplicate support_item.id: {item_id}")
        seen_ids.add(item_id)
        try:
            wiki_uuid = UUID(item.uuid)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError(
                f"support_item {item_id} has an invalid Wiki UUID"
            ) from exc
        if wiki_uuid in items_by_uuid:
            raise ValueError(f"duplicate support_item.uuid: {wiki_uuid}")
        items_by_uuid[wiki_uuid] = (item_id, item)

    payload = catalog.model_dump(mode="python")
    for program, program_payload in zip(catalog.programs, payload["programs"]):
        wiki_uuid = program.support_program.wiki_uuid
        matched = items_by_uuid.get(wiki_uuid)
        if matched is None:
            raise ValueError(f"reviewed support program has no BE row: {wiki_uuid}")
        item_id, item = matched
        if item.program_name != program.program_name:
            raise ValueError(
                f"support program name mismatch for Wiki UUID {wiki_uuid}"
            )
        if (
            item.catalog_version is not None
            and item.catalog_version != catalog.catalog_version
        ):
            raise ValueError(
                f"support catalog version mismatch for Wiki UUID {wiki_uuid}"
            )
        program_payload["support_program"]["support_program_id"] = item_id

    return ReviewedSupportCatalog.model_validate(payload)


def _persisted_id(value: int | None, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a persisted positive integer")
    return value


def _known_step_id(
    value: int,
    steps_by_id: Mapping[int, ProcedureStep],
    field_name: str,
) -> int:
    step_id = _persisted_id(value, field_name)
    if step_id not in steps_by_id:
        raise ValueError(f"{field_name} references unloaded procedure step {step_id}")
    return step_id


def _attach_db_timezone(
    value: datetime | None,
    *,
    db_timezone: tzinfo,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value
    aware = value.replace(tzinfo=db_timezone)
    if aware.utcoffset() is None:
        raise ValueError(f"{field_name} could not be interpreted with db_timezone")
    return aware
