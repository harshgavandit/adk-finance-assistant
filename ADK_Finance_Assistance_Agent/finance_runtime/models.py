"""Shared OpenAI configuration and admission callbacks for both ADK agents."""
import asyncio
import logging
import os
from urllib.parse import urlparse

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOG", "ERROR")

import litellm
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from .rate_limit import LocalRateLimiter, RateLimitUnavailable, credential_scope
from .settings import Settings

litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)


def text_response(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def create_model() -> LiteLlm:
    settings = Settings.from_environment()
    return LiteLlm(model=f"openai/{settings.model}", api_key=settings.api_key,
                   timeout=settings.timeout_seconds, num_retries=0)


def generation_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(temperature=0.2,
                                       max_output_tokens=Settings.from_environment().max_output_tokens)


async def before_model(callback_context, llm_request) -> LlmResponse | None:
    settings = Settings.from_environment()
    limiter = LocalRateLimiter(settings.rate_limit_db, settings.max_calls, settings.window_seconds)
    try:
        admission = await asyncio.to_thread(limiter.admit, credential_scope(settings.api_key))
    except RateLimitUnavailable:
        callback_context.state["finance_model_error"] = "rate_limit_unavailable"
        return text_response("The local rate limiter is unavailable. Model calls are blocked; check .runtime directory permissions.")
    if not admission.allowed:
        callback_context.state["finance_model_error"] = "rate_limited"
        return text_response(f"The local model-call rate limit was reached. Please retry after {admission.retry_after} seconds.")
    return None


def model_error_code(error: Exception) -> str:
    status = getattr(error, "status_code", None)
    if status == 401:
        return "authentication_failed"
    if status == 429:
        return "insufficient_quota" if "insufficient_quota" in str(error) else "provider_rate_limited"
    if status == 404:
        return "model_unavailable"
    return "provider_unavailable"


def on_model_error(callback_context, llm_request, error: Exception) -> LlmResponse:
    code = model_error_code(error)
    callback_context.state["finance_model_error"] = code
    messages = {
        "authentication_failed": "OpenAI authentication failed. Check OPENAI_API_KEY in .env.",
        "insufficient_quota": "OpenAI API quota is unavailable. Check API billing and project limits, then retry.",
        "provider_rate_limited": "OpenAI temporarily rate-limited this request. Please wait and retry.",
        "model_unavailable": "The configured OpenAI model is unavailable to this API key. Check LLM_MODEL and project access.",
        "provider_unavailable": "The OpenAI request could not be completed. Check the network connection and retry.",
    }
    return text_response(messages[code])


def before_tool(tool, args, tool_context):
    names = list(tool_context.state.get("finance_tools_called", []))
    if tool.name not in names:
        names.append(tool.name)
    tool_context.state["finance_tools_called"] = names
    return None


def before_agent(callback_context):
    callback_context.state["finance_model_error"] = None
    callback_context.state["finance_search_status"] = None
    callback_context.state["finance_search_result"] = None
    callback_context.state["finance_tools_called"] = []
    return None


def after_tool(tool, args, tool_context, tool_response):
    if tool.name == "search_current_finance_information" and isinstance(tool_response, dict):
        tool_context.state["finance_search_status"] = tool_response.get("status", "unavailable")
        tool_context.state["finance_search_result"] = tool_response
    return None


def after_model(callback_context, llm_response):
    """Return verified source metadata instead of generated live-price claims.

    Public snippets cannot establish a current bank rate or price. Keep source
    discovery deterministic after search, for both the specialist and its caller.
    """
    parts = llm_response.content.parts if llm_response.content else []
    if any(part.function_call for part in parts) or callback_context.state.get("finance_model_error"):
        return None
    search = callback_context.state.get("finance_search_result")
    if not search:
        return None
    if search.get("status") != "ok":
        return text_response("Live search is unavailable. Current financial information could not be verified; please check the bank or company's official website.")
    lines = ["I found these public sources. Exact current rates, prices, and active schemes must be verified on the underlying pages; search snippets do not establish those values.", ""]
    seen = set()
    for item in search.get("results", []):
        url = item["url"]
        if url not in seen:
            seen.add(url)
            lines.append(f"- [{urlparse(url).hostname}]({url})")
    lines.extend(["", f"Search retrieved at {search.get('retrieved_at', 'unknown')} (UTC). This is a retrieval timestamp, not a publication or effective date."])
    return text_response("\n".join(lines))
