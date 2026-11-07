"""Export public documentation contracts without starting the app or calling a model.

Run from backend: python scripts/export_documentation.py [--check].
Only OpenAPI, reviewed task definitions and source hashes are exported; never env or user data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402
from app.agent.roadmap import STAGES, TASKS  # noqa: E402
from app.be.schemas import auth, case, document  # noqa: E402

DEST = ROOT / "docs/developers/generated/contracts.json"

EXAMPLES = {
    "LoginRequest": {"code": "KAKAO_AUTHORIZATION_CODE"},
    "CaseCreateRequest": {
        "business_type": "CAFE", "franchise_status": False, "lease_status": "LEASED_PAID",
        "restoration_clause": "EXISTS", "employee_count": 0, "had_employees": False,
        "pension_enrolled": False, "health_insurance_enrolled": False,
        "employment_insurance_enrolled": False, "industrial_accident_insurance_enrolled": False,
        "has_business_loan": False, "has_service_contracts": False,
    },
    "CaseResultsSubmitRequest": {
        "case_history_id": 12,
        "restoration_answer": {"restoration_scope": "PARTIAL", "demolition_required": "REQUIRED"},
    },
    "CaseConflictsDecisionRequest": {"decisions": [{"conflict_reference_id": 1, "side": "PROPOSED"}]},
    "CaseChecklistUpdateRequest": {"completed": True},
    "CaseSupportApprovalRequest": {"approved": None},
    "CaseClosureReportRequest": {
        "closure_date": "2026-11-07", "closure_reason": "PERSONAL",
        "road_address": "강원특별자치도 춘천시 강원대학길 1", "address_detail": "예시 주소",
    },
    "CaseDepositReturnRequest": {"result": "PARTIAL"},
    "DocumentConfirmRequest": {"kind": "BEFORE_PHOTO", "confirmed_fields": {}},
    "DocumentCheckRequest": {"applicant_name": "예시 신청인", "closure_date": "2026-11-07"},
}


def sources() -> dict[str, str]:
    paths = []
    for base, suffixes in [(ROOT / "backend/app", {".py", ".json"}),
                           (ROOT / "backend/sql", {".sql"}),
                           (ROOT / "frontend/src", {".ts", ".tsx", ".css"})]:
        paths.extend(p for p in base.rglob("*") if p.suffix in suffixes
                     and ".test." not in p.name and "__pycache__" not in p.parts)
    paths.extend(ROOT / name for name in ["frontend/package.json", "backend/requirements.txt",
                                        "docker-compose.prod.yml", "frontend/vercel.json",
                                        "frontend/vite.config.ts"])
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def payload() -> dict:
    for name, value in EXAMPLES.items():
        model = next(getattr(module, name) for module in (auth, case, document) if hasattr(module, name))
        model.model_validate(value)
    return {
        "openapi": app.openapi(), "request_examples": EXAMPLES,
        "roadmap": [dict(stage=a, stage_title=STAGES[a - 1], task_id=b, title=c,
                         condition=d, procedure_codes=list(e)) for a, b, c, d, e in TASKS],
        "source_hashes": sources(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = payload()
    if args.check:
        saved = json.loads(DEST.read_text()) if DEST.is_file() else {}
        if all(saved.get(key) == value for key, value in current.items()):
            print("Documentation contracts and source hashes are current.")
            return 0
        print("Documentation is stale. Run python scripts/export_documentation.py and review affected guides.")
        return 1
    current["checked_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    current["source_revision"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    current["maintain_through"] = "2026-11-11"
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(f"Exported {sum(len(v) for v in current['openapi']['paths'].values())} API operations, "
          f"{len(TASKS)} roadmap tasks and {len(current['source_hashes'])} source hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
