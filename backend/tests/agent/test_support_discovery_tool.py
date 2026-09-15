from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.agent.support_agent import (
    BIZINFO_SUPPORT_API_ENDPOINT,
    BizInfoSupportDiscoveryConfig,
    BizInfoSupportDiscoveryTool,
    SupportNoticeDiscoveryConfigurationError,
    SupportNoticeDiscoveryInput,
    SupportNoticeDiscoveryInputError,
    SupportNoticeDiscoveryRequestError,
    SupportNoticeDiscoveryResponseError,
    SupportNoticeDiscoveryResult,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 15, 4, 30, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=5)
TEST_KEY = "fake-bizinfo-key-that-must-not-leak"


def notice(
    notice_id: str = "PBLN_000000000117676",
    *,
    total_count: int = 1,
    **updates: Any,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "bsnsSumryCn": (
            "<p>폐업 소상공인의 재기를 &amp; 안전하게 지원합니다.</p>"
            "<script>secret script text</script><p>둘째 문장</p>"
        ),
        "creatPnttm": "2026-01-05 09:10:11",
        "excInsttNm": "소상공인시장진흥공단",
        "fileNm": "공고문.hwp",
        "flpthNm": (
            "https://www.bizinfo.go.kr/cmm/fms/getImageFile.do"
            "?atchFileId=FILE_1&fileSn=1"
        ),
        "hashtags": "폐업, 소상공인,폐업",
        "inqireCo": 321,
        "jrsdInsttNm": "중소벤처기업부",
        "pblancId": notice_id,
        "pblancNm": "<b>2026년 희망리턴패키지</b>",
        "pblancUrl": (
            "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do"
            f"?pblancId={notice_id}"
        ),
        "pldirSportRealmLclasCodeNm": "경영",
        "pldirSportRealmMlsfcCodeNm": "경영지원",
        "printFileNm": "공고문.pdf",
        "printFlpthNm": (
            "https://www.bizinfo.go.kr/cmm/fms/getImageFile.do"
            "?atchFileId=FILE_2&fileSn=1"
        ),
        "rceptEngnHmpgUrl": "https://www.sbiz24.kr/nhrp/",
        "refrncNm": "중소기업통합콜센터 1357",
        "reqstBeginEndDe": "예산 소진시까지",
        "reqstMthPapersCn": "<p>온라인 접수<br>서류 제출</p>",
        "totCnt": total_count,
        "trgetNm": "폐업(예정) 소상공인",
        "updtPnttm": "2026-01-06 10:11:12",
    }
    item.update(updates)
    return item


def api_response(
    *items: dict[str, Any],
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    response_headers = {"content-type": "application/json; charset=UTF-8"}
    if headers:
        response_headers.update(headers)
    return httpx.Response(
        status_code,
        content=json.dumps({"jsonArray": list(items)}, ensure_ascii=False).encode(),
        headers=response_headers,
    )


def config(**updates: Any) -> BizInfoSupportDiscoveryConfig:
    values: dict[str, Any] = {
        "api_key": TEST_KEY,
        "timeout_seconds": 2,
        "max_response_bytes": 20_000,
        "max_results": 10,
    }
    values.update(updates)
    return BizInfoSupportDiscoveryConfig(**values)


def request(
    *, keywords: tuple[str, ...] = ("폐업", "희망리턴"), max_results: int = 5
) -> SupportNoticeDiscoveryInput:
    return SupportNoticeDiscoveryInput(
        keywords=keywords,
        max_results=max_results,
    )


def valid_result_payload(
    *items: dict[str, Any],
) -> dict[str, Any]:
    response_items = items or (notice(),)

    async def scenario() -> SupportNoticeDiscoveryResult:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(lambda _: api_response(*response_items)),
            clock=lambda: NOW,
        ) as tool:
            return await tool.discover(request())

    return asyncio.run(scenario()).model_dump(mode="python")


