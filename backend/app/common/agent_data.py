"""Pure adapters from BE-owned data into the Agent's reviewed input contracts.

This module never opens a database session.  BE loaders must supply complete ORM
row sets and complete, human-reviewed payloads.  The adapters validate those
inputs and fail closed; they do not fill missing review data, Evidence, versions,
or timestamps.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo

from app.agent.procedure_tool.store import (
    ReviewedProcedureRecord,
    ReviewedProcedureSnapshot,
)
from app.agent.schemas import (
    KnownProcedureStep,
    ProcedureDependency,
    ProcedureEligibility,
    ProcedureStepRef,
    validate_procedure_registry,
)
from app.agent.support_agent.models import ReviewedSupportCatalog
from app.be.models.procedure_step import (
    ProcedureStep,
    StepDependency,
    StepEligibility,
)

__all__ = [
    "InMemoryReviewedProcedureStore",
    "build_known_procedure_steps",
    "load_reviewed_procedure_store",
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
