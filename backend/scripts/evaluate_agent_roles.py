"""Real calls for existing Agent/Tool contracts, using clearly synthetic inputs."""

import argparse
import asyncio
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.agent.info_agent import InfoAnalysisAgent
from app.agent.llm import (
    LLMCallBudget,
    LLMConfig,
    ScopedCallBudget,
    StructuredLLMClient,
    call_budget_scope,
)
from app.agent.review_tool import ReviewTool
from app.agent.review_tool.models import ReviewProviderOutput
from app.agent.run_scope import RunDeadline, run_deadline_scope
from app.agent.schemas import (
    DiscoverSupportInput,
    InfoAnalysisInput,
    ReviewSubject,
    SupervisorAgentInput,
    canonical_digest,
)
from app.agent.supervisor import SupervisorAgent
from app.agent.support_agent import ReviewedSupportCatalog, SupportAgent
from app.agent.tracing import LangfuseTraceSink, capture_usage, observation_scope
from scripts.evaluation_metrics import (
    evaluate_efforts,
    evaluation_code_digest,
    load_prices,
    summarize_metrics,
    write_metadata,
)


def decision_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def agent_code_digest():
    root = Path(__file__).resolve().parents[1] / "app/agent"
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def baseline_row(checkpoint, dataset, case, repeat, config):
    request = SupervisorAgentInput.model_validate(dataset["supervisor_cases"][case])
    if canonical_digest(request) != checkpoint["case_input_digests"].get(case):
        return None
    for row in checkpoint["rows"]:
        if (row["case"] == case and row["repeat"] == repeat and row["passed"]
                and row["model"] == config.model and row["effort"] == config.reasoning_effort):
            copied = deepcopy(row)
            copied["reused_from_report_sha256"] = checkpoint["original_report_sha256"]
            return copied
    return None


async def record_review(subject, client, row):
    """합성 평가에서 같은 초안의 모델 판단·코드 검사·최종 결과를 나눠 저장한다."""
    row["review_subject"] = subject.model_dump(mode="json")
    row["model_review_outputs"] = []
    # 가짜 PASS에도 남는 문제는 코드 검사에서 찾은 것이다. 실제 모델 호출·사용량 기록은 없다.
    code_client = SimpleNamespace(generate=AsyncMock(return_value=ReviewProviderOutput(
        verdict="PASS", issues=[], missing_evidence=[], recommended_rework_targets=[],
        resolution_reason="합성 평가에서 코드 검사만 확인하기 위한 가짜 PASS",
    )))
    code_result = await ReviewTool(code_client).review(subject)
    row["code_review_result"] = code_result.model_dump(mode="json")

    async def generate(*args, **kwargs):
        output = await client.generate(*args, **kwargs)
        row["model_review_outputs"].append(output.model_dump(mode="json"))
        return output

    result = await ReviewTool(SimpleNamespace(generate=generate)).review(subject)
    # 기대 판정과의 비교가 실패해도 반려 상세와 원래 검수 대상을 잃지 않는다.
    row["result"] = result.model_dump(mode="json")
    row["review_results"].append({"verdict": result.verdict.value})
    return result


