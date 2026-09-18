"""Standalone command-line entry point for the persistence-free Agent graph."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from app.agent.fixtures import build_standalone_fixture
from app.agent.graph import AgentGraph
from app.agent.info_agent import InfoAnalysisAgent
from app.agent.llm import LLMCallBudget, LLMClientError, StructuredLLMClient
from app.agent.procedure_tool import ProcedureLookupTool
from app.agent.review_tool import ReviewTool
from app.agent.supervisor import SupervisorAgent
from app.agent.support_agent import SupportAgent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the RE:BORN Agent graph without BE persistence. "
            "It uses a synthetic Case/support catalog, but retrieves closure "
            "procedure sources from the real internet."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="allow configured LLM calls and real procedure web requests",
    )
    parser.add_argument(
        "--trace-id", default=None, help="metadata-only trace identifier"
    )
    parser.add_argument("--compact", action="store_true", help="print compact JSON")
    return parser


async def _run(args: argparse.Namespace) -> int:
    fixture = build_standalone_fixture()
    request = fixture.request.model_copy(deep=True)
    request.trace_id = args.trace_id

    client: StructuredLLMClient | None = None
    supervisor_client: StructuredLLMClient | None = None
    procedure_tool: ProcedureLookupTool | None = None
    try:
        # Both clients share one budget, so splitting Supervisor onto another
        # provider does not double what a single run may spend.
        call_budget = LLMCallBudget()
        client = StructuredLLMClient.from_env(call_budget=call_budget)
        supervisor_client = StructuredLLMClient.from_env(
            env_prefix="SUPERVISOR_",
            call_budget=call_budget,
        )
        procedure_tool = ProcedureLookupTool.from_env()
        runtime = AgentGraph(
            info_agent=InfoAnalysisAgent(client),
            procedure_tool=procedure_tool,
            support_agent=SupportAgent(client, fixture.support_catalog),
            supervisor=SupervisorAgent(supervisor_client),
            review_tool=ReviewTool(client),
            known_procedure_steps=fixture.known_procedure_steps,
            call_budget=call_budget,
        )
        outcome = await runtime.run(request)
    finally:
        if procedure_tool is not None:
            await procedure_tool.aclose()
        if supervisor_client is not None:
            await supervisor_client.aclose()
        if client is not None:
            await client.aclose()

    data = outcome.model_dump(mode="json")
    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        )
    )
    return 2 if outcome.outcome_type == "SAFE_FAILURE" else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required because this command calls the configured LLM")
    try:
        return asyncio.run(_run(args))
    except LLMClientError as exc:
        print(
            f"Agent LLM call failed safely: {exc.code} "
            f"(retryable={str(exc.retryable).lower()})",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError):
        print("Agent input/configuration failed safely.", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - CLI must never expose private exception detail
        print("Agent execution failed safely.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
