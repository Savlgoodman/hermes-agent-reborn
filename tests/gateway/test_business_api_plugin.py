import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import cors_middleware, security_headers_middleware
from tests.gateway._plugin_adapter_loader import load_plugin_adapter


_business_mod = load_plugin_adapter("business_api")
BusinessAPIAdapter = _business_mod.BusinessAPIAdapter


def _make_adapter(tmp_path: Path, *, api_key: str = "sk-business-secret") -> BusinessAPIAdapter:
    return BusinessAPIAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "key": api_key,
                "workspace_root": str(tmp_path),
                "max_upload_bytes": 2 * 1024 * 1024,
            },
        )
    )


def _create_app(adapter: BusinessAPIAdapter) -> web.Application:
    mws = [mw for mw in (cors_middleware, security_headers_middleware) if mw is not None]
    app = web.Application(middlewares=mws, client_max_size=adapter._max_upload_bytes)
    app["api_server_adapter"] = adapter
    app.router.add_post("/v1/responses", adapter._handle_responses)
    app.router.add_get("/api/responses/{response_id}/context", adapter._handle_response_context)
    app.router.add_post("/api/files", adapter._handle_file_upload)
    return app


def _auth_headers(token: str = "sk-business-secret") -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_responses_returns_extended_usage_and_context(tmp_path):
    adapter = _make_adapter(tmp_path)
    app = _create_app(adapter)

    fake_db = MagicMock()
    fake_db.get_session.return_value = {
        "id": "sid-1",
        "model": "model-from-session",
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_tokens": 300,
        "cache_write_tokens": 40,
        "reasoning_tokens": 12,
        "api_call_count": 3,
        "estimated_cost_usd": 0.123,
        "cost_status": "estimated",
        "cost_source": "official_docs_snapshot",
        "billing_provider": "openai",
        "billing_base_url": "https://api.openai.com/v1",
    }

    async with TestClient(TestServer(app)) as cli:
        with (
            patch.object(adapter, "_ensure_session_db", return_value=fake_db),
            patch.object(adapter, "_create_agent") as mock_create_agent,
        ):
            mock_agent = MagicMock()
            mock_agent.session_id = "sid-1"
            mock_agent.session_prompt_tokens = 135
            mock_agent.session_completion_tokens = 20
            mock_agent.session_total_tokens = 155
            mock_agent.run_conversation.return_value = {
                "final_response": "done",
                "messages": [{"role": "assistant", "content": "done"}],
                "completed": True,
                "model": "gpt-test",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_tokens": 30,
                "cache_write_tokens": 5,
                "reasoning_tokens": 7,
                "prompt_tokens": 135,
                "completion_tokens": 20,
                "total_tokens": 155,
            }
            mock_create_agent.return_value = mock_agent

            resp = await cli.post(
                "/v1/responses",
                json={"input": "hello"},
                headers=_auth_headers(),
            )
            assert resp.status == 200
            data = await resp.json()

            assert data["usage"]["input_tokens"] == 100
            assert data["usage"]["output_tokens"] == 20
            assert data["usage"]["cache_read_tokens"] == 30
            assert data["usage"]["cache_write_tokens"] == 5
            assert data["usage"]["reasoning_tokens"] == 7
            assert data["usage"]["total_tokens"] == 155

            ctx_resp = await cli.get(
                f"/api/responses/{data['id']}/context",
                headers=_auth_headers(),
            )
            assert ctx_resp.status == 200
            ctx = await ctx_resp.json()

    assert ctx["response_id"] == data["id"]
    assert ctx["session_id"] == "sid-1"
    assert ctx["model"] == "model-from-session"
    assert ctx["response_model"] == data["model"]
    assert ctx["usage"]["turn"]["cache_read_tokens"] == 30
    assert ctx["usage"]["session_total"]["cache_write_tokens"] == 40
    assert ctx["usage"]["session_total"]["total_tokens"] == 1540
    assert ctx["messages"][0]["role"] == "user"
    assert ctx["messages"][-1]["content"] == "done"


@pytest.mark.asyncio
async def test_context_requires_business_api_key(tmp_path):
    adapter = _make_adapter(tmp_path)
    adapter._response_store.put(
        "resp_test",
        {
            "response": {"id": "resp_test", "object": "response", "status": "completed"},
            "conversation_history": [],
            "session_id": "sid-1",
        },
    )
    app = _create_app(adapter)

    async with TestClient(TestServer(app)) as cli:
        resp = await cli.get("/api/responses/resp_test/context")
        assert resp.status == 401


@pytest.mark.asyncio
async def test_file_upload_writes_inside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    adapter = _make_adapter(workspace)
    app = _create_app(adapter)

    form = FormData()
    form.add_field("target_path", "docs")
    form.add_field("conversation_id", "conv-1")
    form.add_field(
        "file",
        b"hello business file",
        filename="report.txt",
        content_type="text/plain",
    )

    async with TestClient(TestServer(app)) as cli:
        resp = await cli.post("/api/files", data=form, headers=_auth_headers())
        assert resp.status == 201
        data = await resp.json()

    saved_path = Path(data["path"])
    assert saved_path.read_text() == "hello business file"
    assert saved_path == workspace.resolve() / "docs" / "report.txt"
    assert data["conversation_id"] == "conv-1"
    assert data["size"] == len(b"hello business file")


@pytest.mark.asyncio
async def test_file_upload_rejects_path_traversal(tmp_path):
    workspace = tmp_path / "workspace"
    adapter = _make_adapter(workspace)
    app = _create_app(adapter)

    form = FormData()
    form.add_field("target_path", "../outside")
    form.add_field("file", b"nope", filename="escape.txt", content_type="text/plain")

    async with TestClient(TestServer(app)) as cli:
        resp = await cli.post("/api/files", data=form, headers=_auth_headers())
        assert resp.status == 400
        body = await resp.json()

    assert body["error"]["code"] == "invalid_target_path"
    assert not (tmp_path / "outside" / "escape.txt").exists()
