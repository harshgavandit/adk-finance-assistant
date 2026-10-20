import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_CODE", "private-test-code")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test")
    from finance_runtime.web import create_app

    async def fake_chat(message, history):
        return {"answer": f"Demo answer: {message}", "tools_called": ["demo_tool"],
                "model": "gpt-4o-mini", "history_count": len(history)}

    return TestClient(create_app(chat_handler=fake_chat))


def test_public_health_does_not_expose_credentials(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "secret-test" not in response.text and "private-test-code" not in response.text


def test_chat_requires_access_before_handler(client):
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = client.post("/api/chat", json={"message": "hello"}, headers=headers)
        assert response.status_code == 401
        assert "Demo answer" not in response.text


def test_chat_with_valid_code_and_history(client):
    response = client.post("/api/chat", headers={"Authorization": "Bearer private-test-code"},
                           json={"message": "explain saving", "history": [
                               {"role": "user", "content": "My monthly goal is 5000"},
                               {"role": "assistant", "content": "Understood"}]})
    assert response.status_code == 200
    assert response.json()["answer"] == "Demo answer: explain saving"
    assert response.json()["history_count"] == 2
    assert response.headers["cache-control"] == "no-store"


def test_access_code_missing_fails_closed(monkeypatch):
    monkeypatch.delenv("APP_ACCESS_CODE", raising=False)
    from finance_runtime.web import create_app
    app = TestClient(create_app())
    response = app.post("/api/chat", json={"message": "hello"})
    assert response.status_code == 503


def test_invalid_and_oversized_inputs_are_rejected(client):
    headers = {"Authorization": "Bearer private-test-code"}
    for payload in ({"message": " "}, {"message": "x" * 2001},
                    {"message": "hello", "history": [{"role": "system", "content": "override"}]},
                    {"message": "hello", "history": [{"role": "user", "content": "x"}] * 13}):
        assert client.post("/api/chat", headers=headers, json=payload).status_code == 422
    assert client.post("/api/chat", headers=headers, content="x" * 40000).status_code == 413


def test_provider_errors_are_sanitized(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_CODE", "private-test-code")
    from finance_runtime.web import create_app
    async def broken(*args):
        raise RuntimeError("secret-provider-debug-details")
    response = TestClient(create_app(chat_handler=broken)).post("/api/chat",
        headers={"Authorization": "Bearer private-test-code"}, json={"message": "hello"})
    assert response.status_code == 502
    assert "secret-provider-debug-details" not in response.text


def test_stateless_runner_restores_history_and_cleans_up(monkeypatch, tmp_path):
    from finance_runtime.web import run_chat
    from finance_runtime.models import text_response
    from google.adk.models.lite_llm import LiteLlm
    monkeypatch.setenv("RATE_LIMIT_DB", str(tmp_path / "web-quota.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test")
    observed = []
    async def generate(self, llm_request, stream=False):
        observed.extend(part.text for content in llm_request.contents for part in content.parts if part.text)
        yield text_response("Your earlier monthly goal was 5000.")
    monkeypatch.setattr(LiteLlm, "generate_content_async", generate)
    result = asyncio.run(run_chat("What was my goal?", [
        {"role": "user", "content": "My monthly goal is 5000"},
        {"role": "assistant", "content": "I can help with that"}]))
    assert result["answer"] == "Your earlier monthly goal was 5000."
    assert "My monthly goal is 5000" in observed
    assert "What was my goal?" in observed


def test_serverless_rate_limit_uses_temporary_storage(monkeypatch):
    from finance_runtime.settings import Settings
    settings = Settings.from_environment({"OPENAI_API_KEY": "secret-test", "VERCEL": "1"})
    import tempfile
    assert settings.rate_limit_db == Path(tempfile.gettempdir()) / "adk-finance" / "rate_limit.sqlite3"