def test_discovers_normalized_candidate_and_official_api_evidence() -> None:
    observed: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        observed.append(http_request)
        assert http_request.method == "GET"
        assert (
            str(http_request.url.copy_with(query=None)) == BIZINFO_SUPPORT_API_ENDPOINT
        )
        assert http_request.url.params["crtfcKey"] == TEST_KEY
        assert http_request.url.params["dataType"] == "json"
        assert http_request.url.params["hashtags"] == "폐업,희망리턴"
        assert http_request.url.params["pageUnit"] == "5"
        assert http_request.url.params["pageIndex"] == "1"
        return api_response(notice())

    async def scenario() -> SupportNoticeDiscoveryResult:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        ) as tool:
            return await tool.discover(request())

    result = asyncio.run(scenario())

    assert len(observed) == 1
    assert result.provider == "BIZINFO"
    assert result.result_count == 1
    assert result.provider_total_count == 1
    assert result.provider_returned_count == 1
    assert result.duplicate_count == 0
    assert result.truncated is False
    candidate = result.candidates[0]
    assert candidate.notice_id == "PBLN_000000000117676"
    assert candidate.title == "2026년 희망리턴패키지"
    assert candidate.summary == (
        "폐업 소상공인의 재기를 & 안전하게 지원합니다. 둘째 문장"
    )
    assert "script" not in candidate.summary
    assert candidate.application_method == "온라인 접수 서류 제출"
    assert candidate.hashtags == ("폐업", "소상공인")
    assert candidate.provider_created_at is not None
    assert candidate.provider_created_at.isoformat() == "2026-01-05T09:10:11+09:00"
    assert candidate.freshness_status == "UNKNOWN"

    evidence = result.evidence_records[0]
    assert candidate.evidence_ref == evidence.evidence_id
    assert evidence.source_type == "OFFICIAL_API"
    assert evidence.source_ref == BIZINFO_SUPPORT_API_ENDPOINT
    assert evidence.locator == candidate.detail_url
    assert evidence.published_at is None
    assert evidence.retrieved_at == NOW
    assert evidence.freshness_status == "UNKNOWN"
    assert evidence.content_hash is not None
    assert evidence.content_hash.startswith("sha256:")
    assert evidence.source_version == evidence.content_hash
    assert TEST_KEY not in evidence.model_dump_json()


def test_httpx_info_log_redacts_api_key_before_record_capture(caplog: Any) -> None:
    transmitted_key: str | None = None

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal transmitted_key
        transmitted_key = http_request.url.params["crtfcKey"]
        assert TEST_KEY.encode() in http_request.url.raw_path
        assert TEST_KEY not in str(http_request.url)
        assert TEST_KEY not in repr(http_request)
        return api_response(notice())

    async def scenario() -> None:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        ) as tool:
            await tool.discover(request())

    with caplog.at_level(logging.INFO, logger="httpx"):
        asyncio.run(scenario())

    httpx_records = [record for record in caplog.records if record.name == "httpx"]
    assert transmitted_key == TEST_KEY
    assert httpx_records
    assert any("HTTP Request" in record.getMessage() for record in httpx_records)
    assert any("REDACTED" in record.getMessage() for record in httpx_records)
    assert TEST_KEY not in caplog.text
    assert all(TEST_KEY not in repr(record.args) for record in httpx_records)


def test_injected_client_defaults_are_not_inherited_by_isolated_request() -> None:
    observed: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        observed.append(http_request)
        assert http_request.url.params["crtfcKey"] == TEST_KEY
        assert "inheritedParam" not in http_request.url.params
        assert http_request.headers.get("authorization") is None
        assert http_request.headers.get("x-client-default") is None
        assert http_request.headers.get("cookie") is None
        assert http_request.extensions["timeout"] == {
            "connect": 2,
            "read": 2,
            "write": 2,
            "pool": 2,
        }
        return api_response(notice())

    async def scenario() -> None:
        client = httpx.AsyncClient(
            base_url="https://client-default.example",
            params={"inheritedParam": "must-not-send"},
            headers={
                "Authorization": "Bearer client-default-secret",
                "X-Client-Default": "must-not-send",
            },
            cookies={"session": "must-not-send"},
            auth=("default-user", "default-password"),
            timeout=99,
            transport=httpx.MockTransport(handler),
        )
        try:
            async with BizInfoSupportDiscoveryTool(
                config(),
                client=client,
                clock=lambda: NOW,
            ) as tool:
                await tool.discover(request())
            assert client.is_closed is False
        finally:
            await client.aclose()

    asyncio.run(scenario())
    assert len(observed) == 1


