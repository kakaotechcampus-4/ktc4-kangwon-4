"""Real document Agent evaluation with labelled synthetic files and explicit owner input."""

import argparse
import asyncio
import hashlib
import io
import json
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

import pymupdf
from app.agent.document_tool.checks import document_date, money, normalized
from app.agent.document_tool.models import DocumentContext, DocumentKind
from app.agent.document_tool.tool import build_document_tool
from app.agent.tracing import capture_usage
from scripts.evaluation_metrics import (
    evaluation_code_digest,
    load_prices,
    summarize_metrics,
    write_metadata,
)

EXPECTED = {
    DocumentKind.CONSTRUCTION_STATEMENT: {"supplier": "그린철거", "buyer": "봄날개인카페", "amount": "3,300,000원"},
    DocumentKind.TAX_INVOICE: {"supplier": "그린철거", "buyer": "봄날개인카페", "supply_amount": "3,000,000원", "tax_amount": "300,000원", "amount": "3,300,000원"},
    DocumentKind.TRANSFER: {"sender": "김리본", "recipient": "그린철거", "amount": "3,300,000원"},
    DocumentKind.CLOSURE_CERTIFICATE: {"business_name": "봄날개인카페", "closure_date": "2026년 10월 31일"},
    DocumentKind.BANK_COPY: {"account_holder": "김리본"},
    DocumentKind.BEFORE_PHOTO: {}, DocumentKind.AFTER_PHOTO: {},
}
LABELS = {"supplier": "공급자", "buyer": "공급받는 자", "amount": "합계금액(부가세 포함)",
          "supply_amount": "공급가액", "tax_amount": "세액", "sender": "보낸 사람",
          "recipient": "받는 사람", "business_name": "상호", "closure_date": "폐업일", "account_holder": "예금주"}
TITLES = {DocumentKind.CONSTRUCTION_STATEMENT: "철거공사내역서", DocumentKind.TAX_INVOICE: "전자세금계산서",
          DocumentKind.TRANSFER: "이체확인증", DocumentKind.CLOSURE_CERTIFICATE: "폐업사실증명원",
          DocumentKind.BANK_COPY: "통장 사본"}


def document_bytes(kind, layout):
    with pymupdf.open() as document:
        page = document.new_page()
        if kind in {DocumentKind.BEFORE_PHOTO, DocumentKind.AFTER_PHOTO}:
            # Distinct image placeholders, never presented as actual cafe photos.
            page.draw_rect((60, 100, 220 if kind == DocumentKind.BEFORE_PHOTO else 380, 250), fill=(0.4, 0.5, 0.6))
            return page.get_pixmap().tobytes("png"), ".png"
        page.insert_text((40, 35), "검증용 가상문서 / 제출용 아님", fontname="korea", fontsize=10)
        page.insert_text((40, 75), TITLES[kind], fontname="korea", fontsize=18)
        for index, (field, value) in enumerate(EXPECTED[kind].items()):
            top = 100 + index * 55
            if layout == "simple":
                page.insert_text((40, top + 15), f"{LABELS[field]}: {value}", fontname="korea", fontsize=12)
            else:
                page.draw_rect((40, top, 555, top + 55), width=0.5)
                page.draw_line((180, top), (180, top + 55), width=0.5)
                for rect, text in [((48, top + 8, 174, top + 52), LABELS[field]), ((188, top + 8, 549, top + 52), value)]:
                    if page.insert_textbox(rect, text, fontname="korea", fontsize=11) < 0:
                        raise ValueError("Synthetic text does not fit")
        if kind == DocumentKind.TRANSFER:
            page.insert_text((40, 350), "주민등록번호: 900101-1234567", fontname="korea", fontsize=12)
        if layout == "scan":
            return page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5).prerotate(1)).tobytes("png"), ".png"
        return document.tobytes(no_new_id=True), ".pdf"


def fields_correct(record, kind):
    if record.analysis.kind != kind:
        return False
    fields = {field.name: field.value for field in record.analysis.fields}
    for key, expected in EXPECTED[kind].items():
        try:
            if key in {"amount", "supply_amount", "tax_amount"}:
                correct = money(fields[key]) == money(expected)
            elif key == "closure_date":
                correct = document_date(fields[key]) == document_date(expected)
            else:
                correct = normalized(fields[key]) == normalized(expected)
        except (KeyError, ValueError, ArithmeticError):
            return False
        if not correct:
            return False
    return True


