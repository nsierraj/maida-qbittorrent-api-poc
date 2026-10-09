"""The MCP server over streamable HTTP (container mode): a real uvicorn server against the fake."""

from contextlib import asynccontextmanager

import anyio
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from qbittorrent_mcp.server import HttpConfig, http_app, http_server, transport_from_env

from .fake_qbt import API_KEY
from .test_mcp_server import READ_TOOLS, make_server, payload

httpx = pytest.importorskip("httpx2")

TOKEN = "t" * 40


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def serving(server):
    config = HttpConfig(token=TOKEN, port=0)
    srv = http_server(http_app(server, config), config)
    async with anyio.create_task_group() as tg:
        tg.start_soon(srv.serve)
        while not srv.started:
            await anyio.sleep(0.01)
        port = srv.servers[0].sockets[0].getsockname()[1]
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            srv.should_exit = True


@pytest.mark.anyio
async def test_requests_without_the_token_are_refused(qbt):
    async with serving(make_server()) as base, httpx.AsyncClient() as http:
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        assert (await http.post(f"{base}/mcp", json=init)).status_code == 401
        wrong = await http.post(f"{base}/mcp", json=init, headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401 and wrong.headers["www-authenticate"] == "Bearer"
        # The qBittorrent API key is not an MCP token.
        key = await http.post(f"{base}/mcp", json=init, headers={"Authorization": f"Bearer {API_KEY}"})
        assert key.status_code == 401
        health = await http.get(f"{base}/healthz")
        assert health.status_code == 200 and health.text == "ok"


@pytest.mark.anyio
async def test_tools_work_with_the_token(qbt):
    async with serving(make_server()) as base:
        http = httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"})
        async with http, Client(streamable_http_client(f"{base}/mcp", http_client=http)) as c:
            assert {t.name for t in (await c.list_tools()).tools} == READ_TOOLS
            info = payload(await c.call_tool("qbt_server_info", {}))
            assert info["qbittorrent_version"] == "v5.2.3"


def test_http_config_needs_a_long_token(monkeypatch):
    monkeypatch.setenv("QBT_MCP_TOKEN", "short")
    with pytest.raises(SystemExit, match="QBT_MCP_TOKEN"):
        HttpConfig.from_env()
    monkeypatch.setenv("QBT_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("QBT_MCP_HOST", "0.0.0.0")
    monkeypatch.delenv("QBT_MCP_PORT", raising=False)
    config = HttpConfig.from_env()
    assert (config.host, config.port) == ("0.0.0.0", 8000)
    assert TOKEN not in repr(config)
    monkeypatch.setenv("QBT_MCP_PORT", "eighty")
    with pytest.raises(SystemExit, match="QBT_MCP_PORT"):
        HttpConfig.from_env()


def test_transport_defaults_to_stdio(monkeypatch):
    monkeypatch.delenv("QBT_MCP_TRANSPORT", raising=False)
    assert transport_from_env() == "stdio"
    monkeypatch.setenv("QBT_MCP_TRANSPORT", " HTTP ")
    assert transport_from_env() == "http"
    monkeypatch.setenv("QBT_MCP_TRANSPORT", "sse")
    with pytest.raises(SystemExit):
        transport_from_env()
