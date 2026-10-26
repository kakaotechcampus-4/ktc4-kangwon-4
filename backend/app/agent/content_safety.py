"""Model-based content checks that never return source text or reasoning."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.agent import prompts
from app.agent.llm import LLMRequestError, LLMResponseError, StructuredLLMClient
from app.agent.projection import (
    ensure_projection_has_no_obvious_sensitive_text,
    to_model_projection,
)
from app.agent.schemas import (
    AgentGraphInput,
    AgentGraphOutput,
    CaseFact,
    CrisisSupportGuidance,
    EvidenceRecord,
    InfoAnalysisResult,
    RedactedInput,
)


class SafetyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    decision: Literal["ALLOW", "REFUSE", "CRISIS_SUPPORT"]


class CrisisSupportRequired(RuntimeError):
    """Stop business processing and deliver only the fixed checked guidance."""

    def __init__(self, guidance: CrisisSupportGuidance | None = None) -> None:
        self.guidance = CrisisSupportGuidance.model_validate(
            (guidance or CrisisSupportGuidance()).model_dump(mode="python")
        )
        super().__init__("Crisis support is required before business processing")


class SafetyBlockedError(RuntimeError):
    retryable = False

    def __init__(self, decision: str) -> None:
        self.decision = SafetyDecision.model_validate({"decision": decision}).decision
        self.code = "AGENT_SAFETY_" + self.decision
        super().__init__("Content safety check blocked the response")


class SafetyCheckUnavailableError(RuntimeError):
    code = "AGENT_SAFETY_CHECK_UNAVAILABLE"
    retryable = True

    def __init__(self) -> None:
        super().__init__("Content safety check is unavailable")


class ContentSafetyGuard:
    def __init__(self, client: StructuredLLMClient) -> None:
        self._client = client

    async def check_submission(
        self, redacted_text: str | RedactedInput, facts: Sequence[CaseFact] | None = None
    ) -> None:
        """Check a BE-redacted submission before its business data is saved.

        The caller owns authorization, redaction and the call budget/deadline.
        This method neither persists the submission nor reports that it was saved.
        """
        if isinstance(redacted_text, RedactedInput):
            submission = RedactedInput.model_validate(redacted_text.model_dump(mode="python"))
            payload = to_model_projection(submission)
            payload["redacted_text"] = submission.redacted_text
        else:
            if not isinstance(redacted_text, str) or not redacted_text.strip():
                raise ValueError("redacted_text must be a nonempty string")
            payload = {"redacted_text": redacted_text}
        context = [
            CaseFact.model_validate(item.model_dump(mode="python"))
            for item in facts or ()
        ]
        payload["facts"] = to_model_projection(context)
        try:
            await self._check("SUBMISSION", payload)
        except CrisisSupportRequired as signal:
            await self._check("OUTPUT", {"guidance": signal.guidance.model_dump(mode="json")})
            raise

    async def check_sources(self, evidence_records: Sequence[EvidenceRecord]) -> None:
        """Screen source bodies as untrusted data before another model reads them."""
        records = [
            EvidenceRecord.model_validate(item.model_dump(mode="python"))
            for item in evidence_records
        ]
        sources = [
            {"source_type": item.source_type.value, "excerpt": item.excerpt}
            for item in records
            if item.excerpt
        ]
        if sources:
            await self._check("SOURCES", {"sources": sources})

    async def check_input(self, request: AgentGraphInput) -> None:
        # The trigger holds the current submission; snapshot evidence is history.
        trigger = to_model_projection(request.trigger)
        current_input = getattr(request.trigger, "input", None)
        if current_input is not None:
            trigger["input"]["redacted_text"] = current_input.redacted_text
        pending = getattr(request.trigger, "pending_input", None)
        if pending is not None:
            # A retained report is history to screen, never a new instruction.
            trigger["pending_input"]["original_input"]["redacted_text"] = (
                pending.original_input.redacted_text
            )
        await self._check(
            "INPUT",
            {
                "trigger": trigger,
                "case_snapshot": to_model_projection(request.case_snapshot),
            },
        )

    async def check_output(self, outcome: AgentGraphOutput) -> None:
        if outcome.outcome_type == "SAFE_FAILURE":
            return
        if outcome.outcome_type == "CRISIS_SUPPORT":
            guidance = CrisisSupportGuidance.model_validate(outcome.guidance.model_dump(mode="python"))
            payload = {"guidance": guidance.model_dump(mode="json")}
        elif outcome.outcome_type == "REVIEWED_PLAN":
            payload = {
                "supervisor_draft": outcome.review_subject.supervisor_draft.model_dump(
                    mode="json"
                ),
                "analysis": [
                    {
                        field: [
                            item.model_dump(include={"reason_summary", "text"}, mode="json")
                            for item in getattr(source.output, field)
                        ]
                        for field in (
                            "fact_candidates", "procedure_progress_observations",
                            "missing_fields", "uncertainties", "question_candidates",
                        )
                    }
                    for source in outcome.review_subject.source_results
                    if isinstance(source.output, InfoAnalysisResult)
                ],
            }
        else:
            payload = {
                "conflicts": [item.model_dump(mode="json") for item in outcome.conflicts]
            }
        await self._check("OUTPUT", to_model_projection(payload))

    async def _check(
        self,
        stage: Literal["INPUT", "OUTPUT", "SUBMISSION", "SOURCES"],
        payload: dict[str, Any],
    ) -> None:
        ensure_projection_has_no_obvious_sensitive_text(payload)
        try:
            result = await self._client.generate(
                SafetyDecision,
                prompts.content_safety_messages(stage, payload),
                schema_name="ContentSafetyDecision",
                max_retries=0,
            )
            decision = SafetyDecision.model_validate(result).decision
        except LLMResponseError as exc:
            if exc.code == "PROVIDER_REFUSAL":
                raise SafetyBlockedError("REFUSE") from None
            raise SafetyCheckUnavailableError() from None
        except (LLMRequestError, ValidationError):
            raise SafetyCheckUnavailableError() from None
        if decision == "CRISIS_SUPPORT":
            if stage not in {"INPUT", "SUBMISSION"}:
                raise SafetyCheckUnavailableError()
            raise CrisisSupportRequired()
        if decision == "REFUSE":
            raise SafetyBlockedError(decision)
