"""Small, read-only client for the locally verified Hermes gateway API."""

import asyncio
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

HermesState = Literal["ONLINE", "OFFLINE", "DEGRADED", "UNKNOWN"]
Capability = Literal[
    "run_submission",
    "run_status",
    "run_events_sse",
    "run_stop",
    "run_approval_response",
    "session_resources",
]
CAPABILITIES = (
    "run_submission",
    "run_status",
    "run_events_sse",
    "run_stop",
    "run_approval_response",
    "session_resources",
)


def validate_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Hermes requires a loopback HTTP origin without credentials or a path")
    port = parsed.port if parsed.port is not None else 8642
    if not 1 <= port <= 65535:
        raise ValueError("Invalid Hermes port")
    # Pin localhost to a literal address; do not trust DNS or environment proxies.
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}"


class HermesStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: HermesState
    version: str | None = None
    capabilities: list[Capability] = Field(default_factory=list, max_length=6)
    checked_at: datetime
    last_successful_check: datetime | None = None
    reason: Literal[
        "verified", "unavailable", "authentication_required", "invalid_response", "http_error"
    ]


class HealthPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    status: Literal["ok"]
    platform: Literal["hermes-agent"]
    version: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9.+_-]+$")


class Features(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    run_submission: bool
    run_status: bool
    run_events_sse: bool
    run_stop: bool
    run_approval_response: bool
    session_resources: bool


class CapabilitiesPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    object: Literal["hermes.api_server.capabilities"]
    platform: Literal["hermes-agent"]
    features: Features


class HermesAdapter:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8642",
        api_key: SecretStr | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_response_bytes: int = 65536,
        total_timeout: float = 4,
    ) -> None:
        self.base_url = validate_base_url(base_url)
        self._api_key = api_key
        self._transport = transport
        self._max_response_bytes = max_response_bytes
        self._total_timeout = total_timeout
        self._last_success: dict[str, datetime] = {}

    async def health(self) -> HermesStatus:
        return await self._query("/health")

    async def capabilities(self) -> HermesStatus:
        return await self._query("/v1/capabilities")

    async def _query(self, path: str) -> HermesStatus:
        state: HermesState = "UNKNOWN"
        reason = "invalid_response"
        version = None
        capabilities = []
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if path != "/health" and self._api_key and self._api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {self._api_key.get_secret_value()}"
        try:
            async with asyncio.timeout(self._total_timeout):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(2, connect=1),
                ) as client:
                    async with client.stream("GET", self.base_url + path, headers=headers) as r:
                        if r.status_code in {401, 403}:
                            state, reason = "UNKNOWN", "authentication_required"
                        elif r.status_code != 200:
                            state, reason = "DEGRADED", "http_error"
                        else:
                            if r.headers.get("content-encoding", "identity") != "identity":
                                raise ValueError("Encoded responses are not supported")
                            if (
                                r.headers.get("content-type", "").split(";")[0]
                                != "application/json"
                            ):
                                raise ValueError("Expected JSON")
                            body = bytearray()
                            async for chunk in r.aiter_bytes():
                                if len(body) + len(chunk) > self._max_response_bytes:
                                    raise ValueError("Response exceeds limit")
                                body.extend(chunk)
                            if path == "/health":
                                version = HealthPayload.model_validate_json(bytes(body)).version
                            else:
                                payload = CapabilitiesPayload.model_validate_json(bytes(body))
                                capabilities = [
                                    name for name in CAPABILITIES if getattr(payload.features, name)
                                ]
                            state, reason = "ONLINE", "verified"
                            self._last_success[path] = datetime.now(UTC)
        except (httpx.TransportError, TimeoutError):
            state, reason = "OFFLINE", "unavailable"
        except (ValidationError, ValueError):
            state, reason = "DEGRADED", "invalid_response"
        return HermesStatus(
            state=state,
            reason=reason,
            version=version,
            capabilities=capabilities,
            checked_at=datetime.now(UTC),
            last_successful_check=self._last_success.get(path),
        )
