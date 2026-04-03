"""Project manager — creates, stores, and generates code for projects.

A project is a directory of files generated from a blueprint (or from scratch)
using an Ollama model.  The manager:

1. Creates a project skeleton from a blueprint.
2. Iterates over each ``generate=True`` file and asks the model to produce its
   content, providing the blueprint's system prompt and the full file map as
   context so the model writes coherent, cross-referencing code.
3. Persists project metadata and generated files in a local SQLite database
   so they survive restarts and can be exported / pushed to Git.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite

from training_interface.blueprints import Blueprint
from training_interface.ollama_client import ChatMessage, OllamaClient


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ProjectFile:
    """A single file within a generated project."""

    path: str
    content: str = ""
    generated: bool = False  # True once the model has filled it
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "generated": self.generated,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectFile:
        return cls(
            path=data.get("path", ""),
            content=data.get("content", ""),
            generated=data.get("generated", False),
            description=data.get("description", ""),
        )


@dataclass
class Project:
    """A generated project with all its files and metadata."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    description: str = ""
    blueprint_id: str = ""
    blueprint_name: str = ""
    model_name: str = ""
    language: str = ""
    framework: str = ""
    files: list[ProjectFile] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    build_commands: list[str] = field(default_factory=list)
    run_command: str = ""
    status: str = "pending"  # pending | generating | completed | failed
    git_remote: str = ""  # remote URL if synced
    git_branch: str = "main"
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    user_prompt: str = ""  # extra instructions from the user

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "blueprint_id": self.blueprint_id,
            "blueprint_name": self.blueprint_name,
            "model_name": self.model_name,
            "language": self.language,
            "framework": self.framework,
            "files": [f.to_dict() for f in self.files],
            "dependencies": self.dependencies,
            "build_commands": self.build_commands,
            "run_command": self.run_command,
            "status": self.status,
            "git_remote": self.git_remote,
            "git_branch": self.git_branch,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "user_prompt": self.user_prompt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            name=data.get("name", ""),
            description=data.get("description", ""),
            blueprint_id=data.get("blueprint_id", ""),
            blueprint_name=data.get("blueprint_name", ""),
            model_name=data.get("model_name", ""),
            language=data.get("language", ""),
            framework=data.get("framework", ""),
            files=[ProjectFile.from_dict(f) for f in data.get("files", [])],
            dependencies=data.get("dependencies", []),
            build_commands=data.get("build_commands", []),
            run_command=data.get("run_command", ""),
            status=data.get("status", "pending"),
            git_remote=data.get("git_remote", ""),
            git_branch=data.get("git_branch", "main"),
            created_at=data.get("created_at", time.time()),
            finished_at=data.get("finished_at", 0.0),
            user_prompt=data.get("user_prompt", ""),
        )

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def generated_count(self) -> int:
        return sum(1 for f in self.files if f.generated)


# ---------------------------------------------------------------------------
# Project store (SQLite)
# ---------------------------------------------------------------------------

_PROJECT_SCHEMA = """\
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    name TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    model_name TEXT DEFAULT '',
    blueprint_name TEXT DEFAULT '',
    git_remote TEXT DEFAULT '',
    created_at REAL NOT NULL,
    finished_at REAL DEFAULT 0
);
"""


