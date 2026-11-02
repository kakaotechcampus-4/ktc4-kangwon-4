"""Synthetic files and structured responses for document boundary tests."""

import json
from types import SimpleNamespace

import pymupdf
from app.agent.document_tool.models import (
    DocumentAnalysis,
    DocumentKind,
    ExtractedField,
    ReviewDecision,
)
from app.agent.document_tool.safety import SafetyDecision


def document_pdf(kind, **fields):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40, 60), f"kind={kind}\n" + "\n".join(f"{key}={value}" for key, value in fields.items()),
                         fontname="korea", fontsize=14)
        return document.tobytes()


class DocumentClient:
    def __init__(self):
        self.config = SimpleNamespace(model="synthetic", reasoning_effort="high")
        self.calls = []
        self.needs_confirmation = False

    async def generate(self, model, messages, **_):
        self.calls.append(model.__name__)
        if model is SafetyDecision:
            return SafetyDecision(decision="ALLOW")
        if model is ReviewDecision:
            return ReviewDecision(verdict="PASS", issues=[])
        assert model is DocumentAnalysis
        text = json.loads(messages[-1]["content"])["pages"][0]
        fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
        kind = DocumentKind(fields.pop("kind"))
        return DocumentAnalysis(kind=kind, fields=[
            ExtractedField(name=key, value=value, page=1, quote=f"{key}={value}")
            for key, value in fields.items()
        ], needs_confirmation=self.needs_confirmation)

    async def aclose(self):
        pass
