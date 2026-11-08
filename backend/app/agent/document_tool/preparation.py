"""Local PDF operations run in one process; no model calls or file persistence."""

import asyncio
import base64
import multiprocessing
import re
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import lru_cache

import pymupdf

RRN = re.compile(r"(?<!\d)(\d{6})\s*[- ]?\s*([1-8]\d{6})(?!\d)")
IDENTIFIERS = re.compile(
    r"(?<!\d)(?:\d{3}-\d{2}-\d{5}|01[016789][- ]?\d{3,4}[- ]?\d{4}|"
    r"\d{10,16}|\d{3,6}-\d{2,6}-\d{3,8})(?!\d)|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
)
PDF_ERRORS = (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase)


class DocumentError(ValueError):
    """Safe message without document contents or provider bodies."""


def redact_text(text: str, private_values: tuple[str, ...] = ()) -> str:
    text = IDENTIFIERS.sub("[식별번호]", RRN.sub("[주민등록번호]", text))
    for index, value in enumerate(private_values):
        if value:
            text = text.replace(value, f"[개인정보_{index + 1}]")
    return text


@lru_cache(maxsize=1)
def _pool() -> ProcessPoolExecutor:
    # ponytail: one PDF worker per API process; increase only after load testing.
    return ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))


async def run_pdf(function, *args):
    try:
        return await asyncio.get_running_loop().run_in_executor(_pool(), function, *args)
    except BrokenProcessPool:
        _pool.cache_clear()
        raise DocumentError("문서 처리 프로세스가 중단됐습니다. 파일을 확인하고 다시 시도해 주세요.") from None


def prepare_document(content: bytes, extension: str, tessdata: str,
                     private_values: tuple[str, ...], submission_policy: str, for_model: bool = False):
    if extension not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise DocumentError("PDF, PNG, JPG 파일만 지원합니다.")
    if not content or len(content) > 20_000_000:
        raise DocumentError("파일은 비어 있지 않은 20MB 이하 자료여야 합니다.")
    try:
        source = pymupdf.open(stream=content, filetype=extension.lstrip("."))
        if not source.is_pdf:
            with source:
                converted = source.convert_to_pdf()
            source = pymupdf.open(stream=converted, filetype="pdf")
    except PDF_ERRORS:
        raise DocumentError("파일을 읽을 수 없습니다. 파일 형식과 손상 여부를 확인해 주세요.") from None
    pages, redactions, ocr_used = [], 0, False
    unlocated = {value for value in private_values if value} if for_model else set()
    try:
        with source, pymupdf.open() as output:
            if source.needs_pass or not 1 <= len(source) <= 30:
                raise DocumentError("암호 없는 30쪽 이하 문서를 올려주세요.")
            for page in source:
                if page.rect.width * page.rect.height > 5_000_000:
                    raise DocumentError("문서 페이지 크기가 너무 큽니다.")
                try:
                    needs_ocr = bool(page.get_images()) or not page.get_text().strip()
                    ocr_used |= needs_ocr
                    textpage = page.get_textpage_ocr(
                        language="kor+eng", dpi=180, full=False, tessdata=tessdata,
                    ) if needs_ocr else page.get_textpage()
                except PDF_ERRORS:
                    raise DocumentError("로컬 한국어 OCR을 준비해 주세요: scripts/setup_agent_ocr.py") from None
                text = page.get_text("text", textpage=textpage, sort=True)
                pages.append(redact_text(text, private_values))
                areas = []
                for match in RRN.finditer(text):
                    target = match[2] if submission_policy == "RRN_BACK_ONLY" and not for_model else match[0]
                    rectangles = page.search_for(target, textpage=textpage)
                    if not rectangles:
                        raise DocumentError("주민등록번호 위치를 확인할 수 없어 파일 생성을 중단했습니다.")
                    areas.extend(rectangles)
                    redactions += 1
                if submission_policy == "ALL_IDENTIFIERS" or for_model:
                    for match in IDENTIFIERS.finditer(text):
                        areas.extend(page.search_for(match[0], textpage=textpage))
                if for_model:
                    for value in private_values:
                        if not value:
                            continue
                        rectangles = page.search_for(value, textpage=textpage)
                        if rectangles:
                            unlocated.discard(value)
                        areas.extend(rectangles)
                image = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                clean = output.new_page(width=page.rect.width, height=page.rect.height)
                clean.insert_image(clean.rect, pixmap=image)
                for rectangle in areas:
                    clean.add_redact_annot(rectangle + (-1, -1, 1, 1), fill=(0, 0, 0))
                if areas:
                    clean.apply_redactions()
            if unlocated:
                raise DocumentError("개인정보 가림 위치를 확인할 수 없어 이미지 판독을 중단했습니다.")
            return pages, output.tobytes(garbage=4, deflate=True), redactions, ocr_used
    except DocumentError:
        raise
    except PDF_ERRORS:
        raise DocumentError("문서를 처리할 수 없습니다. 파일 손상 여부를 확인해 주세요.") from None


def render_images(masked_pdf: bytes) -> list[str]:
    try:
        with pymupdf.open(stream=masked_pdf, filetype="pdf") as document:
            return [base64.b64encode(page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).tobytes("png")).decode()
                    for page in document]
    except PDF_ERRORS:
        raise DocumentError("문서 이미지를 처리할 수 없습니다. 파일 손상 여부를 확인해 주세요.") from None
