from __future__ import annotations

import asyncio
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.agent.procedure_tool import (
    DEFAULT_SEARCH_ENDPOINT,
    ProcedureLookupInputError,
    ProcedureLookupRequestError,
    ProcedureLookupTool,
    ProcedureSearchConfig,
    ProcedureSearchConfigurationError,
)
from app.agent.schemas import ProcedureLookupInput

NOW = datetime(2026, 9, 15, 3, 30, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000701")
LOOKUP_ID = UUID("00000000-0000-4000-8000-000000000702")
DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000703")


def lookup_request(
    *,
    queries: list[str] | None = None,
    max_results: int = 5,
) -> ProcedureLookupInput:
    return ProcedureLookupInput(
        lookup_goal="BUSINESS_CLOSURE",
        search_queries=queries or ["개인사업자 폐업 신고 절차"],
        as_of=date(2026, 9, 15),
        locale="ko-KR",
        source_policy="OFFICIAL_ONLY",
        max_results_per_query=max_results,
        based_on_snapshot_id=SNAPSHOT_ID,
        review_feedback=[],
    )


def config(**updates: Any) -> ProcedureSearchConfig:
    values: dict[str, Any] = {
        "api_key": "test-kakao-rest-key",
        "allowed_domains": ("gov.kr", "nts.go.kr"),
        "timeout_seconds": 2,
        "max_retries": 0,
        "retry_backoff_seconds": 0,
        "max_response_bytes": 20_000,
        "max_redirects": 3,
    }
    values.update(updates)
    return ProcedureSearchConfig(**values)


def uuids(*values: UUID):
    iterator = iter(values)
    return lambda: next(iterator)


def search_response(*documents: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "meta": {
                "total_count": len(documents),
                "pageable_count": len(documents),
                "is_end": True,
            },
            "documents": list(documents),
        },
    )


def official_html(
    body: str = "사업자는 폐업 신고서를 제출하고 신고 사실을 확인해야 합니다.",
    *,
    title: str = "폐업 신고 안내",
) -> httpx.Response:
    return httpx.Response(
        200,
        content=(
            "<!doctype html><html><head>"
            f"<title>{title}</title><script>ignore me</script></head>"
            '<body><noscript><img src="tracking.gif"></noscript>'
            f'<form><input value="must-not-copy-attribute"></form>'
            f"<main><h1>{title}</h1><p>{body}</p></main></body></html>"
        ).encode(),
        headers={"content-type": "text/html; charset=utf-8"},
    )


def test_kakao_query_header_and_official_fetch_create_evidence() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        if request.url.host == "dapi.kakao.com":
            return search_response(
                {
                    "title": "<b>검색 snippet 제목</b>",
                    "contents": "이 검색 snippet은 Evidence가 아니어야 합니다.",
                    "url": "https://www.gov.kr/closure/guide",
                    "datetime": "2026-09-15T00:00:00.000+09:00",
                }
            )
        assert request.headers.get("authorization") is None
        return official_html("공식 원문에 적힌 폐업 신고 절차입니다.")

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
            uuid_factory=uuids(DOCUMENT_ID, LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(lookup_request(max_results=7))

        assert result.completion_status == "COMPLETE"
        assert result.lookup_id == LOOKUP_ID
        assert result.based_on_snapshot_id == SNAPSHOT_ID
        assert len(result.documents) == 1
        document = result.documents[0]
        assert document.document_id == DOCUMENT_ID
        assert document.title == "폐업 신고 안내"
        assert document.authority_name == "정부24"
        assert document.canonical_url == "https://www.gov.kr/closure/guide"
        assert document.source_domain == "www.gov.kr"
        assert "공식 원문에 적힌" in document.excerpt
        assert "검색 snippet은" not in document.excerpt
        assert "must-not-copy-attribute" not in document.excerpt
        assert document.freshness_status == "UNKNOWN"
        assert document.published_at is None
        assert document.retrieved_at == NOW
        assert document.evidence_ref == result.evidence_records[0].evidence_id
        assert result.evidence_records[0].source_ref == document.canonical_url
        assert result.evidence_records[0].source_type == "OFFICIAL_DOCUMENT"

        search_request, fetch_request = observed
        assert str(search_request.url).startswith(DEFAULT_SEARCH_ENDPOINT)
        assert search_request.headers["authorization"] == "KakaoAK test-kakao-rest-key"
        assert search_request.url.params["query"] == "개인사업자 폐업 신고 절차"
        assert search_request.url.params["size"] == "7"
        assert search_request.url.params["page"] == "1"
        assert search_request.url.params["sort"] == "accuracy"
        assert fetch_request.url == httpx.URL("https://www.gov.kr/closure/guide")

    asyncio.run(scenario())


def test_long_navigation_does_not_hide_query_relevant_official_text() -> None:
    navigation = "사업자 메뉴 항목 " * 500
    relevant = "사업자는 휴게음식점 폐업 신고서를 관할 기관에 제출합니다."

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dapi.kakao.com":
            return search_response(
                {
                    "title": "공식 안내",
                    "contents": "",
                    "url": "https://www.gov.kr/long-guide",
                }
            )
        return official_html(navigation + relevant)

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        ) as tool:
            result = await tool.lookup(
                lookup_request(queries=["휴게음식점 폐업 신고 절차 정부24"])
            )

        assert relevant in result.documents[0].excerpt
        assert len(result.documents[0].excerpt) <= 4_000

    asyncio.run(scenario())


