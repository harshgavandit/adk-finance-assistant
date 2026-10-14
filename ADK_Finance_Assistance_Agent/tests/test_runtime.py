import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from finance_runtime.rate_limit import LocalRateLimiter, RateLimitUnavailable, credential_scope
from finance_runtime.settings import ConfigurationError, Settings


def test_configuration_validation_and_secret_repr():
    settings = Settings.from_environment({"OPENAI_API_KEY": "secret-test", "LLM_MODEL": "openai/gpt-4o-mini"})
    assert settings.model == "gpt-4o-mini"
    assert "secret-test" not in repr(settings)
    assert settings.rate_limit_db.is_absolute()
    with pytest.raises(ConfigurationError):
        Settings.from_environment({})
    for invalid in ("0", "-1", "abc"):
        with pytest.raises(ConfigurationError):
            Settings.from_environment({"OPENAI_API_KEY": "secret-test", "RATE_LIMIT_MAX_CALLS": invalid})


def test_concurrent_admission_is_atomic(tmp_path):
    limiter = LocalRateLimiter(tmp_path / "quota.db", 3, 60)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: limiter.admit("same-key"), range(20)))
    assert sum(result.allowed for result in results) == 3
    assert limiter.admit("different-key").allowed


def test_expiry_rejection_does_not_extend_window(tmp_path):
    now = [100.0]
    limiter = LocalRateLimiter(tmp_path / "quota.db", 1, 10, clock=lambda: now[0])
    assert limiter.admit("key").allowed
    now[0] = 109
    denied = limiter.admit("key")
    assert not denied.allowed and denied.retry_after == 1
    now[0] = 110
    assert limiter.admit("key").allowed


def test_admission_is_shared_with_another_process(tmp_path):
    database = tmp_path / "quota.db"
    assert LocalRateLimiter(database, 1, 60).admit("key").allowed
    code = "from finance_runtime.rate_limit import LocalRateLimiter; from pathlib import Path; import sys; print(LocalRateLimiter(Path(sys.argv[1]), 1, 60).admit('key').allowed)"
    result = subprocess.run([sys.executable, "-c", code, str(database)], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


def test_storage_failure_blocks_admission(tmp_path):
    database = tmp_path / "directory"
    database.mkdir()
    with pytest.raises(RateLimitUnavailable):
        LocalRateLimiter(database, 1, 60).admit("key")


def test_agent_configuration_and_demo_profile(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test")
    from finance_assistant_agent.agent import root_agent, get_user_personal_finance_details
    from investment_plan_agent.agent import root_agent as investment
    assert root_agent.model.model == "openai/gpt-4o-mini"
    assert investment.model.model == "openai/gpt-4o-mini"
    assert root_agent.before_model_callback and investment.before_model_callback
    data = get_user_personal_finance_details()
    assert data["data_source"] == "demo_sample"
    assert data["salary"] - sum(data["expense"].values()) == data["savings"]


def test_rate_limit_callback_returns_response_without_model_call(tmp_path, monkeypatch):
    from finance_runtime.models import before_model
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test")
    monkeypatch.setenv("RATE_LIMIT_DB", str(tmp_path / "quota.db"))
    monkeypatch.setenv("RATE_LIMIT_MAX_CALLS", "1")
    context = SimpleNamespace(state={})
    assert asyncio.run(before_model(context, None)) is None
    response = asyncio.run(before_model(context, None))
    assert "retry after" in response.content.parts[0].text
    assert context.state["finance_model_error"] == "rate_limited"


def test_model_error_is_sanitized(monkeypatch):
    from finance_runtime.models import on_model_error
    error = Exception("private-secret-insufficient_quota")
    error.status_code = 429
    context = SimpleNamespace(state={})
    response = on_model_error(context, None, error)
    assert context.state["finance_model_error"] == "insufficient_quota"
    assert "billing" in response.content.parts[0].text
    assert "private-secret" not in response.content.parts[0].text


def test_search_filters_bad_urls_and_keeps_provenance(monkeypatch):
    from finance_runtime import search
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test")
    monkeypatch.setattr(search, "_search", lambda *args: [
        {"href": "https://bank.example/rates", "title": "Rates", "body": "Published rate"},
        {"href": "javascript:bad", "body": "Bad"},
    ])
    result = asyncio.run(search.search_current_finance_information("bank rates"))
    assert result["status"] == "ok"
    assert len(result["results"]) == 1
    assert result["results"][0]["url"] == "https://bank.example/rates"
    assert result["retrieved_at"]


def test_search_failure_never_fabricates_results(monkeypatch):
    from finance_runtime import search
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test")
    def fail(*args):
        raise RuntimeError("private-provider-details")
    monkeypatch.setattr(search, "_search", fail)
    result = asyncio.run(search.search_current_finance_information("bank rates"))
    assert result["status"] == "unavailable" and not result["results"]
    assert "private-provider-details" not in str(result)


def test_current_source_response_cannot_invent_rates_or_dates():
    from finance_runtime.models import after_model, before_agent, text_response
    context = SimpleNamespace(state={"finance_search_result": {
        "status": "ok", "retrieved_at": "2026-10-14T12:00:00+00:00",
        "results": [{"url": "https://bank.example/rates", "snippet": "Old rates"}]
    }})
    response = after_model(context, text_response("Current rates are 9.9% retrieved yesterday"))
    text = response.content.parts[0].text
    assert "9.9%" not in text and "yesterday" not in text
    assert "https://bank.example/rates" in text and "2026-10-14T12:00:00+00:00" in text
    before_agent(context)
    assert after_model(context, text_response("General budgeting answer")) is None


def test_denied_runner_never_contacts_model(tmp_path, monkeypatch):
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    from finance_assistant_agent.agent import root_agent
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test")
    database = tmp_path / "quota.db"
    monkeypatch.setenv("RATE_LIMIT_DB", str(database))
    monkeypatch.setenv("RATE_LIMIT_MAX_CALLS", "1")
    LocalRateLimiter(database, 1, 60).admit(credential_scope("secret-test"))
    from google.adk.models.lite_llm import LiteLlm
    async def forbidden(*args, **kwargs):
        raise AssertionError("The provider must not be contacted on denial")
        yield
    monkeypatch.setattr(LiteLlm, "generate_content_async", forbidden)
    async def run():
        service = InMemorySessionService()
        await service.create_session(app_name="tests", user_id="test", session_id="test")
        runner = Runner(agent=root_agent, app_name="tests", session_service=service)
        events = [event async for event in runner.run_async(user_id="test", session_id="test",
            new_message=types.Content(role="user", parts=[types.Part(text="Explain saving.")]))]
        assert any("local model-call rate limit" in (part.text or "") for event in events
                   if event.content for part in event.content.parts)
    asyncio.run(run())
