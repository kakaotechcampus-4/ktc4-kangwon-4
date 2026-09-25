"""Repeat real Supervisor calls with frozen inputs and a fixed Review model.

Run from the repository root with PYTHONPATH=backend. Inputs are synthetic
SupervisorAgentInput JSON files; --validate-only never calls the provider.
Reports contain synthetic decisions and review issues, never credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
from app.agent.llm import LLMCallBudget, LLMConfig, StructuredLLMClient
from app.agent.review_tool import ReviewTool
from app.agent.schemas import ReviewSubject, SupervisorAgentInput, canonical_digest
from app.agent.supervisor import SupervisorAgent


class MeasuredSupervisor(SupervisorAgent):
    fallback_used = False

    def _missing_info_fallback(self, *args, **kwargs):
        self.fallback_used = True
        return super()._missing_info_fallback(*args, **kwargs)


async def trial(request, config, review_config):
    budget = LLMCallBudget(max_calls=2)
    calls = []

    async def capture_request(http_request):
        body = json.loads(http_request.content)
        calls.append(
            {
                "model": body.get("model"),
                "reasoning_effort": body.get("reasoning_effort"),
                "max_completion_tokens": body.get("max_completion_tokens"),
                "request_without_model_digest": hashlib.sha256(
                    json.dumps(
                        {key: value for key, value in body.items() if key != "model"},
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode()
                ).hexdigest(),
            }
        )

    result = {
        "input_digest": canonical_digest(request),
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
        "review_model": review_config.model,
        "review_reasoning_effort": review_config.reasoning_effort,
        "status": "ERROR",
        "fallback_used": False,
        "stage": "SUPERVISOR",
        "calls": calls,
        "limits": {
            "provider_calls": 2,
            "supervisor_timeout_seconds": config.timeout_seconds,
            "review_timeout_seconds": review_config.timeout_seconds,
            "rework": 0,
        },
    }
    start = perf_counter()
    async with (
        httpx.AsyncClient(
            event_hooks={"request": [capture_request]}
        ) as supervisor_http,
        httpx.AsyncClient(event_hooks={"request": [capture_request]}) as review_http,
    ):
        supervisor_client = StructuredLLMClient(
            replace(config, max_retries=0),
            client=supervisor_http,
            call_budget=budget,
        )
        reviewer = StructuredLLMClient(
            replace(review_config, max_retries=0),
            client=review_http,
            call_budget=budget,
        )
        supervisor = MeasuredSupervisor(
            supervisor_client,
            max_local_attempts=1,
            clock=lambda: request.case_snapshot.captured_at,
        )
        try:
            draft = await supervisor.draft(request.model_copy(deep=True))
            result["fallback_used"] = supervisor.fallback_used
            result["supervisor_ms"] = round((perf_counter() - start) * 1000)
            result["draft"] = draft.model_dump(mode="json")
            result["stage"] = "REVIEW"
            subject = ReviewSubject.create(
                schema_version="agent-io/2.0",
                review_subject_id=uuid4(),
                review_attempt=1,
                run_id=request.source_results[0].meta.run_id,
                case_id=request.case_snapshot.case_id,
                trigger=request.trigger,
                snapshot=request.case_snapshot,
                known_procedure_steps=request.known_procedure_steps,
                source_results=request.source_results,
                supervisor_draft=draft,
            )
            review = await ReviewTool(
                reviewer, max_output_attempts=1, provider_max_retries=0
            ).review(subject)
            result["review"] = review.model_dump(mode="json")
            result["status"] = (
                "SUPERVISOR_FALLBACK"
                if supervisor.fallback_used
                else "REVIEWED_PLAN"
                if review.verdict.value == "PASS"
                else "REVIEW_REJECTED"
            )
            result["stage"] = "COMPLETE"
        except Exception as exc:  # noqa: BLE001 - record failures without secret-bearing messages
            # Exception messages may contain provider bodies or request URLs.
            result["error"] = {
                "type": type(exc).__name__,
                "code": getattr(exc, "code", None),
                "status_code": getattr(exc, "status_code", None),
            }
        finally:
            result["fallback_used"] = supervisor.fallback_used
    result["elapsed_ms"] = round((perf_counter() - start) * 1000)
    result["provider_calls"] = budget.spent
    return result


async def run(args):
    inputs = [
        (path.stem, SupervisorAgentInput.model_validate_json(path.read_text()))
        for path in args.input
    ]
    if args.validate_only:
        print(json.dumps({"validated_inputs": len(inputs), "provider_calls": 0}))
        return
    configs = [
        LLMConfig.from_env(environ={}, env_prefix=prefix)
        for prefix in args.model_prefix
    ]
    review_config = LLMConfig.from_env(environ={}, env_prefix=args.review_prefix)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    semaphore = asyncio.Semaphore(2)

    async def run_case(case, request):
        for repeat in range(1, args.repeats + 1):
            order = configs if repeat % 2 else list(reversed(configs))
            for config in order:
                async with semaphore:
                    result = await trial(request, config, review_config)
                result.update(case=case, repeat=repeat)
                rows.append(result)
                path = args.output / f"trial-{len(rows):03d}.json"
                path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
                print(
                    json.dumps(
                        {
                            key: result[key]
                            for key in [
                                "case",
                                "model",
                                "repeat",
                                "status",
                                "elapsed_ms",
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                if (result.get("error") or {}).get("status_code") in (401, 403):
                    raise SystemExit(
                        "Provider rejected credentials; remaining trials stopped."
                    )

    await asyncio.gather(*(run_case(case, request) for case, request in inputs))
    (args.output / "results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--model-prefix", action="append")
    parser.add_argument("--review-prefix", default="SUPERVISOR_")
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    args.model_prefix = args.model_prefix or ["LUNA_", "SUPERVISOR_"]
    asyncio.run(run(args))
