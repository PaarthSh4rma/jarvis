import asyncio

import httpx
import pytest
from pydantic import SecretStr

from jarvis_api.integrations.hermes import HermesAdapter, validate_base_url

HEALTH = {"status": "ok", "platform": "hermes-agent", "version": "0.9.0"}
FEATURES = {
    "run_submission": True,
    "run_status": True,
    "run_events_sse": True,
    "run_stop": True,
    "run_approval_response": True,
    "session_resources": False,
}
CAPABILITIES = {
    "object": "hermes.api_server.capabilities",
    "platform": "hermes-agent",
    "features": FEATURES,
    "private_metadata": "not for JARVIS",
}


def test_online_health_and_capabilities_are_sanitized_gets():
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        if request.url.path == "/health":
            assert "authorization" not in request.headers
            return httpx.Response(200, json=HEALTH)
        assert request.url.path == "/v1/capabilities"
        assert request.headers["authorization"] == "Bearer test-only-token"
        return httpx.Response(200, json=CAPABILITIES)

    adapter = HermesAdapter(
        api_key=SecretStr("test-only-token"), transport=httpx.MockTransport(respond)
    )
    health = asyncio.run(adapter.health())
    capabilities = asyncio.run(adapter.capabilities())
    assert health.state == "ONLINE"
    assert health.version == "0.9.0"
    assert health.last_successful_check is not None
    assert capabilities.state == "ONLINE"
    assert capabilities.capabilities == list(FEATURES)[:-1]
    assert "private_metadata" not in capabilities.model_dump_json()
    assert "test-only-token" not in capabilities.model_dump_json()
    assert len(requests) == 2


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_offline_and_timeout(error):
    def respond(request):
        raise error("sensitive upstream details", request=request)

    status = asyncio.run(HermesAdapter(transport=httpx.MockTransport(respond)).health())
    assert status.state == "OFFLINE"
    assert "sensitive" not in status.model_dump_json()


def test_total_deadline():
    async def respond(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=HEALTH)

    adapter = HermesAdapter(transport=httpx.MockTransport(respond), total_timeout=0.01)
    assert asyncio.run(adapter.health()).state == "OFFLINE"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**HEALTH, "platform": "other"},
        {**HEALTH, "version": "secret value\n"},
        {**HEALTH, "status": "error"},
        [],
    ],
)
def test_invalid_health_never_reports_online(payload):
    adapter = HermesAdapter(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    assert asyncio.run(adapter.health()).state == "DEGRADED"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"x" * 100, headers={"Content-Type": "application/json"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, content=b"{", headers={"Content-Type": "application/json"}),
    ],
)
def test_bounded_or_malformed_response(response):
    adapter = HermesAdapter(
        transport=httpx.MockTransport(lambda _: response), max_response_bytes=50
    )
    assert asyncio.run(adapter.health()).state == "DEGRADED"


def test_capability_boolean_validation():
    payload = {**CAPABILITIES, "features": {**FEATURES, "run_submission": "true"}}
    adapter = HermesAdapter(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    assert asyncio.run(adapter.capabilities()).state == "DEGRADED"


@pytest.mark.parametrize(
    "code,state,reason",
    [
        (401, "UNKNOWN", "authentication_required"),
        (403, "UNKNOWN", "authentication_required"),
        (500, "DEGRADED", "http_error"),
        (302, "DEGRADED", "http_error"),
    ],
)
def test_safe_http_errors_and_no_redirects(code, state, reason):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(code, headers={"Location": "https://example.invalid"})

    status = asyncio.run(HermesAdapter(transport=httpx.MockTransport(respond)).capabilities())
    assert (status.state, status.reason) == (state, reason)
    assert len(requests) == 1


def test_last_success_survives_outage_without_stale_online_state():
    replies = iter([httpx.Response(200, json=HEALTH), httpx.Response(503)])
    adapter = HermesAdapter(transport=httpx.MockTransport(lambda _: next(replies)))
    first = asyncio.run(adapter.health())
    second = asyncio.run(adapter.health())
    assert second.state == "DEGRADED"
    assert second.version is None
    assert second.last_successful_check == first.last_successful_check


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://192.168.1.1:8642",
        "http://127.0.0.1.evil:8642",
        "http://user:password@localhost:8642",
        "http://localhost:8642/path",
        "http://localhost:8642?token=x",
        "file:///tmp/hermes",
        "http://localhost:99999",
    ],
)
def test_non_loopback_and_credential_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_localhost_is_pinned_to_loopback():
    assert validate_base_url("http://localhost:8642/") == "http://127.0.0.1:8642"


def test_zero_port_is_rejected():
    with pytest.raises(ValueError):
        validate_base_url("http://localhost:0")


def test_stream_overflow_stops_reading_and_closes():
    class Body(httpx.AsyncByteStream):
        closed = False
        chunks_read = 0

        async def __aiter__(self):
            for _ in range(100):
                self.chunks_read += 1
                yield b"x" * 16

        async def aclose(self):
            self.closed = True

    body = Body()
    adapter = HermesAdapter(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=body, headers={"Content-Type": "application/json"})
        ),
        max_response_bytes=32,
    )
    assert asyncio.run(adapter.health()).state == "DEGRADED"
    assert body.chunks_read == 3
    assert body.closed


def test_slow_body_is_timed_out_and_closed():
    class SlowBody(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'{"status":'
            await asyncio.sleep(1)
            yield b'"ok"}'

        async def aclose(self):
            self.closed = True

    body = SlowBody()
    adapter = HermesAdapter(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                stream=body,
                headers={"Content-Type": "application/json"},
            )
        ),
        total_timeout=0.01,
    )
    assert asyncio.run(adapter.health()).state == "OFFLINE"
    assert body.closed


def test_hostile_extra_fields_are_discarded(caplog):
    hostile = "<script>private-upstream-value</script>\nFORGED LOG"
    payload = {**HEALTH, "credentials": hostile, "endpoints": {"execute": hostile}}
    adapter = HermesAdapter(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    status = asyncio.run(adapter.health())
    assert status.state == "ONLINE"
    assert hostile not in status.model_dump_json()
    assert "private-upstream-value" not in caplog.text


def test_ipv6_loopback_and_environment_proxy_isolation(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:1234")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:1234")
    seen = []
    client_type = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        assert kwargs["timeout"].connect == 1
        assert kwargs["timeout"].read == 2
        return client_type(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    def respond(request):
        seen.append(request.url.host)
        return httpx.Response(200, json=HEALTH)

    adapter = HermesAdapter(
        "http://[::1]:8642",
        transport=httpx.MockTransport(respond),
    )
    assert asyncio.run(adapter.health()).state == "ONLINE"
    assert seen == ["::1"]


def test_huge_default_limit_response_is_rejected():
    adapter = HermesAdapter(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={**HEALTH, "extra": "x" * 1000000})
        )
    )
    assert asyncio.run(adapter.health()).state == "DEGRADED"
