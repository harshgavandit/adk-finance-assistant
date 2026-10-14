"""Credential-safe offline checks and optional live ADK workflows."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import tempfile
import uuid

from finance_runtime.settings import PROJECT_ROOT, Settings
from finance_runtime.rate_limit import LocalRateLimiter


async def run_scenario(prompt: str, expected_tools: set[str]) -> dict:
    from google.adk.agents.run_config import RunConfig
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    from finance_assistant_agent.agent import root_agent
    service = InMemorySessionService()
    sid = uuid.uuid4().hex
    await service.create_session(app_name="finance_verification", user_id="verification", session_id=sid)
    runner = Runner(agent=root_agent, app_name="finance_verification", session_service=service)
    calls, authors, final, errors = set(), set(), [], []
    search_status = None
    async for event in runner.run_async(user_id="verification", session_id=sid,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        run_config=RunConfig(max_llm_calls=10)):
        authors.add(event.author)
        state = event.actions.state_delta or {}
        calls.update(state.get("finance_tools_called", []))
        search_status = state.get("finance_search_status", search_status)
        if state.get("finance_model_error"):
            errors.append(state["finance_model_error"])
        for part in event.content.parts if event.content else []:
            if part.function_call:
                calls.add(part.function_call.name)
            if event.is_final_response() and part.text:
                final.append(part.text)
    answer = "\n".join(final)
    passed = bool(answer) and not errors and expected_tools <= calls
    if "search_current_finance_information" in expected_tools:
        passed = passed and search_status == "ok" and "http" in answer
    return {"status": "pass" if passed else "fail", "tools_called": sorted(calls),
            "authors": sorted(authors), "model_errors": errors, "search_status": search_status, "answer": answer}


async def verify(live: bool) -> dict:
    settings = Settings.from_environment()
    from finance_assistant_agent.agent import root_agent, get_user_personal_finance_details
    from investment_plan_agent.agent import root_agent as investment
    data = get_user_personal_finance_details()
    with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
        limiter = LocalRateLimiter(Path(directory) / "quota.db", 2, 60)
        assert [limiter.admit("test").allowed for _ in range(3)] == [True, True, False]
    report = {"verified_at": datetime.now(timezone.utc).isoformat(),
              "configuration": {"model": settings.model, "api_key_present": bool(settings.api_key),
                                "rate_limit_backend": "local_sqlite", "max_model_calls": settings.max_calls,
                                "window_seconds": settings.window_seconds},
              "offline": {"agent_imports": "pass", "both_models_configured":
                          root_agent.model.model == investment.model.model == f"openai/{settings.model}",
                          "demo_budget_consistent": data["salary"] - sum(data["expense"].values()) == data["savings"],
                          "rate_limit_admission": "pass"}}
    if live:
        from finance_runtime.search import search_current_finance_information
        scenarios = {}
        scenarios["general_question"] = await run_scenario("Explain a recurring deposit in two sentences.", set())
        if scenarios["general_question"]["status"] == "pass":
            scenarios["demo_budget_tool"] = await run_scenario(
                "Use the available demo personal finance profile tool, label it as demo data, and summarize salary, total expenses and monthly savings.",
                {"get_user_personal_finance_details"})
            scenarios["investment_delegation_and_search"] = await run_scenario(
                "Ask the investment planning agent to search for current SBI domestic fixed deposit interest rates. Cite an official source URL if available; say if they could not be verified.",
                {"investment_plan_agent", "search_current_finance_information"})
        search = await search_current_finance_information("site:sbi.bank.in domestic term deposit interest rates")
        report["live"] = {"scenarios": scenarios, "public_search": search}
        report["status"] = "pass" if all(s["status"] == "pass" for s in scenarios.values()) and search["status"] == "ok" else "fail"
    else:
        report["status"] = "pass"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make billable OpenAI requests and public web searches.")
    parser.add_argument("--output", type=Path, help="Save the credential-safe JSON report.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    try:
        report = asyncio.run(verify(args.live))
    except Exception as error:
        # Do not print the raw exception: SDK errors can include credential details.
        report = {"status": "fail", "error_type": type(error).__name__,
                  "notice": "Verification could not complete. Check configuration, dependencies and connectivity."}
    payload = json.dumps(report, indent=2, ensure_ascii=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