def test_deceptive_non_official_urls_are_never_fetched() -> None:
    fetched_hosts: list[str] = []
    urls = [
        "https://www.gov.kr.evil.example/guide",
        "https://evilgov.kr/guide",
        "http://www.gov.kr/guide",
        "https://127.0.0.1/guide",
        "https://user:password@www.gov.kr/guide",
        "https://www.gov.kr:444/guide",
        "https://www.gov.kr/guide?serviceKey=do-not-leak",
        "https://www.gov.kr/valid-guide",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dapi.kakao.com":
            return search_response(
                *(
                    {"title": f"결과 {index}", "contents": "", "url": url}
                    for index, url in enumerate(urls)
                )
            )
        fetched_hosts.append(request.url.host or "")
        assert request.url.path == "/valid-guide"
        return official_html()

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
            uuid_factory=uuids(DOCUMENT_ID, LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(lookup_request(max_results=10))
        assert result.completion_status == "COMPLETE"
        assert fetched_hosts == ["www.gov.kr"]
        assert result.search_summary.provider_result_count == len(urls)
        assert result.search_summary.official_candidate_count == 1
        assert result.search_summary.rejected_result_count == len(urls) - 1
        assert {warning.code for warning in result.warnings} == {"RESULT_REJECTED"}

    asyncio.run(scenario())


def test_each_redirect_hop_is_validated_and_final_url_is_recorded() -> None:
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dapi.kakao.com":
            return search_response(
                {
                    "title": "국세청 안내",
                    "contents": "",
                    "url": "https://www.gov.kr/start",
                }
            )
        fetched.append(str(request.url))
        if request.url.host == "www.gov.kr":
            return httpx.Response(
                302,
                headers={"location": "https://www.nts.go.kr/final?utm_source=kakao"},
            )
        return official_html(
            "국세청 공식 폐업 안내 원문입니다.", title="국세청 폐업 안내"
        )

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
            uuid_factory=uuids(DOCUMENT_ID, LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(lookup_request())
        assert fetched == [
            "https://www.gov.kr/start",
            "https://www.nts.go.kr/final",
        ]
        assert result.documents[0].canonical_url == "https://www.nts.go.kr/final"
        assert result.documents[0].authority_name == "국세청"

    asyncio.run(scenario())


def test_injected_client_cannot_follow_redirect_or_leak_default_credentials() -> None:
    observed_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_hosts.append(request.url.host or "")
        assert request.headers.get("cookie") is None
        if request.url.host == "dapi.kakao.com":
            assert request.headers["authorization"] == "KakaoAK test-kakao-rest-key"
            return search_response(
                {
                    "title": "공식 후보",
                    "contents": "",
                    "url": "https://www.gov.kr/start",
                }
            )
        if request.url.host == "www.gov.kr":
            assert request.headers.get("authorization") is None
            return httpx.Response(
                302,
                headers={"location": "https://evil.example/credential-target"},
            )
        raise AssertionError("a non-official redirect target must never be fetched")

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
            headers={
                "Authorization": "Bearer injected-default",
                "Cookie": "session=must-not-leak",
            },
        ) as client:
            tool = ProcedureLookupTool(config(), client=client, clock=lambda: NOW)
            result = await tool.lookup(lookup_request())
            await tool.aclose()

        assert result.completion_status == "PARTIAL"
        assert result.documents == []
        assert result.evidence_records == []
        assert result.search_summary.fetch_failure_count == 1
        assert observed_hosts == ["dapi.kakao.com", "www.gov.kr"]

    asyncio.run(scenario())


def test_redirect_to_non_official_host_yields_partial_without_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dapi.kakao.com":
            return search_response(
                {
                    "title": "검색 결과",
                    "contents": "",
                    "url": "https://www.gov.kr/start",
                }
            )
        return httpx.Response(
            302,
            headers={"location": "https://www.gov.kr.evil.example/phishing"},
        )

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
            uuid_factory=uuids(LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(lookup_request())
        assert result.completion_status == "PARTIAL"
        assert result.documents == []
        assert result.evidence_records == []
        assert result.search_summary.fetch_failure_count == 1
        assert {warning.code for warning in result.warnings} == {
            "SOURCE_FETCH_FAILED",
            "NO_FETCHED_DOCUMENTS",
        }

    asyncio.run(scenario())


def test_canonical_url_dedupes_tracking_and_fragment_variants() -> None:
    fetch_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal fetch_count
        if request.url.host == "dapi.kakao.com":
            return search_response(
                {
                    "title": "첫 결과",
                    "contents": "",
                    "url": "https://www.gov.kr/guide?a=1&utm_source=kakao#part",
                },
                {
                    "title": "중복 결과",
                    "contents": "",
                    "url": "https://www.gov.kr/guide?a=1&utm_medium=search",
                },
                {
                    "title": "표준 포트 중복 결과",
                    "contents": "",
                    "url": "https://www.gov.kr:443/guide?a=1#top",
                },
            )
        fetch_count += 1
        assert str(request.url) == "https://www.gov.kr/guide?a=1"
        return official_html()

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
            uuid_factory=uuids(DOCUMENT_ID, LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(lookup_request())
        assert fetch_count == 1
        assert len(result.documents) == 1
        assert result.search_summary.official_candidate_count == 3
        assert result.search_summary.fetched_document_count == 1

    asyncio.run(scenario())


def test_content_hash_uses_fetched_bytes_and_runtime_clock() -> None:
    raw = (
        "<html><head><title>공식 문서</title></head>"
        "<body><p>폐업 신고 원문</p></body></html>"
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dapi.kakao.com":
            return search_response(
                {
                    "title": "검색 제목",
                    "contents": "조작 가능 snippet",
                    "url": "https://www.gov.kr/hash",
                }
            )
        return httpx.Response(
            200,
            content=raw,
            headers={"content-type": "text/html"},
        )

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
            uuid_factory=uuids(DOCUMENT_ID, LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(lookup_request())
        expected = "sha256:" + hashlib.sha256(raw).hexdigest()
        assert result.documents[0].content_hash == expected
        assert result.evidence_records[0].content_hash == expected
        assert result.evidence_records[0].source_version == expected
        assert result.documents[0].retrieved_at == NOW

    asyncio.run(scenario())


def test_successful_lookup_with_no_official_candidate_is_no_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "dapi.kakao.com"
        return search_response(
            {
                "title": "개인 블로그",
                "contents": "",
                "url": "https://blog.example.com/closure",
            }
        )

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
            uuid_factory=uuids(LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(lookup_request())
        assert result.completion_status == "NO_RESULTS"
        assert result.documents == []
        assert result.search_summary.failed_query_count == 0
        assert result.search_summary.official_candidate_count == 0
        assert {warning.code for warning in result.warnings} == {
            "RESULT_REJECTED",
            "NO_OFFICIAL_RESULTS",
        }

    asyncio.run(scenario())


def test_one_failed_query_and_one_fetched_document_is_partial() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dapi.kakao.com":
            if request.url.params["query"] == "실패 검색":
                return httpx.Response(401, json={"message": "unauthorized"})
            return search_response(
                {
                    "title": "공식 안내",
                    "contents": "",
                    "url": "https://www.gov.kr/guide",
                }
            )
        return official_html()

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
            uuid_factory=uuids(DOCUMENT_ID, LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(
                lookup_request(queries=["실패 검색", "성공 검색"])
            )
        assert result.completion_status == "PARTIAL"
        assert result.search_summary.successful_query_count == 1
        assert result.search_summary.failed_query_count == 1
        assert len(result.documents) == 1
        assert {warning.code for warning in result.warnings} == {"SEARCH_QUERY_FAILED"}

    asyncio.run(scenario())


def test_provider_cannot_expand_fetches_beyond_requested_result_limit() -> None:
    fetched_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dapi.kakao.com":
            return search_response(
                *(
                    {
                        "title": f"공식 후보 {index}",
                        "contents": "",
                        "url": f"https://www.gov.kr/closure/{index}",
                    }
                    for index in range(7)
                )
            )
        fetched_paths.append(request.url.path)
        return official_html()

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        ) as tool:
            result = await tool.lookup(lookup_request(max_results=2))

        assert len(result.documents) == 2
        assert result.search_summary.provider_result_count == 7
        assert result.search_summary.official_candidate_count == 2
        assert result.search_summary.rejected_result_count == 5
        assert fetched_paths == ["/closure/0", "/closure/1"]

    asyncio.run(scenario())


def test_all_search_queries_failing_is_typed_request_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "temporary"})

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        ) as tool:
            with pytest.raises(ProcedureLookupRequestError) as raised:
                await tool.lookup(lookup_request(queries=["검색 1", "검색 2"]))
        assert raised.value.code == "SEARCH_UNAVAILABLE"
        assert raised.value.retryable is True
        assert "test-kakao-rest-key" not in str(raised.value)

    asyncio.run(scenario())


def test_oversized_search_body_is_stopped_before_json_parse_or_fetch() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=b"x" * 2_000,
            headers={"content-type": "application/json"},
        )

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(max_response_bytes=1_024),
            transport=httpx.MockTransport(handler),
        ) as tool:
            with pytest.raises(ProcedureLookupRequestError) as captured:
                await tool.lookup(lookup_request())

        assert captured.value.code == "SEARCH_UNAVAILABLE"
        assert captured.value.retryable is False
        assert calls == 1

    asyncio.run(scenario())


def test_transient_search_failure_retries_with_bounded_backoff() -> None:
    search_calls = 0
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal search_calls
        if request.url.host == "dapi.kakao.com":
            search_calls += 1
            if search_calls == 1:
                return httpx.Response(503, json={"message": "temporary"})
            return search_response(
                {
                    "title": "공식 안내",
                    "contents": "",
                    "url": "https://www.gov.kr/retry",
                }
            )
        return official_html()

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(max_retries=1, retry_backoff_seconds=0.5),
            transport=httpx.MockTransport(handler),
            sleep=sleep,
            clock=lambda: NOW,
            uuid_factory=uuids(DOCUMENT_ID, LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(lookup_request())
        assert result.completion_status == "COMPLETE"
        assert search_calls == 2
        assert sleeps == [0.5]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "official_response",
    [
        httpx.Response(
            200,
            content=b"not a supported document",
            headers={"content-type": "application/pdf"},
        ),
        httpx.Response(
            200,
            content=b"x" * 2_000,
            headers={"content-type": "text/plain", "content-length": "2000"},
        ),
    ],
)
def test_unsupported_or_oversized_source_never_becomes_evidence(
    official_response: httpx.Response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dapi.kakao.com":
            return search_response(
                {
                    "title": "공식 자료",
                    "contents": "",
                    "url": "https://www.gov.kr/source",
                }
            )
        return official_response

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(max_response_bytes=1_024),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
            uuid_factory=uuids(LOOKUP_ID),
        ) as tool:
            result = await tool.lookup(lookup_request())
        assert result.completion_status == "PARTIAL"
        assert result.documents == []
        assert result.evidence_records == []
        assert result.search_summary.fetch_failure_count == 1

    asyncio.run(scenario())


def test_config_prefers_procedure_key_and_repr_hides_both_key_names(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "missing.env"
    configured = ProcedureSearchConfig.from_env(
        env_file=env_file,
        environ={
            "PROCEDURE_SEARCH_API_KEY": "primary-secret",
            "KAKAO_CLIENT_ID": "fallback-secret",
        },
    )
    assert configured.api_key == "primary-secret"
    assert configured.endpoint == DEFAULT_SEARCH_ENDPOINT
    assert "primary-secret" not in repr(configured)
    assert "fallback-secret" not in repr(configured)


def test_config_falls_back_to_kakao_client_id(tmp_path: Path) -> None:
    configured = ProcedureSearchConfig.from_env(
        env_file=tmp_path / "missing.env",
        environ={"KAKAO_CLIENT_ID": "fallback-key"},
    )
    assert configured.api_key == "fallback-key"


def test_config_rejects_missing_key_and_unsafe_endpoint(tmp_path: Path) -> None:
    with pytest.raises(ProcedureSearchConfigurationError):
        ProcedureSearchConfig.from_env(
            env_file=tmp_path / "missing.env",
            environ={},
        )
    with pytest.raises(ProcedureSearchConfigurationError):
        ProcedureSearchConfig(
            api_key="secret",
            endpoint="http://dapi.kakao.com/v2/search/web",
        )
    with pytest.raises(ProcedureSearchConfigurationError):
        ProcedureSearchConfig(
            api_key="secret",
            endpoint="https://attacker.example/v2/search/web",
        )
    for unsafe_domain in ("localhost", "com", "co.kr", "or.kr"):
        with pytest.raises(ProcedureSearchConfigurationError, match="public suffix"):
            ProcedureSearchConfig(
                api_key="secret",
                allowed_domains=(unsafe_domain,),
            )
    with pytest.raises(ProcedureSearchConfigurationError, match="reviewed registry"):
        ProcedureSearchConfig(
            api_key="secret",
            allowed_domains=("official-looking.example",),
        )
    for invalid_domain in ("*.gov.kr", "-bad.gov.kr", "bad-.gov.kr"):
        with pytest.raises(ProcedureSearchConfigurationError):
            ProcedureSearchConfig(
                api_key="secret",
                allowed_domains=(invalid_domain,),
            )

    narrowed = ProcedureSearchConfig(
        api_key="secret",
        allowed_domains=("www.gov.kr", "custom.nts.go.kr"),
    )
    assert narrowed.allowed_domains == ("www.gov.kr", "custom.nts.go.kr")

    for field, value in (
        ("timeout_seconds", float("nan")),
        ("total_timeout_seconds", float("inf")),
        ("retry_backoff_seconds", float("nan")),
    ):
        with pytest.raises(ProcedureSearchConfigurationError, match="finite"):
            ProcedureSearchConfig(api_key="secret", **{field: value})


def test_total_lookup_timeout_fails_closed_with_typed_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return search_response()

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(total_timeout_seconds=0.005),
            transport=httpx.MockTransport(handler),
        ) as tool:
            with pytest.raises(ProcedureLookupRequestError) as captured:
                await tool.lookup(lookup_request())

        assert captured.value.code == "LOOKUP_TIMEOUT"
        assert captured.value.retryable is True

    asyncio.run(scenario())


def test_sensitive_search_query_is_rejected_before_network_call() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return search_response()

    async def scenario() -> None:
        async with ProcedureLookupTool(
            config(), transport=httpx.MockTransport(handler)
        ) as tool:
            with pytest.raises(ProcedureLookupInputError) as raised:
                await tool.lookup(
                    lookup_request(queries=["폐업 sk-sensitivecredential123456"])
                )
        assert raised.value.code == "INVALID_INPUT"
        assert calls == 0

    asyncio.run(scenario())


def test_tool_closes_only_the_client_it_owns() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return search_response()

    async def scenario() -> None:
        external = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        tool_with_external_client = ProcedureLookupTool(config(), client=external)
        await tool_with_external_client.aclose()
        assert external.is_closed is False
        await external.aclose()

        owned_tool = ProcedureLookupTool(
            config(), transport=httpx.MockTransport(handler)
        )
        async with owned_tool:
            assert owned_tool._client.is_closed is False
        assert owned_tool._client.is_closed is True

    asyncio.run(scenario())
