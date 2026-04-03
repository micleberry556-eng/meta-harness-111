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

from training_interface.blueprints import Blueprint, BlueprintStore
from training_interface.git_sync import GitRemote, GitRemoteStore, GitSync
from training_interface.knowledge_base import KnowledgeBase
from training_interface.ollama_client import OllamaClient
from training_interface.projects import ProjectGenerator, ProjectStore
from training_interface.providers import (
    PROVIDER_PRESETS,
    APIProvider,
    ExternalAPIClient,
    ProviderStore,
    UnifiedClient,
)
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
_PROJECTS_DB_PATH = _DATA_DIR / "projects" / "projects.db"
_GIT_DB_PATH = _DATA_DIR / "git" / "remotes.db"
_PROVIDERS_DB_PATH = _DATA_DIR / "providers" / "providers.db"
_KB_DIR = _DATA_DIR / "knowledge_base"
_EXPORTS_DIR = _DATA_DIR / "exports"
_PROJECTS_DIR = _DATA_DIR / "projects" / "files"
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Ensure directories exist
for _d in (
    _DATA_DIR / "sessions",
    _DATA_DIR / "projects",
    _DATA_DIR / "git",
    _DATA_DIR / "providers",
    _KB_DIR,
    _EXPORTS_DIR,
    _PROJECTS_DIR,
    _STATIC_DIR,
    _TEMPLATES_DIR,
):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

ollama = OllamaClient()
store = SessionStore(_DB_PATH)
kb = KnowledgeBase(_KB_DIR)
engine = TrainingEngine(client=ollama, store=store)
bp_store = BlueprintStore(_KB_DIR)
proj_store = ProjectStore(_PROJECTS_DB_PATH)
proj_gen = ProjectGenerator(ollama)
git_store = GitRemoteStore(_GIT_DB_PATH)
provider_store = ProviderStore(_PROVIDERS_DB_PATH)
unified = UnifiedClient(ollama, provider_store)

# Seed knowledge base and blueprints on first run
kb.seed_if_empty()
bp_store.seed_if_empty()

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


class CreateProjectRequest(BaseModel):
    blueprint_id: str = Field(..., description="Blueprint to use")
    name: str = Field(..., description="Project name")
    model: str = Field(..., description="Ollama model name")
    user_prompt: str = ""
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)


class SaveBlueprintRequest(BaseModel):
    id: str = ""
    name: str = ""
    category: str = ""
    description: str = ""
    language: str = ""
    framework: str = ""
    files: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    build_commands: list[str] = Field(default_factory=list)
    run_command: str = ""
    system_prompt: str = ""
    tags: list[str] = Field(default_factory=list)


class SaveGitRemoteRequest(BaseModel):
    name: str
    provider: str = "github"
    url_template: str = ""
    owner: str = ""
    token: str = ""


class GitSyncRequest(BaseModel):
    project_id: str
    remote_id: str
    repo_name: str = ""
    branch: str = "main"
    commit_message: str = "Update project"


class UpdateFileRequest(BaseModel):
    content: str


class AdminUpdateKBItemRequest(BaseModel):
    data: dict[str, Any]


class SaveProviderRequest(BaseModel):
    provider_type: str = Field(
        ..., description="xai, openai, anthropic, google, custom"
    )
    name: str = ""
    base_url: str = ""
    api_key: str = Field(..., description="API key for the provider")
    default_model: str = ""
    models: list[str] = Field(default_factory=list)


class CheckResponseRequest(BaseModel):
    response_text: str = Field(..., description="AI response text to check")
    context: str = ""
    check_type: str = "auto"
    model: str = Field(..., description="Model to use for checking")


# ---------------------------------------------------------------------------
# Pages (HTML)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the main dashboard page."""
    return templates.TemplateResponse(request, "index.html")


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
    """Send a single message to a model and get a response.

    The model field can be:
    - A plain Ollama model name: "codellama:latest"
    - A prefixed external model: "xai:grok-3-latest", "openai:gpt-4o"
    - A provider-ID prefixed model: "<provider_id>:<model_name>"
    """
    from training_interface.ollama_client import ChatMessage

    messages = []
    if req.system_prompt:
        messages.append(ChatMessage(role="system", content=req.system_prompt))
    messages.append(ChatMessage(role="user", content=req.message))

    try:
        result = await unified.chat(model_ref=req.model, messages=messages)
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
# Blueprints
# ---------------------------------------------------------------------------


@app.get("/api/blueprints")
async def list_blueprints(category: str | None = None) -> dict[str, Any]:
    """List available project blueprints."""
    items = bp_store.list_blueprints(category=category)
    return {"blueprints": items, "count": len(items)}