async def trial(args, output):
    os.environ["AGENT_DOCUMENT_MODEL_PREFIX"] = args.model_prefix
    os.environ["AGENT_DOCUMENT_REASONING_EFFORT"] = args.effort
    if args.model_prefix == "INFO_":
        os.environ["INFO_REASONING_EFFORT"] = args.effort
    agent = await build_document_tool(output / "vault", submission_policy="RRN_BACK_ONLY")
    context = DocumentContext(applicant_name="김리본", business_name="봄날개인카페", closure_date=date(2026, 10, 31))
    kinds = [DocumentKind.TAX_INVOICE] if args.pilot else list(EXPECTED)
    inputs, originals = [], {}
    for kind in kinds:
        data, extension = document_bytes(kind, args.layout)
        filename = str(kind) + extension
        (output / filename).write_bytes(data)
        inputs.append((filename, data, kind))
        originals[hashlib.sha256(data).hexdigest()] = kind
    row = {"model": agent.documents.llm.config.model, "effort": args.effort,
           "automatic_fields_correct": True, "owner_confirmations": [], "owner_corrections": [],
           "workflow_passed": False}
    started = perf_counter()
    with capture_usage() as usage:
        try:
            if args.pilot:
                context = await agent.add_documents(context, inputs)
                row["automatic_fields_correct"] = fields_correct(context.documents[0], kinds[0])
                row["workflow_passed"] = True
            else:
                initial = [item for item in inputs if item[2] != DocumentKind.TRANSFER]
                context = await agent.add_documents(context, initial)

                def confirm(current):
                    for record in list(current.documents):
                        if record.confirmed_fields is not None:
                            continue
                        kind = originals[record.content_hash]
                        correct = fields_correct(record, kind)
                        row["automatic_fields_correct"] &= correct
                        if record.analysis.needs_confirmation or not correct:
                            row["owner_confirmations"].append(str(kind))
                            if not correct:
                                row["owner_corrections"].append(str(kind))
                            current = agent.confirm_document(current, record.document_id, kind,
                                                             confirmed_fields=EXPECTED[kind])
                    return current

                context = confirm(context)
                context = agent.check_documents(context)
                row["missing_transfer_detected"] = {issue.code for issue in context.document_check.issues} == {"MISSING_TRANSFER"}
                assert row["missing_transfer_detected"]
                previous = len(usage)
                transfer = next(item for item in inputs if item[2] == DocumentKind.TRANSFER)
                context = await agent.add_document(context, transfer[0], transfer[1], kind_hint=transfer[2])
                row["new_document_provider_calls"] = len(usage) - previous
                context = confirm(context)
                previous = len(usage)
                context = await agent.add_document(context, transfer[0], transfer[1], kind_hint=transfer[2])
                row["same_file_reupload_provider_calls"] = len(usage) - previous
                assert row["same_file_reupload_provider_calls"] == 0
                context = agent.check_documents(context)
                assert context.document_check.status == "COMPLETE"
                row["redaction_count"] = sum(record.redaction_count for record in context.documents)
                assert row["redaction_count"] >= 1
                package = agent.prepare_settlement(context)
                with ZipFile(io.BytesIO(package)) as archive:
                    assert archive.testzip() is None and len(archive.namelist()) == 9
                (output / "settlement.zip").write_bytes(package)
                row.update(workflow_passed=True, documents=len(context.documents), zip_entries=9)
            row["passed"] = row["workflow_passed"] and row["automatic_fields_correct"]
        except Exception as exc:  # noqa: BLE001 - do not persist provider bodies
            row.update(passed=False, error_type=type(exc).__name__, error_code=getattr(exc, "code", None))
        finally:
            await agent.aclose()
    row.update(status="REVIEWED_PLAN" if row["workflow_passed"] else "ERROR", behavior_passed=row["passed"],
               elapsed_ms=round((perf_counter() - started) * 1000), provider_usage=[asdict(call) for call in usage],
               calls_by_role={"all": len(usage)})
    row["metrics"] = summarize_metrics([row], load_prices())
    return row


async def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    digest = evaluation_code_digest()
    row = await trial(args, args.output)
    report = {"synthetic_data": True, "scope": "Standalone document Agent; explicit synthetic owner confirmations; no app APIs",
              "layout": args.layout, "pilot": args.pilot, "code_digest": digest,
              "code_unchanged": evaluation_code_digest() == digest, "trials": [row], "passed": row["passed"]}
    write_metadata(args.output / "results.json", report)
    print(json.dumps({key: row.get(key) for key in ("passed", "workflow_passed", "automatic_fields_correct", "owner_corrections", "error_type", "metrics")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-prefix", choices=["INFO_", "LUNA6_"], default="LUNA6_")
    parser.add_argument("--effort", choices=["xhigh", "high", "medium", "low"], required=True)
    parser.add_argument("--layout", choices=["simple", "table", "scan"], default="simple")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
