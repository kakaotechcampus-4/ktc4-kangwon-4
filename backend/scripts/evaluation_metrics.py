"""Metadata-only evaluation metrics shared by Agent validation scripts."""

import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean, median

from dotenv import dotenv_values


def write_metadata(path: Path, value) -> None:
    """Keep a complete metadata file even when the process is interrupted."""
    pending = path.with_name(path.name + ".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


async def evaluate_efforts(configurations, evaluate):
    """Stop weaker efforts for a model after its first failed evaluation."""
    failed = set()
    for label, prefix, config in configurations:
        if prefix in failed:
            yield label, prefix, config, None
            continue
        group = await evaluate(label, config, 1)
        if not group["passed"]:
            failed.add(prefix)
        yield label, prefix, config, group


def evaluation_code_digest() -> str:
    """Identify the exact Agent, prompts, dataset and evaluation harness bytes."""
    backend_root = Path(__file__).resolve().parents[1]
    files = sorted([
        *backend_root.joinpath("app/agent").rglob("*.py"),
        *backend_root.joinpath("scripts").rglob("*.py"),
    ])
    content = hashlib.sha256()
    for path in files:
        content.update(str(path.relative_to(backend_root)).encode())
        content.update(path.read_bytes())
    return "sha256:" + content.hexdigest()


def price_model(model: str) -> str:
    provider, separator, name = model.partition("/")
    return name if separator and provider in {"openai", "anthropic", "google"} else model


def load_prices(*, env_file=None, environ=None) -> dict[str, tuple[float, float, float]]:
    """KRW input/cache/output rates, bound to the exact quoted model ID."""
    path = env_file or Path(__file__).resolve().parents[2] / ".env"
    values = dict(dotenv_values(path))
    values.update(os.environ if environ is None else environ)
    prices = {}
    for prefix in ("OPENAI_", "LUNA_", "LUNA6_", "HAIKU_", "GEMINI_"):
        raw = [values.get(prefix + part + "_KRW_PER_MILLION")
               for part in ("INPUT", "CACHED_INPUT", "OUTPUT")]
        if not any(str(item or "").strip() for item in raw):
            continue
        try:
            rates = tuple(float(item) for item in raw)
        except (ValueError, TypeError):
            raise SystemExit(f"{prefix}INPUT/CACHED_INPUT/OUTPUT_KRW_PER_MILLION must all be filled") from None
        model = values.get(prefix + "PRICE_MODEL") or values.get(prefix + "MODEL")
        if not model or any(not math.isfinite(rate) or rate < 0 for rate in rates):
            raise SystemExit(f"{prefix}price requires a model and finite nonnegative rates")
        prices[price_model(model)] = rates
    return prices


def summarize_metrics(rows: list[dict], prices: dict | None = None) -> dict:
    """Include failed attempts in cost, and divide only by successful tasks."""
    prices = prices or {}
    usage = [call for row in rows for call in row.get("provider_usage", [])]
    attempts = sum(sum(row.get("calls_by_role", {}).values()) for row in rows)
    complete = bool(usage) and len(usage) == attempts and all(
        call.get("prompt_tokens") is not None and call.get("completion_tokens") is not None
        for call in usage
    )
    totals = {
        key: sum(call.get(key) or 0 for call in usage)
        for key in ("prompt_tokens", "completion_tokens")
    }
    successful = sum(
        row.get("status") == "REVIEWED_PLAN" and "error" not in row
        and row.get("behavior_passed", True)
        and row.get("score", {}).get("result", "PASS") == "PASS" for row in rows
    )
    cost = uncached_cost = 0.0 if complete else None
    unpriced_models = set()
    cache_complete = bool(usage) and all(
        call.get("prompt_tokens") is not None and call.get("cached_prompt_tokens") is not None
        and 0 <= call["cached_prompt_tokens"] <= call["prompt_tokens"] for call in usage
    )
    for call in usage:
        model = price_model(call.get("model") or call.get("requested_model") or "")
        requested = price_model(call.get("requested_model") or model)
        rates = prices.get(model)
        if rates is None or model != requested:
            unpriced_models.add(model)
            cost = uncached_cost = None
            continue
        cached, prompt, output = (call.get(key) for key in (
            "cached_prompt_tokens", "prompt_tokens", "completion_tokens",
        ))
        if uncached_cost is not None:
            uncached_cost += (prompt * rates[0] + output * rates[2]) / 1_000_000
        if cached is None or prompt is None or not 0 <= cached <= prompt:
            cache_complete = False
            cost = None
        if cost is not None:
            cost += ((prompt - cached) * rates[0] + cached * rates[1] + output * rates[2]) / 1_000_000
    times = sorted(row["elapsed_ms"] for row in rows if "elapsed_ms" in row)
    return {
        "runs": len(rows), "successful_runs": successful,
        "success_rate": successful / len(rows) if rows else None,
        "http_attempts": attempts, "usage_complete": complete,
        "attempts_with_reported_usage": sum(
            call.get("prompt_tokens") is not None and call.get("completion_tokens") is not None
            for call in usage
        ),
        "reported_tokens": totals,
        "total_tokens": sum(totals.values()) if complete else None,
        "tokens_per_success": sum(totals.values()) / successful if complete and successful else None,
        "estimated_cost_krw": cost,
        "cost_per_success_krw": cost / successful if cost is not None and successful else None,
        "uncached_cost_krw": uncached_cost,
        "cache_usage_complete": cache_complete,
        "unpriced_models": sorted(unpriced_models),
        "cost_basis": "User-provided Elice Serverless KRW rates; cached input is counted once",
        "mean_latency_ms": mean(times) if times else None,
        "median_latency_ms": median(times) if times else None,
        # Nearest rank: with fewer than 20 timed runs, p95 is the maximum.
        "p95_latency_ms": times[math.ceil(0.95 * len(times)) - 1] if times else None,
        "max_latency_ms": max(times) if times else None,
        "transport_retries": sum(call.get("attempt", 1) > 1 for call in usage),
        "review_revise_count": None if any("review_results" not in row for row in rows) else sum(
            review.get("verdict") == "REVISE" for row in rows
            for review in row.get("review_results", [])
        ),
    }