async def trial(dataset, case, config, prices, expected=None):
    clients = [StructuredLLMClient(value, call_budget=ScopedCallBudget())
               for value in (config, LLMConfig.from_env())]
    primary, reviewer = clients
    sink = LangfuseTraceSink.from_env()
    row = {"case": case, "model": config.model, "effort": config.reasoning_effort, "review_results": []}
    started = perf_counter()
    with capture_usage() as usage:
        try:
            with (call_budget_scope(LLMCallBudget(40)), run_deadline_scope(RunDeadline.after(180)),
                  observation_scope("AGENT_ROLE_VALIDATION", sink=sink, as_type="span")):
                if case == "info":
                    request = InfoAnalysisInput.model_validate(dataset["info_input"])
                    original = request.model_dump_json()
                    with observation_scope("INFO_AGENT", as_type="span"):
                        result = await InfoAnalysisAgent(primary).analyze(request)
                    values = {f.field_path.value: f.value for f in result.fact_candidates}
                    conflicts = {f.field_path.value: f.proposed_value for f in result.conflicts}
                    row.update(fact_fields=sorted(values), conflict_fields=sorted(conflicts),
                               result=result.model_dump(mode="json"))
                    if expected is None:
                        assert "restoration_scope" not in values and "restoration_scope" in conflicts
                        values.update(conflicts)
                        assert values.get("restoration_scope") == "PARTIAL"
                        assert values.get("demolition_required") == "REQUIRED"
                    else:
                        row["checks"] = {"facts_exact": values == expected["facts"],
                                         "conflicts_exact": conflicts == expected["conflicts"]}
                    row.setdefault("checks", {})["input_unchanged"] = request.model_dump_json() == original
                    assert all(row["checks"].values())
                elif case == "support":
                    request = DiscoverSupportInput.model_validate(dataset["support_input"])
                    catalog = ReviewedSupportCatalog.model_validate(dataset["support_catalog"])
                    original = request.model_dump_json(), catalog.model_dump_json()
                    with observation_scope("SUPPORT_AGENT", as_type="span"):
                        result = await SupportAgent(primary, catalog).analyze(request)
                    row["result"] = result.model_dump(mode="json")
                    if expected is None:
                        assert len(result.support_checks) == 1
                        assert result.support_checks[0].match_status == "NEEDS_CONFIRMATION"
                        row["support_match_status"] = result.support_checks[0].match_status.value
                    else:
                        row["checks"] = {
                            "match_statuses": [c.match_status.value for c in result.support_checks]
                            in expected["match_statuses"],
                            "criteria_exact": [[c.status.value for c in check.criteria]
                                               for check in result.support_checks] == expected["criteria"],
                            "completion": result.completion_status.value in expected["completion"],
                            "input_unchanged": original == (request.model_dump_json(), catalog.model_dump_json()),
                        }
                        assert all(row["checks"].values())
                elif case == "review":
                    subject = ReviewSubject.model_validate(dataset["review_subject"])
                    original = subject.model_dump_json()
                    with observation_scope("REVIEW_TOOL", as_type="span"):
                        result = await record_review(subject, reviewer, row)
                    row["checks"] = {"verdict": result.verdict.value == expected["verdict"],
                                     "input_unchanged": subject.model_dump_json() == original}
                    if expected["verdict"] == "REVISE":
                        row["checks"]["blocking_issue"] = any(i.severity == "BLOCKING" for i in result.issues)
                    assert all(row["checks"].values())
                else:
                    request = SupervisorAgentInput.model_validate(dataset["supervisor_cases"][case])
                    original = request.model_dump_json()
                    with observation_scope("SUPERVISOR", as_type="span"):
                        draft = await SupervisorAgent(primary).draft(request)
                    row["supervisor_draft"] = draft.model_dump(mode="json")
                    meta = request.source_results[0].meta
                    subject = ReviewSubject.create(
                        schema_version="agent-io/2.0", review_subject_id=uuid4(), review_attempt=1,
                        run_id=meta.run_id, case_id=meta.case_id, trigger=request.trigger,
                        snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
                        source_results=request.source_results, supervisor_draft=draft,
                    )
                    with observation_scope("REVIEW_TOOL", as_type="span"):
                        reviewed = await record_review(subject, reviewer, row)
                    decision = draft.decision.model_dump(mode="json")
                    action = decision.get("next_action")
                    code = action["action_code"] if action else None
                    row["decision_signature"] = {
                        "decision_type": decision["decision_type"], "action_code": code,
                        "questions": decision.get("questions_for_user", []),
                    }
                    row["checks"] = {"review_passed": reviewed.verdict == "PASS",
                                     "expected_action": code == dataset["expected_actions"][case],
                                     "input_unchanged": request.model_dump_json() == original}
                    assert all(row["checks"].values())
                row["passed"] = True
        except Exception as exc:  # noqa: BLE001 - save error types, never exception messages/provider bodies
            row.update(passed=False, error_type=type(exc).__name__, error_code=getattr(exc, "code", None))
            if hasattr(exc, "fact_errors"):
                row["fact_errors"] = list(exc.fact_errors)
        finally:
            await asyncio.gather(*(client.aclose() for client in clients))
            if sink is not None:
                sink.flush()
    row.update(elapsed_ms=round((perf_counter() - started) * 1000),
               provider_usage=[asdict(item) for item in usage], calls_by_role={"all": len(usage)})
    row["status"] = "REVIEWED_PLAN" if row["passed"] else "ERROR"
    row["metrics"] = summarize_metrics([row], prices)
    return row


