"""Read metadata-only Langfuse observations and report Agent usage and KRW estimates."""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent.tracing import LangfuseTraceSink
from scripts.evaluation_metrics import load_prices, summarize_metrics, write_metadata


def fetch_observations(api, *, start, end, trace_id=None, maximum=5000):
    rows, cursor = [], None
    seen = set()
    while len(rows) < maximum:
        page = api.get_many(
            fields="core,basic,model,usage,metadata", from_start_time=start,
            # Otherwise Langfuse returns issue lists over 200 chars as truncated strings.
            expand_metadata="review_issues",
            to_start_time=end, trace_id=trace_id, limit=min(1000, maximum - len(rows)),
            cursor=cursor,
        ).model_dump(mode="json")
        rows.extend(page["data"])
        cursor = (page.get("meta") or {}).get("cursor")
        if not cursor:
            break
        if cursor in seen:
            raise ValueError("Langfuse returned a repeated cursor")
        seen.add(cursor)
    return rows, bool(cursor)


def provider_usage(row):
    metadata, details = row.get("metadata") or {}, row.get("usageDetails") or {}

    def tokens(key, base, subset):
        if key in metadata:
            return metadata[key]
        if metadata.get("usage_complete") is False or base not in details:
            return None
        return details[base] + details.get(subset, 0)

    return {
        "model": row.get("model"), "requested_model": metadata.get("requested_model") or row.get("model"),
        "prompt_tokens": tokens("prompt_tokens", "input", "input_cached"),
        "completion_tokens": tokens("completion_tokens", "output", "output_reasoning"),
        "cached_prompt_tokens": metadata.get("cached_prompt_tokens", details.get("input_cached")),
        "reasoning_tokens": metadata.get("reasoning_tokens", details.get("output_reasoning")),
        "attempt": metadata.get("attempt", 1), "status": metadata.get("status"),
        "error_code": metadata.get("error_code"), "latency_ms": metadata.get("latency_ms"),
    }


def summarize(observations, prices):
    by_id = {row["id"]: row for row in observations}
    groups, attempts, runs = defaultdict(list), [], []
    for row in by_id.values():
        metadata = row.get("metadata") or {}
        if row.get("name") == "RUN" and metadata.get("component") == "RUN":
            runs.append({
                "trace_id": row["traceId"],
                **{key: metadata.get(key) for key in (
                    "run_id", "status", "outcome_type", "latency_ms", "provider_calls",
                    "review_count", "review_revise_count", "rework_count", "error_code",
                )},
            })
        schema = metadata.get("schema_name") or ""
        if row.get("type") != "GENERATION" or not (
            schema.startswith("reborn_") or schema in {"ContentSafetyDecision", "support_analysis"}
        ):
            continue
        parent = by_id.get(row.get("parentObservationId"), {})
        component = metadata.get("component") or parent.get("name") or schema
        usage = provider_usage(row)
        attempt = {
            "status": "ERROR" if row.get("level") == "ERROR" or usage["status"] == "ERROR" else "REVIEWED_PLAN",
            "provider_usage": [usage], "calls_by_role": {component: 1},
            **({"elapsed_ms": usage["latency_ms"]} if usage["latency_ms"] is not None else {}),
        }
        groups[(component, usage["model"], metadata.get("reasoning_effort"))].append(attempt)
        attempts.append(attempt)

    def metrics(rows):
        result = summarize_metrics(rows, prices)
        # Each row here is an HTTP attempt, not a completed Agent task.
        for key in ("runs", "successful_runs", "success_rate", "tokens_per_success", "cost_per_success_krw", "review_revise_count"):
            result.pop(key)
        costs = [summarize_metrics([row], prices)["estimated_cost_krw"] for row in rows]
        result.update(
            successful_http_attempts=sum(row["status"] != "ERROR" for row in rows),
            failed_http_attempts=sum(row["status"] == "ERROR" for row in rows),
            unknown_usage_attempts=len(rows) - result["attempts_with_reported_usage"],
            priced_cost_subtotal_krw=sum(cost for cost in costs if cost is not None),
            unknown_cost_attempts=sum(cost is None for cost in costs),
            error_codes=dict(Counter(row["provider_usage"][0]["error_code"] for row in rows if row["provider_usage"][0]["error_code"])),
        )
        return result

    return {
        "totals": metrics(attempts),
        "by_component_model_effort": [
            {"component": key[0], "model": key[1], "effort": key[2], **metrics(rows)}
            for key, rows in sorted(groups.items(), key=lambda item: tuple(str(v) for v in item[0]))
        ],
        "agent_runs": runs,
        "outcomes": dict(Counter(row["outcome_type"] or "UNKNOWN" for row in runs)),
        "review_revise_count": (
            sum(row["review_revise_count"] for row in runs)
            if runs and all(row["review_revise_count"] is not None for row in runs) else None
        ),
        "scope": "Only recorded Agent HTTP generations in the selected window; RUN totals are not charged again. KRW uses configured user-provided rates, not Langfuse USD costs or an invoice.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--trace-id")
    parser.add_argument("--max-observations", type=int, default=5000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.hours <= 168 or not 1 <= args.max_observations <= 10000:
        parser.error("hours must be 0..168 and max-observations 1..10000")
    if args.output.exists():
        parser.error("output already exists; choose a new file")
    sink = LangfuseTraceSink.from_env()
    if sink is None:
        parser.error("Langfuse credentials or SDK are unavailable; check .env")
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=args.hours)
    try:
        observations, truncated = fetch_observations(
            sink._client.api.observations, start=start, end=end,
            trace_id=args.trace_id, maximum=args.max_observations,
        )
    except Exception as exc:  # noqa: BLE001 - never print credentials or service bodies
        raise SystemExit(f"Langfuse query failed: {type(exc).__name__}; status={getattr(exc, 'status_code', None)}") from None
    result = {
        "from_utc": start.isoformat(), "to_utc": end.isoformat(),
        "trace_id": args.trace_id, "fetched_observations": len(observations),
        "truncated": truncated, **summarize(observations, load_prices()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_metadata(args.output, result)
    print(json.dumps({key: result[key] for key in ("fetched_observations", "truncated", "totals", "outcomes")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