def test_optional_fields_may_be_absent_in_the_actual_json_array_shape() -> None:
    item = notice()
    for field in ("fileNm", "flpthNm", "rceptEngnHmpgUrl"):
        item.pop(field)

    async def scenario() -> SupportNoticeDiscoveryResult:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(lambda _: api_response(item)),
            clock=lambda: NOW,
        ) as tool:
            return await tool.discover(request())

    candidate = asyncio.run(scenario()).candidates[0]
    assert candidate.attachment_name is None
    assert candidate.attachment_url is None
    assert candidate.application_url is None


def test_evidence_identity_and_hash_ignore_retrieval_time_and_view_count() -> None:
    async def discover_at(
        now: datetime, view_count: int
    ) -> SupportNoticeDiscoveryResult:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(
                lambda _: api_response(notice(inqireCo=view_count))
            ),
            clock=lambda: now,
        ) as tool:
            return await tool.discover(request())

    first = asyncio.run(discover_at(NOW, 10))
    second = asyncio.run(discover_at(LATER, 999))

    assert (
        first.evidence_records[0].evidence_id == second.evidence_records[0].evidence_id
    )
    assert (
        first.evidence_records[0].content_hash
        == second.evidence_records[0].content_hash
    )
    assert first.evidence_records[0].retrieved_at == NOW
    assert second.evidence_records[0].retrieved_at == LATER


def test_deduplicates_by_pblanc_id_and_keeps_provider_order() -> None:
    first = notice(total_count=3)
    duplicate = notice(total_count=3, pblancNm="provider duplicate")
    second = notice(
        "PBLN_000000000122739",
        total_count=3,
        pblancNm="두 번째 공고",
    )

    async def scenario() -> SupportNoticeDiscoveryResult:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(
                lambda _: api_response(first, duplicate, second)
            ),
            clock=lambda: NOW,
        ) as tool:
            return await tool.discover(request())

    result = asyncio.run(scenario())
    assert [item.notice_id for item in result.candidates] == [
        "PBLN_000000000117676",
        "PBLN_000000000122739",
    ]
    assert result.candidates[0].title == "2026년 희망리턴패키지"
    assert result.duplicate_count == 1
    assert result.provider_returned_count == 3
    assert result.result_count == 2
    assert result.truncated is True


def test_config_limit_caps_request_and_output_even_if_provider_returns_more() -> None:
    items = [
        notice(
            f"PBLN_00000000000000{index}",
            total_count=3,
            pblancNm=f"공고 {index}",
        )
        for index in range(1, 4)
    ]

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.params["pageUnit"] == "2"
        return api_response(*items)

    async def scenario() -> SupportNoticeDiscoveryResult:
        async with BizInfoSupportDiscoveryTool(
            config(max_results=2),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        ) as tool:
            return await tool.discover(request(max_results=5))

    result = asyncio.run(scenario())
    assert result.applied_result_limit == 2
    assert result.result_count == 2
    assert len(result.evidence_records) == 2
    assert result.truncated is True