async def accuracy_suite(args, dataset):
    """Run fixed synthetic oracles at current settings, without effort tuning."""
    prices = load_prices()
    report = {"synthetic_data": True, "scope": "Current Info/Support/Supervisor/Review contracts",
              "agent_code_digest": agent_code_digest(), "code_digest": evaluation_code_digest(),
              "input_sha256": hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
              "prices_krw_per_million": prices, "trials": []}
    cases = dataset["accuracy_cases"]
    # Validate all fixtures before the first paid call.
    for case in cases:
        if case["role"] == "info":
            InfoAnalysisInput.model_validate(case["request"])
        elif case["role"] == "support":
            DiscoverSupportInput.model_validate(case["request"])
            ReviewedSupportCatalog.model_validate(case["catalog"])
        elif case["role"] == "review":
            if "request" in case:
                if "changes" in case:
                    raise ValueError("Fixed Review requests cannot also include changes")
                ReviewSubject.model_validate(case["request"])
            if case.get("expected", {}).get("verdict") not in {"PASS", "REVISE"}:
                raise ValueError("Review cases require expected verdict PASS or REVISE")
        else:
            SupervisorAgentInput.model_validate(dataset["supervisor_cases"][case["role"]])
    if args.validate_only:
        print(json.dumps({"validated_cases": len(cases), "model_calls": 0}))
        return
    for repeat in range(1, args.repeats + 1):
        seed = None
        for case in cases:
            role, data = case["role"], dict(dataset)
            if role in {"info", "support"}:
                data[role + "_input"] = case["request"]
            if role == "support":
                data["support_catalog"] = case["catalog"]
            if role == "review" and "request" in case:
                data["review_subject"] = case["request"]
            elif role == "review":
                if seed is None:
                    raise ValueError("Review cases require a preceding Supervisor trial")
                request = SupervisorAgentInput.model_validate(data["supervisor_cases"]["scope_unknown"])
                draft = deepcopy(seed)
                for field, value in case["changes"].items():
                    draft["decision"]["next_action"][field] = value
                    for claim in draft["grounded_claims"]:
                        if claim["target_path"] == "/supervisor_draft/decision/next_action/" + field:
                            claim["text"] = value
                meta = request.source_results[0].meta
                data["review_subject"] = ReviewSubject.create(
                    schema_version="agent-io/2.0", review_subject_id=uuid4(), review_attempt=1,
                    run_id=meta.run_id, case_id=meta.case_id, trigger=request.trigger,
                    snapshot=request.case_snapshot, known_procedure_steps=request.known_procedure_steps,
                    source_results=request.source_results, supervisor_draft=draft,
                ).model_dump(mode="json")
            prefix = "INFO_" if role == "info" else "SUPERVISOR_" if role in data.get("supervisor_cases", {}) else ""
            config = LLMConfig.from_env(env_prefix=prefix)
            row = await trial(data, role, config, prices, case.get("expected"))
            if role == "scope_unknown" and row.get("supervisor_draft"):
                seed = row["supervisor_draft"]
            row.update(case_id=case["name"], repeat=repeat)
            report["trials"].append(row)
            report["metrics"] = summarize_metrics(report["trials"], prices)
            report["passed"] = all(r["passed"] for r in report["trials"])
            report["code_unchanged"] = evaluation_code_digest() == report["code_digest"]
            write_metadata(args.output / "results.json", report)
            print(json.dumps({k: row.get(k) for k in ("case_id", "repeat", "passed", "checks", "error_type")}), flush=True)
            if any(u.get("status_code") in {401, 403} for u in row["provider_usage"]):
                raise SystemExit("Provider rejected credentials; remaining trials stopped")
    if not report["passed"] or not report["code_unchanged"]:
        raise SystemExit(1)


