import pytest

from scripts.evaluation_metrics import load_prices, summarize_metrics


def trial(*, success=True, model="gpt-6.1-sol", cached=40):
    return {
        "status": "REVIEWED_PLAN" if success else "ERROR", "calls_by_role": {"all": 1},
        "provider_usage": [{"requested_model": model, "prompt_tokens": 100,
                            "completion_tokens": 20, "reasoning_tokens": 10,
                            "cached_prompt_tokens": cached}],
    }


def test_cache_and_reasoning_subsets_are_not_charged_twice_and_failures_are_included():
    report = summarize_metrics([trial(), trial(success=False)], {"gpt-6.1-sol": (2835, 141, 14175)})
    assert report["estimated_cost_krw"] == pytest.approx(0.91848)
    assert report["cost_per_success_krw"] == report["estimated_cost_krw"]
    assert report["total_tokens"] == 240 and report["successful_runs"] == 1


def test_missing_cache_or_model_price_is_unknown_instead_of_free():
    rates = {"gpt-6.1-sol": (2835, 141, 14175)}
    missing_cache = summarize_metrics([trial(cached=None)], rates)
    assert missing_cache["estimated_cost_krw"] is None
    assert missing_cache["uncached_cost_krw"] == pytest.approx(0.567)
    assert not missing_cache["cache_usage_complete"]
    invalid_cache = summarize_metrics([trial(cached=101)], rates)
    assert invalid_cache["estimated_cost_krw"] is None
    wrong_version = summarize_metrics([trial(model="gpt-5.6-luna")], {"gpt-6-luna": (141, 14, 708)})
    assert wrong_version["estimated_cost_krw"] is None
    assert wrong_version["unpriced_models"] == ["gpt-5.6-luna"]


def test_unrecorded_review_verdicts_are_unknown_instead_of_zero_rework():
    row = trial()
    assert summarize_metrics([row])["review_revise_count"] is None
    row["review_results"] = [{"verdict": "REVISE"}, {"verdict": "PASS"}]
    assert summarize_metrics([row])["review_revise_count"] == 1
    assert summarize_metrics([row, trial()])["review_revise_count"] is None


@pytest.mark.parametrize("reported", ["gpt-5.6-luna", "gpt-6.1-sol"])
def test_response_model_version_mismatch_never_uses_requested_price(reported):
    row = trial(model="gpt-6-luna")
    row["provider_usage"][0]["model"] = reported
    report = summarize_metrics([row], {
        "gpt-6-luna": (141, 14, 708), "gpt-6.1-sol": (2835, 141, 14175),
    })
    assert report["usage_complete"] and report["total_tokens"] == 120
    assert report["estimated_cost_krw"] is None
    assert report["uncached_cost_krw"] is None
    assert report["cost_per_success_krw"] is None


def test_provider_model_alias_preserves_the_same_price():
    row = trial(model="openai/gpt-6-luna")
    row["provider_usage"][0]["model"] = "gpt-6-luna"
    report = summarize_metrics([row], {"gpt-6-luna": (141, 14, 708)})
    assert report["estimated_cost_krw"] == pytest.approx(0.02318)


def test_price_aliases_match_only_the_same_model_and_currency(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LUNA6_PRICE_MODEL=openai/gpt-6-luna\nLUNA6_MODEL=gpt-6-luna\n"
                   "LUNA6_INPUT_KRW_PER_MILLION=141\nLUNA6_CACHED_INPUT_KRW_PER_MILLION=14\n"
                   "LUNA6_OUTPUT_KRW_PER_MILLION=708\n")
    prices = load_prices(env_file=env, environ={})
    assert prices == {"gpt-6-luna": (141, 14, 708)}
    assert summarize_metrics([trial(model="openai/gpt-6-luna")], prices)["estimated_cost_krw"] is not None
    env.write_text(env.read_text().replace("=708", "=-1"))
    with pytest.raises(SystemExit):
        load_prices(env_file=env, environ={})


@pytest.mark.parametrize(("times", "expected"), [
    ([], None), ([7], 7), ([30, 10], 30), (list(range(20, 0, -1)), 19),
])
def test_p95_uses_nearest_rank_for_all_timed_runs(times, expected):
    rows = [{**trial(success=index != 0), "elapsed_ms": value}
            for index, value in enumerate(times)]
    assert summarize_metrics(rows)["p95_latency_ms"] == expected


def test_wrong_dataset_answers_are_not_successes_but_their_cost_is_included():
    rows = [trial(), {**trial(), "score": {"result": "WRONG"}}, trial(success=False)]
    report = summarize_metrics(rows, {"gpt-6.1-sol": (2835, 141, 14175)})
    assert report["successful_runs"] == 1 and report["http_attempts"] == 3
    assert report["cost_per_success_krw"] == pytest.approx(1.37772)
    assert report["estimated_cost_krw"] == report["cost_per_success_krw"]


@pytest.mark.parametrize("missing", [None, "calls_by_role", "provider_usage"])
def test_zero_cost_requires_explicit_zero_call_telemetry(missing):
    row = {"status": "REVIEWED_PLAN", "calls_by_role": {}, "provider_usage": []}
    if missing:
        del row[missing]
    report = summarize_metrics([row])
    assert report["estimated_cost_krw"] == (None if missing else 0)
    assert report["total_tokens"] == (None if missing else 0)
    assert report["usage_complete"] is (missing is None)
    assert summarize_metrics([trial(), row])["usage_complete"] is (missing is None)