def test_well_formed_empty_response_is_a_completed_empty_discovery() -> None:
    async def scenario() -> SupportNoticeDiscoveryResult:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(lambda _: api_response()),
            clock=lambda: NOW,
        ) as tool:
            return await tool.discover(request())

    result = asyncio.run(scenario())
    assert result.provider_total_count is None
    assert result.result_count == 0
    assert result.candidates == ()
    assert result.evidence_records == ()
    assert result.truncated is False


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {"jsonArray": {}, "extra": "unexpected"},
        {"jsonArray": [dict(notice(), inqireCo="321")]},
        {"jsonArray": [dict(notice(), unexpected="schema drift")]},
        {
            "jsonArray": [
                {key: value for key, value in notice().items() if key != "pblancNm"}
            ]
        },
    ],
)
def test_rejects_schema_drift_without_coercion(payload: dict[str, Any]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def scenario() -> None:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        ) as tool:
            with pytest.raises(SupportNoticeDiscoveryResponseError) as raised:
                await tool.discover(request())
        assert raised.value.code == "BIZINFO_RESPONSE_SCHEMA_INVALID"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        (b"not-json", "BIZINFO_RESPONSE_SCHEMA_INVALID"),
        (b'{"jsonArray":[],"jsonArray":[]}', "BIZINFO_RESPONSE_SCHEMA_INVALID"),
        (b'{"jsonArray":[],"number":NaN}', "BIZINFO_RESPONSE_SCHEMA_INVALID"),
    ],
)
def test_rejects_non_strict_json(body: bytes, expected_code: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "application/json"},
        )

    async def scenario() -> None:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        ) as tool:
            with pytest.raises(SupportNoticeDiscoveryResponseError) as raised:
                await tool.discover(request())
        assert raised.value.code == expected_code

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    [
        (
            {"pblancUrl": "https://evil.example/not-a-bizinfo-page"},
            "BIZINFO_OFFICIAL_URL_INVALID",
        ),
        (
            {
                "pblancUrl": (
                    "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do"
                    "?pblancId=PBLN_000000000000000"
                )
            },
            "BIZINFO_DETAIL_URL_INVALID",
        ),
        ({"updtPnttm": "not-a-date"}, "BIZINFO_TIMESTAMP_INVALID"),
        (
            {"rceptEngnHmpgUrl": "http://127.0.0.1/private"},
            "BIZINFO_URL_INVALID",
        ),
        (
            {"flpthNm": "https://127.0.0.1/private"},
            "BIZINFO_URL_INVALID",
        ),
        (
            {
                "pblancUrl": (
                    "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do"
                    "?pblancId=PBLN_000000000117676&token=must-not-emit"
                )
            },
            "BIZINFO_URL_SENSITIVE_QUERY",
        ),
        (
            {
                "flpthNm": (
                    "https://www.bizinfo.go.kr/cmm/fms/getImageFile.do"
                    "?atchFileId=FILE_1&fileSn=1&apiKey=must-not-emit"
                )
            },
            "BIZINFO_URL_SENSITIVE_QUERY",
        ),
        (
            {
                "rceptEngnHmpgUrl": (
                    "https://apply.example.com/form?client_secret=must-not-emit"
                )
            },
            "BIZINFO_URL_SENSITIVE_QUERY",
        ),
    ],
)
def test_rejects_invalid_notice_identity_and_metadata_urls(
    updates: dict[str, Any], expected_code: str
) -> None:
    async def scenario() -> None:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(lambda _: api_response(notice(**updates))),
            clock=lambda: NOW,
        ) as tool:
            with pytest.raises(SupportNoticeDiscoveryResponseError) as raised:
                await tool.discover(request())
        assert raised.value.code == expected_code

    asyncio.run(scenario())


def test_non_sensitive_application_query_names_remain_available() -> None:
    item = notice(
        rceptEngnHmpgUrl=(
            "https://apply.example.com/form?keyword=폐업&authenticity=public"
        )
    )

    async def scenario() -> SupportNoticeDiscoveryResult:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(lambda _: api_response(item)),
            clock=lambda: NOW,
        ) as tool:
            return await tool.discover(request())

    result = asyncio.run(scenario())
    assert result.candidates[0].application_url == item["rceptEngnHmpgUrl"]


