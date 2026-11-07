from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from scripts.monitor_agent import fetch_observations, provider_usage, summarize

RATES = {"gpt-6-luna": (141, 14, 708)}


def generation(**metadata):
    return {
        "id": "generation-1", "traceId": "synthetic-trace", "parentObservationId": "info",
        "type": "GENERATION", "name": "LLM", "model": "gpt-6-luna", "level": "DEFAULT",
        "usageDetails": {"input": 60, "input_cached": 40, "output": 10, "output_reasoning": 10},
        "metadata": {"schema_name": "reborn_info_analysis", "reasoning_effort": "high",
                     "attempt": 1, "status": "SUCCESS", "latency_ms": 200, **metadata},
    }


def test_generations_are_charged_once_and_grouped_separately_from_run_results():
    parent = {"id": "info", "name": "INFO_AGENT", "type": "SPAN"}
    root = {"id": "root", "traceId": "synthetic-trace", "name": "RUN", "type": "SPAN",
            "metadata": {"component": "RUN", "provider_calls": 99, "prompt_tokens": 999,
                         "outcome_type": "SAFE_FAILURE", "review_revise_count": 2}}
    row = generation()
    report = summarize([root, parent, row, deepcopy(row)], RATES)
    assert report["totals"]["http_attempts"] == 1
    assert report["totals"]["total_tokens"] == 120
    assert report["totals"]["estimated_cost_krw"] == pytest.approx(0.02318)
    assert report["by_component_model_effort"][0]["component"] == "INFO_AGENT"
    assert report["outcomes"] == {"SAFE_FAILURE": 1}
    assert report["review_revise_count"] == 2
    assert "successful_runs" not in report["totals"]


def test_error_retry_and_unknown_usage_remain_visible_without_free_cost():
    failed = generation(status="ERROR", attempt=1, error_code="HTTP_503", usage_complete=False,
                        prompt_tokens=None, completion_tokens=None, cached_prompt_tokens=None)
    failed["level"] = "ERROR"
    succeeded = generation(attempt=2)
    succeeded["id"] = "generation-2"
    report = summarize([failed, succeeded], RATES)
    totals = report["totals"]
    assert totals["http_attempts"] == 2 and totals["transport_retries"] == 1
    assert totals["failed_http_attempts"] == totals["successful_http_attempts"] == 1
    assert totals["total_tokens"] is None and totals["estimated_cost_krw"] is None
    assert totals["unknown_usage_attempts"] == totals["unknown_cost_attempts"] == 1
    assert totals["priced_cost_subtotal_krw"] == pytest.approx(0.02318)
    assert totals["error_codes"] == {"HTTP_503": 1}
    assert report["review_revise_count"] is None


def test_metadata_preserves_raw_totals_and_does_not_count_cache_or_reasoning_twice():
    row = generation(prompt_tokens=100, completion_tokens=20, cached_prompt_tokens=40,
                     reasoning_tokens=10, requested_model="gpt-6-luna", component="SUPERVISOR")
    row["usageDetails"] = {"input": 999, "output": 999}
    assert provider_usage(row)["prompt_tokens"] == 100
    report = summarize([row], RATES)
    assert report["totals"]["total_tokens"] == 120
    assert report["by_component_model_effort"][0]["component"] == "SUPERVISOR"


def test_unrelated_observations_are_excluded_and_unknown_review_is_not_zero():
    other = generation()
    other["metadata"]["schema_name"] = "different-application"
    root = {"id": "root", "traceId": "synthetic-trace", "name": "RUN", "type": "SPAN",
            "metadata": {"component": "RUN", "outcome_type": "REVIEWED_PLAN"}}
    report = summarize([other, root], RATES)
    assert report["totals"]["http_attempts"] == 0
    assert report["review_revise_count"] is None


def test_support_schema_is_charged_with_its_original_name():
    row = generation(schema_name="support_analysis", component="SUPPORT_AGENT")
    report = summarize([row, deepcopy(row)], RATES)
    assert report["totals"]["http_attempts"] == 1
    assert report["totals"]["total_tokens"] == 120
    assert report["totals"]["estimated_cost_krw"] == pytest.approx(0.02318)
    assert report["by_component_model_effort"][0]["component"] == "SUPPORT_AGENT"


@pytest.mark.parametrize("maximum,truncated,requests", [(1, True, 1), (2, False, 2)])
def test_pagination_fetches_no_io_and_marks_partial_reports(maximum, truncated, requests):
    api = SimpleNamespace(get_many=Mock(side_effect=[
        SimpleNamespace(model_dump=lambda **_: {"data": [{"id": "one"}], "meta": {"cursor": "next"}}),
        SimpleNamespace(model_dump=lambda **_: {"data": [{"id": "two"}], "meta": {"cursor": None}}),
    ]))
    rows, partial = fetch_observations(api, start="start", end="end", trace_id="trace", maximum=maximum)
    assert len(rows) == maximum and partial is truncated
    assert api.get_many.call_count == requests
    for call in api.get_many.call_args_list:
        assert "io" not in call.kwargs["fields"].split(",")
        assert call.kwargs["from_start_time"] == "start"
        assert call.kwargs["to_start_time"] == "end"
        assert call.kwargs["trace_id"] == "trace"


def test_repeated_cursor_stops_instead_of_fetching_forever():
    api = SimpleNamespace(get_many=Mock(return_value=SimpleNamespace(
        model_dump=lambda **_: {"data": [], "meta": {"cursor": "repeated"}},
    )))
    with pytest.raises(ValueError, match="repeated cursor"):
        fetch_observations(api, start="start", end="end")
    assert api.get_many.call_count == 2