class ProjectStore:
    """Persists projects to a local SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self._db_path)
        await conn.execute(_PROJECT_SCHEMA)
        await conn.commit()
        return conn

    async def save(self, project: Project) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                "INSERT OR REPLACE INTO projects "
                "(id, data, name, status, model_name, blueprint_name, "
                "git_remote, created_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project.id,
                    json.dumps(project.to_dict()),
                    project.name,
                    project.status,
                    project.model_name,
                    project.blueprint_name,
                    project.git_remote,
                    project.created_at,
                    project.finished_at,
                ),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def load(self, project_id: str) -> Project | None:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "SELECT data FROM projects WHERE id = ?", (project_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return Project.from_dict(data)
        finally:
            await conn.close()

    async def list_projects(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return project summaries ordered by creation time (newest first)."""
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "SELECT id, name, status, model_name, blueprint_name, "
                "git_remote, created_at, finished_at "
                "FROM projects ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "status": r[2],
                    "model_name": r[3],
                    "blueprint_name": r[4],
                    "git_remote": r[5],
                    "created_at": r[6],
                    "finished_at": r[7],
                }
                for r in rows
            ]
        finally:
            await conn.close()

    async def delete(self, project_id: str) -> bool:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "DELETE FROM projects WHERE id = ?", (project_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# Code generation engine
# ---------------------------------------------------------------------------

_FILE_GEN_PROMPT = """\
You are generating file `{file_path}` for the project "{project_name}".

Description of this file: {file_description}

Project structure (all files):
{file_tree}

{user_instructions}

Generate ONLY the file content — no explanations, no markdown fences, no
commentary.  Output raw source code that can be saved directly to disk."""


class ProjectGenerator:
    """Generates project files using an Ollama model."""

    def __init__(self, client: OllamaClient) -> None:
        self._client = client

    async def generate_project(
        self,
        blueprint: Blueprint,
        model: str,
        project_name: str,
        store: ProjectStore,
        *,
        user_prompt: str = "",
        temperature: float = 0.4,
        on_file_done: Any = None,
    ) -> Project:
        """Generate a full project from a blueprint.

        Args:
            blueprint: The blueprint to use.
            model: Ollama model name.
            project_name: Human-readable project name.
            store: Where to persist progress.
            user_prompt: Extra instructions from the user.
            temperature: Sampling temperature (lower = more deterministic).
            on_file_done: Optional async callback(project, file) for progress.

        Returns:
            The completed Project with all files generated.
        """
        # Build initial project from blueprint
        project = Project(
            name=project_name,
            description=blueprint.description,
            blueprint_id=blueprint.id,
            blueprint_name=blueprint.name,
            model_name=model,
            language=blueprint.language,
            framework=blueprint.framework,
            dependencies=blueprint.dependencies,
            build_commands=blueprint.build_commands,
            run_command=blueprint.run_command,
            status="generating",
            user_prompt=user_prompt,
        )

        # Create project files from blueprint
        for bp_file in blueprint.files:
            project.files.append(
                ProjectFile(
                    path=bp_file.path,
                    content=bp_file.content,
                    generated=not bp_file.generate,  # static files are "done"
                    description=bp_file.description,
                )
            )

        await store.save(project)

        # Build file tree string for context
        file_tree = "\n".join(f"  - {f.path}: {f.description}" for f in project.files)

        # Generate each file that needs generation
        for pf in project.files:
            if pf.generated:
                continue  # already has static content

            user_instructions = ""
            if user_prompt:
                user_instructions = f"Additional user instructions:\n{user_prompt}"

            prompt = _FILE_GEN_PROMPT.format(
                file_path=pf.path,
                project_name=project_name,
                file_description=pf.description or pf.path,
                file_tree=file_tree,
                user_instructions=user_instructions,
            )

            messages = [
                ChatMessage(role="system", content=blueprint.system_prompt),
                ChatMessage(role="user", content=prompt),
            ]

            try:
                result = await self._client.chat(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    num_predict=4096,
                )
                pf.content = self._strip_fences(result.content)
                pf.generated = True
            except Exception as exc:
                pf.content = f"# ERROR generating this file: {exc}"
                pf.generated = True  # mark as done even on error

            await store.save(project)

            if on_file_done is not None:
                await on_file_done(project, pf)

        project.status = "completed"
        project.finished_at = time.time()
        await store.save(project)
        return project

    async def regenerate_file(
        self,
        project: Project,
        file_path: str,
        model: str,
        store: ProjectStore,
        *,
        extra_instructions: str = "",
        temperature: float = 0.4,
    ) -> ProjectFile | None:
        """Regenerate a single file within an existing project."""
        target: ProjectFile | None = None
        for pf in project.files:
            if pf.path == file_path:
                target = pf
                break
        if target is None:
            return None

        file_tree = "\n".join(f"  - {f.path}: {f.description}" for f in project.files)

        # Include existing files as context
        context_parts: list[str] = []
        for pf in project.files:
            if pf.path != file_path and pf.content:
                context_parts.append(f"--- {pf.path} ---\n{pf.content[:2000]}")

        context_str = ""
        if context_parts:
            context_str = (
                "\n\nExisting project files for reference:\n"
                + "\n\n".join(context_parts[:5])  # limit context size
            )

        user_instructions = ""
        if extra_instructions:
            user_instructions = f"Additional instructions:\n{extra_instructions}"
        if project.user_prompt:
            user_instructions += (
                f"\nOriginal project instructions:\n{project.user_prompt}"
            )

        prompt = (
            _FILE_GEN_PROMPT.format(
                file_path=file_path,
                project_name=project.name,
                file_description=target.description or file_path,
                file_tree=file_tree,
                user_instructions=user_instructions,
            )
            + context_str
        )

        system = ""
        # Try to find the blueprint's system prompt from the project data
        if project.language and project.framework:
            system = (
                f"You are an expert {project.language} developer using "
                f"{project.framework}. Generate clean, production-quality code."
            )

        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=prompt),
        ]

        try:
            result = await self._client.chat(
                model=model,
                messages=messages,
                temperature=temperature,
                num_predict=4096,
            )
            target.content = self._strip_fences(result.content)
            target.generated = True
        except Exception as exc:
            target.content = f"# ERROR regenerating: {exc}"

        await store.save(project)
        return target

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Remove markdown code fences if the model wraps its output."""
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            # Remove first line (```lang) and last line (```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            return "\n".join(lines)
        return stripped

    @staticmethod
    def export_to_disk(project: Project, output_dir: str | Path) -> Path:
        """Write all project files to a directory on disk.

        Returns the output directory path.
        """
        base = Path(output_dir) / project.name.replace(" ", "-").lower()
        base.mkdir(parents=True, exist_ok=True)

        for pf in project.files:
            file_path = base / pf.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(pf.content, encoding="utf-8")

        return base
