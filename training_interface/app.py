"""Meta-Harness Training Interface — FastAPI application.

Provides REST API endpoints for:
- Ollama model management (list, pull, delete, info)
- Training sessions (create, run, list, view, delete)
- Knowledge base (list, get, add, delete, export, import)
- System status and health checks

Run with: python -m training_interface.app
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from training_interface.knowledge_base import KnowledgeBase
from training_interface.ollama_client import OllamaClient
from training_interface.training_engine import (
    SessionStore,
    Task,
    TaskDifficulty,
    TrainingEngine,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).resolve().parent.parent
_DATA_DIR = _BASE_DIR / "data"
_DB_PATH = _DATA_DIR / "sessions" / "sessions.db"
_KB_DIR = _DATA_DIR / "knowledge_base"
_EXPORTS_DIR = _DATA_DIR / "exports"
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Ensure directories exist
for _d in (_DATA_DIR / "sessions", _KB_DIR, _EXPORTS_DIR, _STATIC_DIR, _TEMPLATES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

ollama = OllamaClient()
store = SessionStore(_DB_PATH)
kb = KnowledgeBase(_KB_DIR)
engine = TrainingEngine(client=ollama, store=store)

# Seed knowledge base on first run
kb.seed_if_empty()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Meta-Harness Training Interface",
    version="0.1.0",
    description="Local web UI for training neural networks with Ollama",
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Track running sessions so we can report progress
_running_sessions: dict[str, asyncio.Task[Any]] = {}


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class PullModelRequest(BaseModel):
    name: str = Field(..., description="Model name to pull, e.g. 'llama3.2'")


class CreateTaskRequest(BaseModel):
    title: str
    instruction: str
    expected_behavior: str = ""
    evaluation_criteria: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    tags: list[str] = Field(default_factory=list)


class StartSessionRequest(BaseModel):
    task_id: str = Field(..., description="Knowledge base task ID")
    model: str = Field(..., description="Ollama model name")
    max_iterations: int = Field(default=5, ge=1, le=20)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class StartCustomSessionRequest(BaseModel):
    title: str = "Custom Task"
    instruction: str = Field(..., description="Task instruction for the model")
    expected_behavior: str = ""
    evaluation_criteria: list[str] = Field(default_factory=list)
    model: str = Field(..., description="Ollama model name")
    max_iterations: int = Field(default=5, ge=1, le=20)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class ChatRequest(BaseModel):
    model: str
    message: str
    system_prompt: str = ""


# ---------------------------------------------------------------------------
# Pages (HTML)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the main dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})


# ---------------------------------------------------------------------------
# Health & status
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    """System status: Ollama availability, session counts, KB stats."""
    ollama_ok = await ollama.is_available()
    sessions = await store.list_sessions(limit=1000)
    running = sum(1 for s in sessions if s["status"] == "running")
    completed = sum(1 for s in sessions if s["status"] == "completed")
    return {
        "ollama_available": ollama_ok,
        "sessions_total": len(sessions),
        "sessions_running": running,
        "sessions_completed": completed,
        "knowledge_base": kb.stats(),
    }


# ---------------------------------------------------------------------------
# Ollama model management
# ---------------------------------------------------------------------------


@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    """List locally available Ollama models."""
    try:
        models = await ollama.list_models()
        return {
            "models": [
                {
                    "name": m.name,
                    "size": m.size,
                    "size_gb": round(m.size / (1024**3), 2) if m.size else 0,
                    "parameter_size": m.parameter_size,
                    "quantization": m.quantization,
                    "family": m.family,
                    "digest": m.digest[:12] if m.digest else "",
                    "modified_at": m.modified_at,
                }
                for m in models
            ]
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Ollama: {exc}",
        )


@app.post("/api/models/pull")
async def pull_model(req: PullModelRequest) -> StreamingResponse:
    """Pull a model from the Ollama registry with streaming progress."""

    async def _stream() -> AsyncIterator[str]:
        try:
            async for progress in ollama.pull_model(req.name):
                data = {
                    "status": progress.status,
                    "digest": progress.digest,
                    "total": progress.total,
                    "completed": progress.completed,
                    "percent": round(progress.percent, 1),
                }
                yield f"data: {json.dumps(data)}\n\n"
            yield f"data: {json.dumps({'status': 'success', 'done': True})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'status': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.delete("/api/models/{model_name:path}")
async def delete_model(model_name: str) -> dict[str, Any]:
    """Delete a locally stored model."""
    ok = await ollama.delete_model(model_name)
    if not ok:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"deleted": model_name}


@app.get("/api/models/{model_name:path}/info")
async def model_info(model_name: str) -> dict[str, Any]:
    """Get detailed info about a model."""
    try:
        info = await ollama.show_model(model_name)
        return info
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Training sessions
# ---------------------------------------------------------------------------


@app.get("/api/sessions")
async def list_sessions(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List training sessions."""
    sessions = await store.list_sessions(limit=limit, offset=offset)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Get full details of a training session."""
    session = await store.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


@app.post("/api/sessions/start")
async def start_session(req: StartSessionRequest) -> dict[str, Any]:
    """Start a training session using a knowledge base task."""
    task = kb.get_task(req.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found in knowledge base")

    return await _launch_session(task, req.model, req.max_iterations, req.temperature)


@app.post("/api/sessions/start-custom")
async def start_custom_session(req: StartCustomSessionRequest) -> dict[str, Any]:
    """Start a training session with a custom task (not from KB)."""
    task = Task(
        title=req.title,
        instruction=req.instruction,
        expected_behavior=req.expected_behavior,
        evaluation_criteria=req.evaluation_criteria,
        difficulty=TaskDifficulty.MEDIUM,
    )
    return await _launch_session(task, req.model, req.max_iterations, req.temperature)


async def _launch_session(
    task: Task, model: str, max_iterations: int, temperature: float
) -> dict[str, Any]:
    """Launch a training session in the background."""
    # Verify model is available
    try:
        models = await ollama.list_models()
        available = {m.name for m in models}
        if model not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model}' is not available locally. Pull it first.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")

    # Run in background
    bg_task = asyncio.create_task(
        engine.run_session(
            task=task,
            model=model,
            max_iterations=max_iterations,
            temperature=temperature,
        )
    )

    # We need a session ID before the task completes. Create a preliminary
    # session, save it, and let the engine overwrite it as it progresses.
    # The engine creates its own session internally, so we peek at the task
    # to build a tracking entry. We'll use a small wrapper.
    session_id = task.id  # reuse task id as a correlation key

    _running_sessions[session_id] = bg_task

    # Clean up when done
    def _cleanup(fut: asyncio.Future[Any]) -> None:
        _running_sessions.pop(session_id, None)

    bg_task.add_done_callback(_cleanup)

    return {
        "message": "Training session started",
        "task_id": task.id,
        "model": model,
        "max_iterations": max_iterations,
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    """Delete a training session."""
    ok = await store.delete(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": session_id}


@app.get("/api/sessions/export/all")
async def export_sessions() -> dict[str, Any]:
    """Export all sessions as JSON (for offline backup)."""
    data = await store.export_all()
    return {"sessions": data, "count": len(data)}


# ---------------------------------------------------------------------------
# Quick chat (direct model interaction)
# ---------------------------------------------------------------------------


@app.post("/api/chat")
async def quick_chat(req: ChatRequest) -> dict[str, Any]:
    """Send a single message to a model and get a response."""
    from training_interface.ollama_client import ChatMessage

    messages = []
    if req.system_prompt:
        messages.append(ChatMessage(role="system", content=req.system_prompt))
    messages.append(ChatMessage(role="user", content=req.message))

    try:
        result = await ollama.chat(model=req.model, messages=messages)
        return {
            "response": result.content,
            "model": result.model,
            "eval_count": result.eval_count,
            "duration_sec": result.total_duration_ns / 1e9,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


@app.get("/api/kb")
async def list_kb_items(
    kind: str | None = None, tag: str | None = None
) -> dict[str, Any]:
    """List knowledge base items."""
    items = kb.list_items(kind=kind, tag=tag)
    return {"items": items, "count": len(items)}


@app.get("/api/kb/stats")
async def kb_stats() -> dict[str, Any]:
    """Knowledge base statistics."""
    return kb.stats()


@app.get("/api/kb/{item_id}")
async def get_kb_item(item_id: str) -> dict[str, Any]:
    """Get a single knowledge base item."""
    item = kb.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.post("/api/kb/tasks")
async def create_kb_task(req: CreateTaskRequest) -> dict[str, Any]:
    """Add a new task to the knowledge base."""
    task = Task(
        title=req.title,
        instruction=req.instruction,
        expected_behavior=req.expected_behavior,
        evaluation_criteria=req.evaluation_criteria,
        difficulty=TaskDifficulty(req.difficulty),
        tags=req.tags,
    )
    task_id = kb.add_task(task)
    return {"id": task_id, "message": "Task created"}


@app.delete("/api/kb/{item_id}")
async def delete_kb_item(item_id: str) -> dict[str, Any]:
    """Delete a knowledge base item."""
    ok = kb.delete_item(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"deleted": item_id}


@app.get("/api/kb/export/archive")
async def export_kb_archive() -> FileResponse:
    """Export the entire knowledge base as a zip archive."""
    output_path = _EXPORTS_DIR / "knowledge_base_export"
    archive_path = kb.export_archive(output_path)
    return FileResponse(
        path=archive_path,
        filename="knowledge_base.zip",
        media_type="application/zip",
    )


@app.post("/api/kb/import/archive")
async def import_kb_archive(file: UploadFile) -> dict[str, Any]:
    """Import a knowledge base archive (zip)."""
    if file.filename is None or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Please upload a .zip file")

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        count = kb.import_archive(tmp_path)
        return {"imported": count, "message": f"Imported {count} new items"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the application with uvicorn."""
    import uvicorn

    print("\n  Meta-Harness Training Interface")
    print("  ================================")
    print("  Open http://localhost:8000 in your browser\n")

    uvicorn.run(
        "training_interface.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
