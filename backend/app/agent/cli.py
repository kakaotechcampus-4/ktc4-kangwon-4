"""Standalone command-line entry point for the persistence-free Agent graph."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from app.agent.fixtures import build_standalone_fixture
from app.agent.llm import LLMClientError
from app.agent.runtime import build_runtime
from app.agent.support_agent import JsonFileSupportStore, SupportStoreError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the RE:BORN Agent graph without BE persistence. It uses a "
            "synthetic Case and support catalog, and reads closure procedures "
            "from the reviewed snapshot rather than the live internet."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="allow configured LLM calls",
    )
    parser.add_argument(
        "--trace-id", default=None, help="metadata-only trace identifier"
    )
    parser.add_argument("--compact", action="store_true", help="print compact JSON")
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=None,
        help="override the whole-run time limit for this invocation",
    )
    return parser


def _support_catalog(fixture: Any) -> Any:
    """Prefer the reviewed catalog; fall back to the labelled demo one.

    A discovered notice is only served once a person has written its
    eligibility rules, so a fresh catalog is empty and the support step would
    have nothing to compare.  The fixture keeps the loop demonstrable, and its
    programme name says in the text that it is not a real scheme, so it cannot
    be mistaken for one.
    """

    try:
        snapshot = JsonFileSupportStore.from_env().snapshot()
    except SupportStoreError:
        print(
            "Reviewed support catalog unavailable; using the demo catalog.",
            file=sys.stderr,
        )
        return fixture.support_catalog
    catalog, pending = snapshot.build_catalog(known_steps=fixture.known_procedure_steps)
    if catalog.programs:
        print(
            f"Support catalog {snapshot.catalog_version}: "
            f"{len(catalog.programs)} reviewed, {pending} awaiting review.",
            file=sys.stderr,
        )
        return catalog
    print(
        f"Support catalog {snapshot.catalog_version} has no reviewed programme "
        f"yet ({pending} awaiting eligibility rules); using the demo catalog. "
        "Run app.support_agent.refresh, then review each notice.",
        file=sys.stderr,
    )
    return fixture.support_catalog


async def _run(args: argparse.Namespace) -> int:
    fixture = build_standalone_fixture()
    request = fixture.request.model_copy(deep=True)
    request.trace_id = args.trace_id

    runtime = await build_runtime(
        known_procedure_steps=fixture.known_procedure_steps,
        support_catalog=_support_catalog(fixture),
    )
    try:
        outcome = await runtime.run_planning(
            request,
            deadline_seconds=args.deadline_seconds,
        )
    finally:
        runtime.flush()
        await runtime.aclose()

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
    if args.deadline_seconds is not None and args.deadline_seconds <= 0:
        parser.error("--deadline-seconds must be positive")
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
