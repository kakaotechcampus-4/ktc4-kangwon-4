"""Bounded prompts for the RE:BORN Agent components.

The prompts deliberately ask for short, externally reviewable summaries.  They
must never request or persist hidden chain-of-thought.  Runtime-only metadata
(tokens, credentials and trace identifiers) is not accepted by these helpers.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

SAFETY_RULES = """
- Use only facts and evidence present in INPUT_JSON.
- Never invent dates, deadlines, fees, amounts, eligibility, legal conclusions,
  tax conclusions, program names, identifiers, or source references.
- Keep unknown information unknown. Do not turn missing data into a negative.
- Support-program eligibility is never final; use a needs-confirmation status.
- Return only the requested JSON object. Do not include markdown or hidden reasoning.
""".strip()


def _json_payload(value: BaseModel | dict[str, Any]) -> str:
    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json")
    else:
        data = value
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def info_messages(value: BaseModel | dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are the RE:BORN information-analysis component. Extract only "
                "explicitly stated closure-case facts from the redacted user text. "
                "Use the supplied canonical enum values exactly. Every extracted fact "
                "must quote a minimal exact source_text substring. If wording is "
                "ambiguous, emit a question or missing field instead of guessing.\n"
                + SAFETY_RULES
            ),
        },
        {"role": "user", "content": "INPUT_JSON=" + _json_payload(value)},
    ]


def support_messages(value: BaseModel | dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are the RE:BORN support-program analysis component. Compare the "
                "case facts only with the supplied reviewed catalog entries. You may "
                "select only supplied program IDs and evidence IDs. STALE or UNKNOWN "
                "sources must be UNVERIFIABLE or STALE, never a positive match. Never "
                "say that a person is eligible or guaranteed to receive support.\n"
                + SAFETY_RULES
            ),
        },
        {"role": "user", "content": "INPUT_JSON=" + _json_payload(value)},
    ]


def supervisor_messages(value: BaseModel | dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are the RE:BORN Supervisor. Select one current blocker and, only "
                "when executable, exactly one real-world next action. Base the draft "
                "only on the supplied validated component results. If evidence is "
                "insufficient, ask for information rather than asserting a conclusion. "
                "Use only supplied evidence IDs and stable procedure references. Keep "
                "the Korean wording direct and understandable to a middle-aged owner. "
                "For ACTION, questions_for_user must be empty; put confirmation questions "
                "inside next_action.questions_to_ask. Every ELIGIBILITY claim must set "
                "assertion_level to NEEDS_CONFIRMATION. For each grounded_claim, select "
                "one supplied target_kind; set target_index only for a question target. "
                "The runtime binds the selected field's exact text and final path.\n"
                + SAFETY_RULES
            ),
        },
        {"role": "user", "content": "INPUT_JSON=" + _json_payload(value)},
    ]


def review_messages(value: BaseModel | dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are the independent RE:BORN Review component. Review only the "
                "provided immutable subject. PASS only when every user-visible claim "
                "has resolvable evidence, unknowns remain explicit, there is exactly "
                "one blocker and one action for ACTION, the action is feasible, and no "
                "eligibility/legal/tax/date claim is overconfident. Do not repair the "
                "draft and do not introduce new facts. Report concise issues only.\n"
                + SAFETY_RULES
            ),
        },
        {"role": "user", "content": "INPUT_JSON=" + _json_payload(value)},
    ]