async def run(args):
    if args.validate_only and not args.accuracy:
        raise SystemExit("--validate-only requires --accuracy")
    args.output.mkdir(parents=True, exist_ok=False)
    raw = args.inputs.read_bytes()
    dataset = json.loads(raw)
    assert dataset["synthetic_data"] is True
    if args.accuracy:
        await accuracy_suite(args, dataset)
        return
    prices, digest = load_prices(), evaluation_code_digest()
    baseline_config = LLMConfig.from_env()
    checkpoint = json.loads(args.baseline_checkpoint.read_bytes()) if args.baseline_checkpoint else None
    if checkpoint is not None and checkpoint["agent_code_digest"] != agent_code_digest():
        raise SystemExit("Agent code changed; prior baseline cannot be reused")
    report = {"synthetic_data": True, "scope": "Existing components; no simulated LLM responses",
              "code_digest": digest, "input_sha256": hashlib.sha256(raw).hexdigest(),
              "prices_krw_per_million": prices, "trials": [], "groups": {}}

    async def evaluate(label, config, cases, repeats):
        rows = []
        for repeat in range(1, repeats + 1):
            for case in cases:
                row = (baseline_row(checkpoint, dataset, case, repeat, config)
                       if checkpoint is not None and label == "baseline" else None)
                if row is None:
                    row = await trial(dataset, case, config, prices)
                row.update(configuration=label, repeat=repeat)
                rows.append(row)
                report["trials"].append(row)
                write_metadata(args.output / "results.json", report)
                print(json.dumps({key: row.get(key) for key in
                                  ("configuration", "case", "repeat", "passed", "error_type",
                                   "reused_from_report_sha256")}), flush=True)
                if any(item.get("status_code") in {401, 403} for item in row["provider_usage"]):
                    raise SystemExit("Provider rejected credentials; remaining trials stopped")
        metrics = summarize_metrics(rows, prices)
        group = {"passed": all(row["passed"] for row in rows), "metrics": metrics}
        report["groups"][label] = group
        write_metadata(args.output / "results.json", report)
        return group

    if args.pilot:
        await evaluate("baseline-pilot", baseline_config, ["scope_unknown"], 1)
    elif args.compare_supervisor:
        cases = list(dataset["supervisor_cases"])
        baseline = await evaluate("baseline", baseline_config, cases, 3)
        expected = {case: {decision_digest(row.get("decision_signature"))
                           for row in report["trials"] if row["case"] == case}
                    for case in cases}
        baseline["passed"] = baseline["passed"] and all(len(value) == 1 for value in expected.values())
        if not baseline["passed"]:
            report.update(passed=False, code_unchanged=evaluation_code_digest() == digest)
            write_metadata(args.output / "results.json", report)
            raise SystemExit("Baseline contract or behavior failed; comparisons stopped")
        candidates = []
        configurations = []
        for prefix, base in [("SUPERVISOR_", baseline_config),
                             ("LUNA6_", LLMConfig.from_env(env_prefix="LUNA6_", inherit_shared=False))]:
            for effort in ("high", "medium", "low"):
                label = ("sol" if prefix == "SUPERVISOR_" else "luna6") + "-" + effort
                config = replace(base, reasoning_effort=effort)
                configurations.append((label, prefix, config))

        async def screen(label, config, repeats):
            return await evaluate(label, config, ["scope_unknown"], repeats)

        async for label, prefix, config, group in evaluate_efforts(configurations, screen):
            if group is None:
                report.setdefault("skipped_configurations", []).append(label)
                continue
            if group["passed"] and group["metrics"]["usage_complete"]:
                candidates.append((label, prefix, config))
        report["selected_supervisor_config"] = None
        if candidates and baseline["passed"]:
            report["selection_metric"] = "uncached_cost_per_success_krw"
            best = min(candidates, key=lambda item: (
                report["groups"][item[0]]["metrics"]["uncached_cost_krw"]
                / report["groups"][item[0]]["metrics"]["successful_runs"],
                report["groups"][item[0]]["metrics"]["mean_latency_ms"],
            ))
            label, prefix, config = best
            finalist = await evaluate("final-" + label, config, cases, 3)
            rows = [row for row in report["trials"] if row["configuration"] == "final-" + label]
            finalist["passed"] = finalist["passed"] and all(
                decision_digest(row.get("decision_signature")) in expected[row["case"]] for row in rows
            )
            if (finalist["passed"] and finalist["metrics"]["usage_complete"]
                    and all(finalist["metrics"][key] < baseline["metrics"][key]
                            for key in ("cost_per_success_krw", "mean_latency_ms"))):
                report["selected_supervisor_config"] = {
                    "prefix": prefix, "model": config.model, "effort": config.reasoning_effort,
                }
    else:
        await evaluate("existing-info", LLMConfig.from_env(env_prefix="INFO_"), ["info"], 1)
        await evaluate("existing-support", baseline_config, ["support"], 1)
    report["code_unchanged"] = evaluation_code_digest() == digest
    report["new_call_metrics"] = summarize_metrics(
        [row for row in report["trials"] if "reused_from_report_sha256" not in row], prices,
    )
    report["passed"] = report["code_unchanged"] and all(group["passed"] for group in report["groups"].values())
    if args.compare_supervisor:
        report["passed"] = report["code_unchanged"] and report["selected_supervisor_config"] is not None
    write_metadata(args.output / "results.json", report)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-checkpoint", type=Path)
    parser.add_argument("--inputs", type=Path, default=Path(__file__).resolve().parents[2]
                        / "docs/agent/evaluations/2026-11-01-agent-role-inputs.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pilot", action="store_true")
    mode.add_argument("--compare-supervisor", action="store_true")
    mode.add_argument("--accuracy", action="store_true")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--validate-only", action="store_true")
    asyncio.run(run(parser.parse_args()))
