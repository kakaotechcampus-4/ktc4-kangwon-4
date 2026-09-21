"""Standalone command-line entry point for the persistence-free Agent graph."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from pydantic import TypeAdapter

from app.agent.llm import LLMClientError, resolve_max_calls_per_run
from app.agent.runtime import (
    RuntimeLimits,
    build_runtime,
    resolve_run_deadline_seconds,
)
from app.agent.schemas import AgentGraphInput, KnownProcedureStep
from app.agent.support_agent import (
    JsonFileSupportStore,
    ReviewedSupportCatalog,
)
from app.agent.support_agent.wiki import MarkdownSupportWikiStore

_MAX_INPUT_BYTES = 4 * 1024 * 1024


def _deadline_seconds(value: str) -> float:
    try:
        return RuntimeLimits(
            max_llm_calls_per_run=1, run_deadline_seconds=float(value)
        ).run_deadline_seconds
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "deadline must satisfy the finite positive RuntimeLimits bound"
        ) from exc


def _max_llm_calls(value: str) -> int:
    try:
        return RuntimeLimits(
            max_llm_calls_per_run=int(value), run_deadline_seconds=1
        ).max_llm_calls_per_run
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "call budget must be a positive integer"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the RE:BORN Agent graph on an exported real Case request and "
            "procedure registry. Reads configured procedure/support stores and "
            "returns an Agent outcome without BE persistence."
        )
    )
    parser.add_argument(
        "--request",
        type=Path,
        required=True,
        help="actual BE-exported AgentGraphInput JSON (maximum 4 MiB)",
    )
    parser.add_argument(
        "--procedure-steps",
        type=Path,
        required=True,
        help="actual KnownProcedureStep[] registry JSON (maximum 4 MiB)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="allow configured LLM calls",
    )
    parser.add_argument(
        "--support-wiki",
        type=Path,
        default=None,
        help="optional reviewed Wiki directory for exact support ID/UUID lookup",
    )
    parser.add_argument(
        "--trace-id", default=None, help="metadata-only trace identifier"
    )
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write JSON to a new 0600 file; existing paths are refused",
    )
    parser.add_argument(
        "--max-llm-calls",
        type=_max_llm_calls,
        default=None,
        help="override the provider-call budget for this invocation",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=_deadline_seconds,
        default=None,
        help="override the whole-run time limit for this invocation",
    )
    return parser


def _read_input(path: Path) -> bytes:
    if not path.is_file():
        raise ValueError("input must be a regular file")
    with path.open("rb") as source:
        payload = source.read(_MAX_INPUT_BYTES + 1)
    if len(payload) > _MAX_INPUT_BYTES:
        raise ValueError("input exceeds the 4 MiB limit")
    return payload


def _support_catalog(
    known_steps: Sequence[KnownProcedureStep],
) -> ReviewedSupportCatalog:
    """Load the configured catalog, preserving an empty reviewed selection."""

    snapshot = JsonFileSupportStore.from_env().snapshot()
    catalog, pending = snapshot.build_catalog(known_steps=known_steps)
    print(
        f"Support catalog: {len(catalog.programs)} reviewed, "
        f"{pending} awaiting review and eligibility rules.",
        file=sys.stderr,
    )
    return catalog


def _private_output(path: str, flags: int) -> int:
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


@contextmanager
def _output_destination(path: Path | None) -> Iterator[TextIO]:
    if path is None:
        yield sys.stdout
    else:
        with open(path, "x", encoding="utf-8", opener=_private_output) as output:
            yield output


async def _run(args: argparse.Namespace) -> int:
    request = AgentGraphInput.model_validate_json(_read_input(args.request))
    known_steps = TypeAdapter(list[KnownProcedureStep]).validate_json(
        _read_input(args.procedure_steps)
    )
    if args.trace_id is not None:
        request = AgentGraphInput.model_validate(
            {**request.model_dump(mode="python"), "trace_id": args.trace_id}
        )
    limits = RuntimeLimits(
        max_llm_calls_per_run=(
            args.max_llm_calls
            if args.max_llm_calls is not None
            else resolve_max_calls_per_run()
        ),
        run_deadline_seconds=(
            args.deadline_seconds
            if args.deadline_seconds is not None
            else resolve_run_deadline_seconds()
        ),
    )

    runtime = await build_runtime(
        known_procedure_steps=known_steps,
        support_catalog=_support_catalog(known_steps),
        support_wiki=(
            MarkdownSupportWikiStore(args.support_wiki, known_steps=known_steps)
            if args.support_wiki is not None
            else None
        ),
        limits=limits,
    )
    try:
        # Reserve the output before spending any provider calls. Exclusive
        # creation also refuses symlinks and protects existing user files.
        with _output_destination(args.output) as output:
            outcome = await runtime.run_planning(request)
            json.dump(
                outcome.model_dump(mode="json"),
                output,
                ensure_ascii=False,
                indent=None if args.compact else 2,
                separators=(",", ":") if args.compact else None,
            )
            output.write("\n")
    finally:
        try:
            runtime.flush()
        finally:
            await runtime.aclose()
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