@app.get("/api/blueprints/categories")
async def blueprint_categories() -> dict[str, Any]:
    """List all blueprint categories."""
    return {"categories": bp_store.get_categories()}


@app.get("/api/blueprints/{bp_id}")
async def get_blueprint(bp_id: str) -> dict[str, Any]:
    """Get full blueprint details."""
    bp = bp_store.get(bp_id)
    if bp is None:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return bp.to_dict()


@app.post("/api/blueprints")
async def save_blueprint(req: SaveBlueprintRequest) -> dict[str, Any]:
    """Create or update a blueprint."""
    from training_interface.blueprints import BlueprintFile

    bp = Blueprint(
        id=req.id if req.id else "",
        name=req.name,
        category=req.category,
        description=req.description,
        language=req.language,
        framework=req.framework,
        files=[BlueprintFile.from_dict(f) for f in req.files],
        dependencies=req.dependencies,
        build_commands=req.build_commands,
        run_command=req.run_command,
        system_prompt=req.system_prompt,
        tags=req.tags,
    )
    bp_id = bp_store.save(bp)
    return {"id": bp_id, "message": "Blueprint saved"}


@app.delete("/api/blueprints/{bp_id}")
async def delete_blueprint(bp_id: str) -> dict[str, Any]:
    """Delete a blueprint."""
    ok = bp_store.delete(bp_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return {"deleted": bp_id}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@app.get("/api/projects")
async def list_projects(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List generated projects."""
    projects = await proj_store.list_projects(limit=limit, offset=offset)
    return {"projects": projects}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    """Get full project details including all files."""
    project = await proj_store.load(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.to_dict()


@app.post("/api/projects/generate")
async def generate_project(req: CreateProjectRequest) -> dict[str, Any]:
    """Generate a new project from a blueprint using an Ollama model."""
    bp = bp_store.get(req.blueprint_id)
    if bp is None:
        raise HTTPException(status_code=404, detail="Blueprint not found")

    # Run generation in background
    bg = asyncio.create_task(
        proj_gen.generate_project(
            blueprint=bp,
            model=req.model,
            project_name=req.name,
            store=proj_store,
            user_prompt=req.user_prompt,
            temperature=req.temperature,
        )
    )

    def _cleanup(fut: asyncio.Future[Any]) -> None:
        _running_sessions.pop(req.name, None)

    _running_sessions[req.name] = bg
    bg.add_done_callback(_cleanup)

    return {
        "message": "Project generation started",
        "blueprint": bp.name,
        "model": req.model,
        "name": req.name,
    }


@app.post("/api/projects/{project_id}/regenerate/{file_path:path}")
async def regenerate_file(
    project_id: str, file_path: str, extra: str = ""
) -> dict[str, Any]:
    """Regenerate a single file within a project."""
    project = await proj_store.load(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await proj_gen.regenerate_file(
        project=project,
        file_path=file_path,
        model=project.model_name,
        store=proj_store,
        extra_instructions=extra,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="File not found in project")
    return {"path": result.path, "generated": result.generated}


@app.put("/api/projects/{project_id}/files/{file_path:path}")
async def update_project_file(
    project_id: str, file_path: str, req: UpdateFileRequest
) -> dict[str, Any]:
    """Manually update a file's content in a project."""
    project = await proj_store.load(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    for pf in project.files:
        if pf.path == file_path:
            pf.content = req.content
            await proj_store.save(project)
            return {"path": file_path, "updated": True}

    raise HTTPException(status_code=404, detail="File not found in project")


@app.post("/api/projects/{project_id}/export")
async def export_project(project_id: str) -> dict[str, Any]:
    """Export project files to disk."""
    project = await proj_store.load(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    output = ProjectGenerator.export_to_disk(project, _PROJECTS_DIR)
    return {"path": str(output), "file_count": project.file_count}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, Any]:
    """Delete a project."""
    ok = await proj_store.delete(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": project_id}


# ---------------------------------------------------------------------------
# Git sync
# ---------------------------------------------------------------------------


@app.get("/api/git/remotes")
async def list_git_remotes() -> dict[str, Any]:
    """List saved Git remote configurations."""
    remotes = await git_store.list_remotes()
    return {"remotes": remotes}


@app.post("/api/git/remotes")
async def save_git_remote(req: SaveGitRemoteRequest) -> dict[str, Any]:
    """Save a new Git remote configuration."""
    remote = GitRemote(
        name=req.name,
        provider=req.provider,
        url_template=req.url_template,
        owner=req.owner,
        token=req.token,
    )
    await git_store.save(remote)
    return {"id": remote.id, "message": "Remote saved"}


@app.delete("/api/git/remotes/{remote_id}")
async def delete_git_remote(remote_id: str) -> dict[str, Any]:
    """Delete a Git remote configuration."""
    ok = await git_store.delete(remote_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Remote not found")
    return {"deleted": remote_id}


@app.post("/api/git/sync")
async def sync_project_to_git(req: GitSyncRequest) -> dict[str, Any]:
    """Sync a project to a Git remote (export, init, commit, push)."""
    project = await proj_store.load(req.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    remote = await git_store.load(req.remote_id)
    if remote is None:
        raise HTTPException(status_code=404, detail="Remote not found")

    # Export project to disk
    repo_name = req.repo_name or project.name.replace(" ", "-").lower()
    project_dir = ProjectGenerator.export_to_disk(project, _PROJECTS_DIR)

    # Build remote URL
    remote_url = remote.repo_url(repo_name)

    # Full sync: init, commit, push
    result = await GitSync.full_sync(
        project_dir=project_dir,
        remote_url=remote_url,
        branch=req.branch,
        commit_message=req.commit_message,
    )

    # Update project with git info
    if result.success:
        # Store the safe URL (without token) in the project
        safe_url = remote_url
        if remote.token and safe_url.startswith("https://"):
            safe_url = safe_url.replace(f"{remote.token}@", "", 1)
        project.git_remote = safe_url
        project.git_branch = req.branch
        await proj_store.save(project)

    return result.to_dict()


@app.get("/api/git/status/{project_id}")
async def git_project_status(project_id: str) -> dict[str, Any]:
    """Get git status for a project's exported directory."""
    project = await proj_store.load(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    project_dir = _PROJECTS_DIR / project.name.replace(" ", "-").lower()
    if not project_dir.exists():
        return {"initialized": False, "message": "Project not exported yet"}

    return await GitSync.status(project_dir)


# ---------------------------------------------------------------------------
# Admin panel — CRUD for all entities
# ---------------------------------------------------------------------------


@app.get("/api/admin/overview")
async def admin_overview() -> dict[str, Any]:
    """Admin overview: counts of all entities."""
    sessions = await store.list_sessions(limit=10000)
    projects = await proj_store.list_projects(limit=10000)
    remotes = await git_store.list_remotes()
    return {
        "sessions": len(sessions),
        "projects": len(projects),
        "blueprints": len(bp_store.list_blueprints()),
        "kb_items": kb.stats()["total_items"],
        "git_remotes": len(remotes),
    }


@app.put("/api/admin/kb/{item_id}")
async def admin_update_kb_item(
    item_id: str, req: AdminUpdateKBItemRequest
) -> dict[str, Any]:
    """Update any knowledge base item (task, pattern, prompt) by ID."""
    existing = kb.get_item(item_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Item not found")

    # Determine the kind and directory
    manifest = kb._load_manifest()
    for entry in manifest.entries:
        if entry.id == item_id:
            dir_map = {
                "task": kb._tasks_dir,
                "pattern": kb._patterns_dir,
                "prompt": kb._prompts_dir,
            }
            target_dir = dir_map.get(entry.kind)
            if target_dir:
                path = target_dir / f"{item_id}.json"
                # Merge: keep id, update the rest
                updated = {**req.data, "id": item_id}
                kb._write_json(path, updated)

                # Update manifest entry name/tags if provided
                if "title" in req.data:
                    entry.name = req.data["title"]
                elif "name" in req.data:
                    entry.name = req.data["name"]
                if "tags" in req.data:
                    entry.tags = req.data["tags"]
                kb._save_manifest(manifest)

                return {"id": item_id, "message": "Item updated"}

    raise HTTPException(status_code=404, detail="Item kind not found")


@app.put("/api/admin/blueprints/{bp_id}")
async def admin_update_blueprint(
    bp_id: str, req: SaveBlueprintRequest
) -> dict[str, Any]:
    """Update a blueprint via admin panel."""
    existing = bp_store.get(bp_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Blueprint not found")

    from training_interface.blueprints import BlueprintFile

    existing.name = req.name or existing.name
    existing.category = req.category or existing.category
    existing.description = req.description or existing.description
    existing.language = req.language or existing.language
    existing.framework = req.framework or existing.framework
    if req.files:
        existing.files = [BlueprintFile.from_dict(f) for f in req.files]
    if req.dependencies:
        existing.dependencies = req.dependencies
    if req.build_commands:
        existing.build_commands = req.build_commands
    if req.run_command:
        existing.run_command = req.run_command
    if req.system_prompt:
        existing.system_prompt = req.system_prompt
    if req.tags:
        existing.tags = req.tags

    bp_store.save(existing)
    return {"id": bp_id, "message": "Blueprint updated"}


# ---------------------------------------------------------------------------
# API Providers (Z.ai, OpenAI, Anthropic, Google, custom)
# ---------------------------------------------------------------------------


@app.get("/api/providers/presets")
async def get_provider_presets() -> dict[str, Any]:
    """Return available provider presets (xai, openai, etc.)."""
    return {"presets": PROVIDER_PRESETS}


@app.get("/api/providers")
async def list_providers() -> dict[str, Any]:
    """List configured API providers (keys masked)."""
    providers = await provider_store.list_providers()
    return {"providers": [p.to_safe_dict() for p in providers]}


@app.post("/api/providers")
async def save_provider(req: SaveProviderRequest) -> dict[str, Any]:
    """Add a new API provider."""
    preset = PROVIDER_PRESETS.get(req.provider_type, {})
    provider = APIProvider(
        provider_type=req.provider_type,
        name=req.name or preset.get("name", req.provider_type),
        base_url=req.base_url or preset.get("base_url", ""),
        api_key=req.api_key,
        default_model=req.default_model or preset.get("default_model", ""),
        models=req.models,
    )
    await provider_store.save(provider)
    return {"id": provider.id, "message": "Provider saved"}


@app.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: str) -> dict[str, Any]:
    """Delete an API provider."""
    ok = await provider_store.delete(provider_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"deleted": provider_id}


@app.post("/api/providers/{provider_id}/test")
async def test_provider(provider_id: str) -> dict[str, Any]:
    """Test connection to an API provider."""
    provider = await provider_store.load(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    client = ExternalAPIClient(provider)
    ok, message = await client.test_connection()
    return {"success": ok, "message": message}


@app.get("/api/models/all")
async def list_all_models() -> dict[str, Any]:
    """List all models from all sources (Ollama + external providers)."""
    models = await unified.list_all_models()
    return {"models": models}


# ---------------------------------------------------------------------------
# AI Hub — response checker
# ---------------------------------------------------------------------------

_CHECK_SYSTEM_PROMPT = """\
You are an expert code reviewer and fact-checker. You will receive a response
that was generated by another AI. Your job is to:

1. Find ALL errors: syntax errors, logic bugs, incorrect facts, bad practices,
   security issues, missing edge cases.
2. Rate the overall quality from 0 to 10.
3. Provide a CORRECTED version of the response with all errors fixed.

Return a JSON object (no markdown fences) with:
{
  "score": <int 0-10>,
  "errors": ["list of specific errors found"],
  "warnings": ["list of non-critical issues or suggestions"],
  "corrected": "the full corrected response",
  "summary": "brief 1-2 sentence summary of what was wrong"
}

If the response is perfect, return score 10 with empty errors.
Only output the JSON object, nothing else."""


@app.post("/api/hub/check")
async def check_ai_response(req: CheckResponseRequest) -> dict[str, Any]:
    """Check and correct a response from any AI service."""
    from training_interface.ollama_client import ChatMessage

    user_prompt = ""
    if req.context:
        user_prompt += f"ORIGINAL QUESTION/TASK:\n{req.context}\n\n"
    user_prompt += f"AI RESPONSE TO CHECK:\n{req.response_text}"

    if req.check_type != "auto":
        user_prompt += f"\n\nFocus on: {req.check_type} errors"

    messages = [
        ChatMessage(role="system", content=_CHECK_SYSTEM_PROMPT),
        ChatMessage(role="user", content=user_prompt),
    ]

    try:
        result = await unified.chat(
            model_ref=req.model, messages=messages, temperature=0.1, max_tokens=8192
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Try to parse JSON response
    import json as _json

    raw = result.content.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    try:
        parsed = _json.loads(raw)
        return {
            "score": parsed.get("score", 0),
            "errors": parsed.get("errors", []),
            "warnings": parsed.get("warnings", []),
            "corrected": parsed.get("corrected", ""),
            "summary": parsed.get("summary", ""),
            "model": result.model,
            "duration_sec": result.total_duration_ns / 1e9,
        }
    except _json.JSONDecodeError:
        # Model didn't return valid JSON — return raw text as corrected version
        return {
            "score": -1,
            "errors": ["Could not parse structured review"],
            "warnings": [],
            "corrected": raw,
            "summary": "Model returned unstructured review",
            "model": result.model,
            "duration_sec": result.total_duration_ns / 1e9,
        }


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