def test_refuses_redirect_without_following_location_or_leaking_key() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            302,
            headers={"location": "https://evil.example/collect"},
        )

    async def scenario() -> SupportNoticeDiscoveryRequestError:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(handler),
        ) as tool:
            with pytest.raises(SupportNoticeDiscoveryRequestError) as raised:
                await tool.discover(request())
        return raised.value

    error = asyncio.run(scenario())
    assert calls == 1
    assert error.code == "BIZINFO_REDIRECT_REFUSED"
    assert error.status_code == 302
    assert error.retryable is False
    assert TEST_KEY not in str(error)
    assert TEST_KEY not in repr(error)


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(403, False), (429, True), (503, True)],
)
def test_http_errors_are_sanitized(status_code: int, retryable: bool) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=f"provider echoed {TEST_KEY}")

    async def scenario() -> SupportNoticeDiscoveryRequestError:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(handler),
        ) as tool:
            with pytest.raises(SupportNoticeDiscoveryRequestError) as raised:
                await tool.discover(request())
        return raised.value

    error = asyncio.run(scenario())
    assert error.code == "BIZINFO_HTTP_ERROR"
    assert error.retryable is retryable
    assert error.status_code == status_code
    assert TEST_KEY not in str(error)


def test_invalid_response_error_does_not_retain_key_or_body() -> None:
    private_body_marker = "upstream-private-body-must-not-leak"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonArray": TEST_KEY,
                "detail": private_body_marker,
            },
        )

    async def scenario() -> SupportNoticeDiscoveryResponseError:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(handler),
        ) as tool:
            with pytest.raises(SupportNoticeDiscoveryResponseError) as raised:
                await tool.discover(request())
        return raised.value

    error = asyncio.run(scenario())
    assert error.code == "BIZINFO_RESPONSE_SCHEMA_INVALID"
    assert TEST_KEY not in str(error)
    assert TEST_KEY not in repr(error)
    assert private_body_marker not in str(error)
    assert private_body_marker not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_transport_error_is_sanitized() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"failed URL containing {TEST_KEY}", request=http_request
        )

    async def scenario() -> SupportNoticeDiscoveryRequestError:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(handler),
        ) as tool:
            with pytest.raises(SupportNoticeDiscoveryRequestError) as raised:
                await tool.discover(request())
        return raised.value

    error = asyncio.run(scenario())
    assert error.code == "BIZINFO_TRANSPORT_ERROR"
    assert error.retryable is True
    assert error.status_code is None
    assert TEST_KEY not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(
    "keyword",
    [
        "사업자번호 123-45-67890 폐업지원",
        "사업자번호 123 45 67890 폐업지원",
        "사업자번호 1234567890 폐업지원",
        "강원특별자치도 춘천시 중앙로 123 폐업지원",
        "Bearer abcdefghijklmnop",
    ],
)
def test_sensitive_keyword_preflight_prevents_external_transmission(
    keyword: str,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return api_response()

    async def scenario() -> SupportNoticeDiscoveryInputError:
        async with BizInfoSupportDiscoveryTool(
            config(),
            transport=httpx.MockTransport(handler),
        ) as tool:
            with pytest.raises(SupportNoticeDiscoveryInputError) as raised:
                await tool.discover(request(keywords=(keyword,)))
        return raised.value

    error = asyncio.run(scenario())
    assert calls == 0
    assert error.code == "BIZINFO_SENSITIVE_KEYWORD"
    assert error.retryable is False
    assert keyword not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_rejects_unexpected_content_type_and_oversized_body() -> None:
    def html_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html>not JSON</html>",
            headers={"content-type": "text/html"},
        )

    def large_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"{" + b"x" * 1_024,
            headers={"content-type": "application/json"},
        )

    async def assert_error(handler: Any, expected_code: str) -> None:
        async with BizInfoSupportDiscoveryTool(
            config(max_response_bytes=1_024),
            transport=httpx.MockTransport(handler),
        ) as tool:
            with pytest.raises(SupportNoticeDiscoveryResponseError) as raised:
                await tool.discover(request())
        assert raised.value.code == expected_code

    asyncio.run(assert_error(html_handler, "BIZINFO_CONTENT_TYPE_INVALID"))
    asyncio.run(assert_error(large_handler, "BIZINFO_RESPONSE_TOO_LARGE"))


