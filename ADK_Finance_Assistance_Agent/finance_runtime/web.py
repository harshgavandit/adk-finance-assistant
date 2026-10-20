"""Private-code web access to the existing ADK agents, with request-local sessions."""
import asyncio
import hmac
import os
from pathlib import Path
from typing import Literal
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=12)

    @field_validator("message")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Enter a message.")
        return value.strip()

    @model_validator(mode="after")
    def bounded_history(self):
        if sum(len(item.content) for item in self.history) > 18000:
            raise ValueError("Conversation history is too long. Start a new chat.")
        return self


async def run_chat(message: str, history: list[dict]) -> dict:
    from google.adk.agents.run_config import RunConfig
    from google.adk.events import Event
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    from finance_assistant_agent.agent import root_agent
    from .settings import Settings

    service = InMemorySessionService()
    sid = uuid.uuid4().hex
    session = await service.create_session(app_name="finance_web", user_id=sid, session_id=sid)
    for item in history:
        role = "model" if item["role"] == "assistant" else "user"
        await service.append_event(session, Event(author=root_agent.name if role == "model" else "user",
            invocation_id="history", content=types.Content(role=role, parts=[types.Part(text=item["content"])])))
    runner = Runner(agent=root_agent, app_name="finance_web", session_service=service)
    answer, tools, errors = [], set(), []
    try:
        async for event in runner.run_async(user_id=sid, session_id=sid,
                new_message=types.Content(role="user", parts=[types.Part(text=message)]),
                run_config=RunConfig(max_llm_calls=8)):
            delta = event.actions.state_delta or {}
            tools.update(delta.get("finance_tools_called", []))
            if delta.get("finance_model_error"):
                errors.append(delta["finance_model_error"])
            if event.is_final_response() and event.content:
                answer.extend(part.text for part in event.content.parts if part.text and not part.thought)
    finally:
        await runner.close()
    if errors:
        code = errors[-1]
        raise HTTPException(status_code=429 if code in {"rate_limited", "provider_rate_limited"} else 502,
                            detail="\n".join(answer) or "The model request could not be completed.")
    if not answer:
        raise HTTPException(status_code=502, detail="No answer was returned. Please retry.")
    return {"answer": "\n".join(answer), "tools_called": sorted(tools), "model": Settings.from_environment().model}


def create_app(chat_handler=None) -> FastAPI:
    app = FastAPI(title="Finance Assistant", docs_url=None, redoc_url=None, openapi_url=None)
    handler = chat_handler or run_chat

    @app.middleware("http")
    async def limit_and_secure(request: Request, call_next):
        if request.url.path == "/api/chat":
            body = await request.body()
            if len(body) > 32000:
                return JSONResponse({"detail": "Request too large."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    def require_access(request: Request):
        expected = os.environ.get("APP_ACCESS_CODE", "")
        if not expected:
            raise HTTPException(status_code=503, detail="Chat access is not configured.")
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
            raise HTTPException(status_code=401, detail="Enter the private chat access code.")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "adk-finance-assistant", "access_required": True,
                "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
                "rate_limit_scope": "per-instance", "persistent_server_history": False}

    @app.post("/api/chat", dependencies=[Depends(require_access)])
    async def chat(payload: ChatRequest):
        try:
            return await asyncio.wait_for(handler(payload.message, [item.model_dump() for item in payload.history]), timeout=105)
        except HTTPException:
            raise
        except TimeoutError:
            raise HTTPException(status_code=504, detail="The request timed out. Please retry with a shorter question.") from None
        except Exception:
            raise HTTPException(status_code=502, detail="The assistant could not complete this request. Please retry shortly.") from None

    public = Path(__file__).resolve().parents[2] / "public"

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(public / "index.html")

    @app.get("/app.js", include_in_schema=False)
    def javascript():
        return FileResponse(public / "app.js", media_type="text/javascript")

    @app.get("/styles.css", include_in_schema=False)
    def stylesheet():
        return FileResponse(public / "styles.css", media_type="text/css")

    return app
