from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent import run_agent
from .config import ROOT_DIR, get_settings
from .models import ChatRequest, ChatResponse


settings = get_settings()
app = FastAPI(title=settings.app_name)
FRONTEND_DIST_DIR = ROOT_DIR / "frontend_dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"

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


if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")


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


@app.get("/{full_path:path}")
def frontend_app(full_path: str) -> FileResponse:
    if not FRONTEND_DIST_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found.")

    requested_path = (FRONTEND_DIST_DIR / full_path).resolve()
    if full_path and requested_path.is_file() and FRONTEND_DIST_DIR in requested_path.parents:
        return FileResponse(requested_path)

    index_path = FRONTEND_DIST_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend entrypoint not found.")
    return FileResponse(index_path)