def test_env_file_loading_uses_process_environment_precedence(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("BIZINFO_API_KEY=file-value\n", encoding="utf-8")

    from_file = BizInfoSupportDiscoveryConfig.from_env(
        env_file=env_file,
        environ={},
    )
    from_process = BizInfoSupportDiscoveryConfig.from_env(
        env_file=env_file,
        environ={"BIZINFO_API_KEY": "process-value"},
    )

    assert from_file.api_key == "file-value"
    assert from_process.api_key == "process-value"
    assert "file-value" not in repr(from_file)
    assert "process-value" not in repr(from_process)


def test_missing_or_invalid_config_is_rejected_without_secret_echo(
    tmp_path: Path,
) -> None:
    with pytest.raises(SupportNoticeDiscoveryConfigurationError) as missing:
        BizInfoSupportDiscoveryConfig.from_env(
            env_file=tmp_path / "missing.env",
            environ={},
        )
    assert "BIZINFO_API_KEY" in str(missing.value)

    secret_with_control = "do-not-echo\nsecret"
    with pytest.raises(SupportNoticeDiscoveryConfigurationError) as invalid:
        BizInfoSupportDiscoveryConfig(api_key=secret_with_control)
    assert secret_with_control not in str(invalid.value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 31},
        {"timeout_seconds": True},
        {"timeout_seconds": "2"},
        {"max_response_bytes": 1_023},
        {"max_response_bytes": 5_000_001},
        {"max_response_bytes": 2_000.5},
        {"max_results": 0},
        {"max_results": 101},
        {"max_results": True},
    ],
)
def test_configuration_limits_are_bounded(kwargs: dict[str, Any]) -> None:
    with pytest.raises(SupportNoticeDiscoveryConfigurationError):
        config(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"keywords": ()},
        {"keywords": ("폐업", "폐업")},
        {"keywords": ("폐업,지원",)},
        {"keywords": ("폐업\n지원",)},
        {"max_results": True},
        {"max_results": 101},
        {"unexpected": "field"},
    ],
)
def test_input_contract_is_strict(kwargs: dict[str, Any]) -> None:
    values: dict[str, Any] = {"keywords": ("폐업",), "max_results": 5}
    values.update(kwargs)
    with pytest.raises(ValidationError):
        SupportNoticeDiscoveryInput(**values)


def test_result_contract_rejects_broken_evidence_relation() -> None:
    payload = valid_result_payload()
    payload["candidates"][0]["evidence_ref"] = "unknown-evidence"
    with pytest.raises(ValidationError, match="identifiers must be bijective"):
        SupportNoticeDiscoveryResult.model_validate(payload)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"result_count": 0}, "result_count must equal"),
        ({"provider_returned_count": 0}, "normalized results exceed"),
        ({"duplicate_count": 2}, "duplicate_count exceeds"),
        ({"provider_total_count": 0}, "provider total count is smaller"),
        ({"provider_total_count": None}, "total count presence"),
        ({"truncated": True}, "truncated does not match"),
    ],
)
def test_result_contract_rejects_invalid_counts(
    updates: dict[str, Any], message: str
) -> None:
    payload = valid_result_payload()
    payload.update(updates)
    with pytest.raises(ValidationError, match=message):
        SupportNoticeDiscoveryResult.model_validate(payload)


def test_result_contract_requires_all_unique_rows_when_limit_has_room() -> None:
    payload = valid_result_payload()
    payload.update(
        provider_returned_count=2,
        provider_total_count=2,
        truncated=True,
    )
    with pytest.raises(ValidationError, match="bounded unique count"):
        SupportNoticeDiscoveryResult.model_validate(payload)


