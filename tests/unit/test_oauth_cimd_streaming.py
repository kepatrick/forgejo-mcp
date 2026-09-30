import gzip

import httpx
import pytest
from mcp.server.auth.provider import RegistrationError

from forgejo_mcp.application.oauth_service import OAuthService
from forgejo_mcp.config import Settings


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def service_for(stream: TrackedStream, headers: dict[str, str]) -> OAuthService:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200, headers={"content-type": "application/json", **headers}, stream=stream
        )

    return OAuthService(
        lambda: None,
        Settings(
            oauth_enabled=True,
            oauth_issuer_url="https://mcp.example.test",
            oauth_resource_url="https://mcp.example.test/mcp",
        ),
        transport=httpx.MockTransport(handler),
        resolver=lambda host, port: {"93.184.216.34"},
    )


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "gzip, identity"])
async def test_compressed_cimd_is_rejected_without_reading_or_decoding(encoding: str) -> None:
    stream = TrackedStream([gzip.compress(b" " * (8 * 1024 * 1024))])
    service = service_for(stream, {"content-encoding": encoding})
    with pytest.raises(RegistrationError, match="compressed CIMD"):
        await service._fetch_cimd("https://client.example/client.json")
    assert stream.reads == 0
    assert stream.closed


@pytest.mark.parametrize("headers", [{}, {"content-length": "1"}])
async def test_cimd_actual_stream_size_is_bounded_without_trusting_length(headers) -> None:
    stream = TrackedStream([b" " * 65536, b"x", b"must not read"])
    with pytest.raises(RegistrationError, match="too large"):
        await service_for(stream, headers)._fetch_cimd("https://client.example/client.json")
    assert stream.reads == 2
    assert stream.closed


@pytest.mark.parametrize("size", [1024, 65536])
async def test_cimd_accepts_valid_json_up_to_exact_limit(size: int) -> None:
    body = (
        b'{"client_id":"https://client.example/client.json",'
        b'"redirect_uris":["https://client.example/callback"],'
        b'"token_endpoint_auth_method":"none",'
        b'"grant_types":["authorization_code","refresh_token"],"response_types":["code"]}'
    )
    stream = TrackedStream([body, b" " * (size - len(body))])
    client = await service_for(stream, {})._fetch_cimd("https://client.example/client.json")
    assert client.client_id == "https://client.example/client.json"
    assert stream.closed
