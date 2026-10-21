"""Exercise the existing Case HTTP API and real Agent in disposable MySQL.

Run from the repository root with PYTHONPATH=backend. This never imports
app.main or uses its destructive development startup. No BE implementation is
replaced: only database connections are pointed at the new test container.
Reports contain status, counts and digests, never tokens or generated text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

import httpx
import jwt
from fastapi import FastAPI
from sqlmodel import Session, SQLModel, create_engine, select
from testcontainers.community.mysql import MySqlContainer

from app.agent.llm import LLMConfig
from scripts.evaluate_planning import (
    CASES,
    ROLE_BY_PREFIX,
    credentials_rejected,
    digest,
    evaluation_code_digest,
    expected_model_calls,
    recording_from_env,
    write_metadata,
)


def model_configuration() -> dict:
    configs = {
        role: LLMConfig.from_env(env_prefix=prefix)
        for prefix, role in ROLE_BY_PREFIX.items()
    }
    return {
        role: {"model": config.model, "reasoning_effort": config.reasoning_effort}
        for role, config in configs.items()
    }


def check_configuration(configured: dict) -> None:
    if set(configured) != set(ROLE_BY_PREFIX.values()) or not all(
        value == {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"}
        for value in configured.values()
    ):
        raise ValueError("API evaluation requires gpt-6.1-sol/xhigh for all roles")


def case_response_checks(payload: dict) -> dict[str, bool]:
    """Judge the existing response contract without reading generated prose."""
    status = payload.get("judgment_status")
    action = payload.get("next_action")
    return {
        "case_returned": payload.get("case") is not None,
        "judgment_finished": status in {"DONE", "NEEDS_MORE_INFO"},
        # The existing BE hides the saved Blocker while asking the user for
        # missing information. Its committed row is checked separately below.
        "blocker_matches_status": (
            bool(payload.get("blocker")) if status == "DONE"
            else status == "NEEDS_MORE_INFO" and payload.get("blocker") is None
        ),
        "next_step_present": (
            isinstance(action, dict) and bool(action.get("title")) and bool(action.get("reason"))
            if status == "DONE"
            else status == "NEEDS_MORE_INFO" and action is None
            and bool(payload.get("questions_for_user"))
        ),
        "no_unreported_changes": payload.get("changes") in (None, []),
    }


def stored_blocker_checks(history, *, case_id: int) -> dict[str, bool]:
    """Verify the committed priority Blocker belongs to this Case and judgment."""
    blocker = history.priority_blocker
    return {
        "stored_history_case_matches": history.case_id == case_id,
        "stored_priority_blocker_present": (
            blocker is not None and history.priority_blocker_id is not None
            and blocker.id == history.priority_blocker_id
        ),
        "stored_blocker_case_matches": blocker is not None and blocker.case_id == case_id,
        "stored_blocker_history_matches": (
            blocker is not None and history.id is not None
            and blocker.created_from_case_history_id == history.id
        ),
        "stored_blocker_description_present": blocker is not None and bool(blocker.description),
    }


async def exercise_api(
    engine, *, repeats: int, jwt_secret: str,
    on_trial: Callable[[dict], None] | None = None,
    on_calls: Callable[[list[dict]], None] | None = None,
) -> list[dict]:
    # Imports occur only after the caller installs the disposable DATABASE_URL.
    import app.agent.runtime as runtime_module
    from app.be import db
    from app.be.crud.member import create_member
    from app.be.models.case import Case
    from app.be.models.case_history import CaseHistory
    from app.be.models.evidence import DecisionRecord, Evidence
    from app.be.routers.case import router
    from app.be.services import first_judgment

    app = FastAPI()
    app.include_router(router)
    SQLModel.metadata.create_all(engine)
    rows = []
    calls = []
    with (
        patch.object(db, "_engine", engine),
        patch.object(first_judgment, "_engine", engine),
        patch.object(runtime_module.StructuredLLMClient, "from_env", recording_from_env(
            calls, (lambda: on_calls(calls)) if on_calls is not None else None,
        )),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://isolated-api.test",
        ) as client:
            for repeat in range(1, repeats + 1):
                with Session(engine) as session:
                    member = create_member(session, oauth_id=str(uuid4()), nickname="합성 평가 사용자")
                    member_id = member.id
                    session.commit()
                token = jwt.encode({
                    "sub": str(member_id), "token_type": "access",
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                }, jwt_secret, algorithm="HS256")
                headers = {"Access-Token": token}
                started = perf_counter()
                call_start = len(calls)
                created = await client.post("/cases", headers=headers, json=CASES["benchmark_case1"])
                row = {"repeat": repeat, "create_http_status": created.status_code}
                if created.status_code == 200:
                    current = await client.get("/cases", headers=headers)
                    row["read_http_status"] = current.status_code
                    row["poll_count"] = 1
                    if current.status_code == 200:
                        payload = current.json()
                        row["judgment_status"] = payload.get("judgment_status")
                        row["checks"] = case_response_checks(payload)
                        row["response_digest"] = digest(payload)
                        # A fresh session verifies committed storage rather than
                        # the objects held by the HTTP request's Session.
                        with Session(engine) as session:
                            case = session.exec(select(Case).where(Case.member_id == member_id)).one()
                            history = session.exec(select(CaseHistory).where(
                                CaseHistory.id == payload["case_history_id"]
                            )).one()
                            proofs = session.exec(select(DecisionRecord).where(
                                DecisionRecord.case_history_id == history.id
                            )).all()
                            sources = session.exec(select(Evidence).where(
                                Evidence.case_id == case.id,
                                Evidence.source_type == "OFFICIAL_DOCUMENT",
                            )).all()
                            row["checks"].update({
                                "stored_response_case_matches": payload["case"]["id"] == case.id,
                                "stored_status_matches": history.judgment_status == row["judgment_status"],
                                "review_proof_saved": len(proofs) == 1 and proofs[0].verdict == "PASS",
                                "official_sources_saved": bool(sources),
                                "unknown_scope_preserved": case.restoration_scope == "UNKNOWN",
                                "unknown_demolition_preserved": case.demolition_required == "UNKNOWN",
                            })
                            row["checks"].update(stored_blocker_checks(history, case_id=case.id))
                            row["stored_failure"] = {
                                "failure_code": history.failure_code,
                                "recovery_action_code": history.recovery_action_code,
                                "retryable": history.retryable,
                                "requested_field_paths": history.requested_field_paths,
                            }
                row["calls"] = list(calls[call_start:])
                if row.get("checks"):
                    successful = {
                        call.get("schema_name") for call in row["calls"]
                        if call.get("http_status") == 200
                    }
                    row["checks"]["real_components_called"] = {
                        "ContentSafetyDecision", "reborn_info_analysis",
                        "reborn_supervisor_draft", "reborn_review_output",
                    }.issubset(successful)
                    row["checks"]["expected_models_called"] = expected_model_calls(row["calls"])
                row["elapsed_ms"] = round((perf_counter() - started) * 1000)
                row["verdict"] = (
                    "PASS" if row.get("checks") and all(row["checks"].values()) else "FAIL"
                )
                rows.append(row)
                if on_trial is not None:
                    on_trial(row)
                print(json.dumps({key: row.get(key) for key in (
                    "repeat", "create_http_status", "judgment_status", "verdict", "elapsed_ms",
                )}), flush=True)
                if credentials_rejected(row["calls"]):
                    break
    return rows


def run(args) -> dict:
    configured = model_configuration()
    check_configuration(configured)
    manifest = {
        "code_digest": evaluation_code_digest(),
        "configured": configured, "repeats": args.repeats,
        "transport": "ASGI; existing background task completes before the in-process response returns",
        "scope": "existing POST /cases -> GET /cases -> new database Session read",
        "limitations": [
            "Result submission and conflict confirmation are not implemented by this harness.",
            "No FE, OAuth provider, deployed network or production database is tested.",
            "Existing BE data supply is used; new Agent integration is a separate BE request.",
        ],
    }
    if args.validate_only:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return manifest
    args.output.mkdir(parents=True, exist_ok=False)
    write_metadata(args.output / "manifest.json", manifest)
    completed_rows = []

    def save_trial(row):
        completed_rows.append(row)
        write_metadata(args.output / f"trial-{len(completed_rows):03d}.json", row)
        write_metadata(args.output / "results.json", {
            **manifest, "verdict": "INCOMPLETE", "trials": completed_rows,
        })

    write_metadata(args.output / "results.json", {
        **manifest, "verdict": "INCOMPLETE", "trials": [],
    })
    with MySqlContainer(
        "mysql:8.0", dialect="pymysql", username="test", password="test",
        root_password="test", dbname="agent_api_evaluation",
    ).with_env("TZ", "Asia/Seoul") as container:
        database_url = container.get_connection_url() + "?charset=utf8mb4"
        secret = uuid4().hex + uuid4().hex
        with patch.dict(os.environ, {
            "DATABASE_URL": database_url, "ENVIRONMENT": "prod",
            "KAKAO_CLIENT_ID": "synthetic", "KAKAO_CLIENT_SECRET": "synthetic",
            "KAKAO_REDIRECT_URI": "http://isolated-api.test/callback", "JWT_SECRET_KEY": secret,
        }):
            from app.common.config import get_settings

            get_settings.cache_clear()
            engine = create_engine(database_url)
            try:
                rows = asyncio.run(exercise_api(
                    engine, repeats=args.repeats, jwt_secret=secret, on_trial=save_trial,
                    on_calls=lambda calls: write_metadata(args.output / "calls.json", {"calls": calls}),
                ))
            finally:
                engine.dispose()
                get_settings.cache_clear()
    code_unchanged = evaluation_code_digest() == manifest["code_digest"]
    report = {
        "code_unchanged": code_unchanged,
        **manifest, "trials": rows,
        "verdict": "PASS" if code_unchanged and len(rows) == args.repeats
        and rows and all(row["verdict"] == "PASS" for row in rows) else "FAIL",
    }
    write_metadata(args.output / "results.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    # BE exceptions can include submitted values; keep the terminal/report to
    # the metadata above, even if its existing background task fails.
    logging.disable(logging.CRITICAL)
    try:
        result = run(parser.parse_args())
    except Exception as exc:  # noqa: BLE001 - exception bodies may contain submitted values
        print(json.dumps({"verdict": "ERROR", "error_type": type(exc).__name__,
                          "error_code": getattr(exc, "code", None)}))
        raise SystemExit(1) from None
    raise SystemExit(0 if result.get("verdict", "PASS") == "PASS" else 1)