def test_result_contract_rejects_result_count_above_applied_limit() -> None:
    first = notice(total_count=2)
    second = notice(
        "PBLN_000000000122739",
        total_count=2,
        pblancNm="두 번째 공고",
    )
    payload = valid_result_payload(first, second)
    payload["applied_result_limit"] = 1
    with pytest.raises(ValidationError, match="applied result limit"):
        SupportNoticeDiscoveryResult.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_type", "OFFICIAL_DOCUMENT", "must be OFFICIAL_API"),
        ("freshness_status", "CURRENT", "freshness must be UNKNOWN"),
        ("retrieved_at", LATER, "retrieval time must match"),
        ("source_ref", "https://example.com/api", "identify the Bizinfo API"),
        ("locator", "https://example.com/notice", "locator must match"),
        ("source_version", "sha256:" + "b" * 64, "hash must match"),
        ("content_hash", "sha256:" + "b" * 64, "hash must match"),
        ("excerpt", "변조된 근거", "excerpt must match"),
        ("parent_evidence_refs", ["parent-evidence"], "must not have parent"),
        ("published_at", NOW, "publication time must remain null"),
    ],
)
def test_result_contract_rejects_invalid_evidence_fields(
    field: str, value: Any, message: str
) -> None:
    payload = valid_result_payload()
    payload["evidence_records"][0][field] = value
    with pytest.raises(ValidationError, match=message):
        SupportNoticeDiscoveryResult.model_validate(payload)


def test_result_contract_recomputes_candidate_hash_and_evidence_id() -> None:
    changed_candidate = valid_result_payload()
    changed_candidate["candidates"][0]["title"] = "근거 해시 없이 바꾼 제목"
    with pytest.raises(ValidationError, match="hash must match"):
        SupportNoticeDiscoveryResult.model_validate(changed_candidate)

    changed_id = valid_result_payload()
    changed_id["candidates"][0]["evidence_ref"] = "arbitrary-evidence-id"
    changed_id["evidence_records"][0]["evidence_id"] = "arbitrary-evidence-id"
    with pytest.raises(ValidationError, match="derived from notice_id and hash"):
        SupportNoticeDiscoveryResult.model_validate(changed_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("notice_id", "NOT_A_BIZINFO_ID"),
        ("detail_url", "https://evil.example/notice"),
        (
            "detail_url",
            (
                "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do"
                "?pblancId=PBLN_000000000000000"
            ),
        ),
        ("attachment_url", "https://evil.example/file"),
        ("print_attachment_url", "http://www.bizinfo.go.kr/file"),
        ("application_url", "http://127.0.0.1/private"),
        ("application_url", "https://example.com:80/wrong-port"),
        ("application_url", "https://example.com/path with space"),
        (
            "detail_url",
            (
                "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do"
                "?pblancId=PBLN_000000000117676&auth=must-not-emit"
            ),
        ),
        (
            "attachment_url",
            (
                "https://www.bizinfo.go.kr/cmm/fms/getImageFile.do"
                "?atchFileId=FILE_1&fileSn=1&signature=must-not-emit"
            ),
        ),
        (
            "application_url",
            "https://apply.example.com/form?access_token=must-not-emit",
        ),
    ],
)
def test_candidate_contract_rejects_invalid_urls_and_notice_ids(
    field: str, value: str
) -> None:
    payload = valid_result_payload()
    payload["candidates"][0][field] = value
    with pytest.raises(ValidationError):
        SupportNoticeDiscoveryResult.model_validate(payload)


@pytest.mark.parametrize("field", ["attachment_url", "print_attachment_url"])
def test_candidate_contract_requires_attachment_name_url_pairs(field: str) -> None:
    payload = valid_result_payload()
    payload["candidates"][0][field] = None
    with pytest.raises(ValidationError, match="must be present together"):
        SupportNoticeDiscoveryResult.model_validate(payload)


def test_candidate_validation_error_hides_sensitive_query_value() -> None:
    sensitive_value = "candidate-query-secret-must-not-leak"
    payload = valid_result_payload()
    payload["candidates"][0]["application_url"] = (
        f"https://apply.example.com/form?api_key={sensitive_value}"
    )

    with pytest.raises(ValidationError) as raised:
        SupportNoticeDiscoveryResult.model_validate(payload)

    assert sensitive_value not in str(raised.value)
    assert sensitive_value not in repr(raised.value)
