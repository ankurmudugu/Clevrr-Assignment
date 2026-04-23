from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import run_agent
from .config import get_settings
from .models import ChatRequest, ChatResponse


settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


def _is_gemini_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "quota" in message or "429" in message or "rate limit" in message


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        payload = run_agent(
            settings=settings,
            session_id=request.session_id,
            message=request.message,
            store_url=request.store_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if _is_gemini_quota_error(exc):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Gemini API quota is unavailable for the configured key or model. "
                    "Check your Gemini API plan, billing, and project quotas, then try again."
                ),
            ) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(session_id=request.session_id, response=payload)
