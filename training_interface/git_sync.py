"""Git sync — push projects to GitHub, GitLab, Bitbucket, or any Git remote.

Operates entirely through the ``git`` CLI so no extra libraries are needed.
All operations are async (run in a subprocess) and non-blocking.

Workflow:
1. Export project files to a temporary directory on disk.
2. ``git init`` + ``git add`` + ``git commit``.
3. ``git remote add origin <url>`` + ``git push``.
4. Subsequent syncs: ``git add -A`` + ``git commit`` + ``git push``.

Supports:
- GitHub (HTTPS with token or SSH)
- GitLab
- Bitbucket
- Any Git remote URL
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class GitRemote:
    """A saved Git remote configuration."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""  # human-readable label, e.g. "My GitHub"
    provider: str = ""  # github, gitlab, bitbucket, custom
    url_template: str = ""  # e.g. "https://github.com/{owner}/{repo}.git"
    owner: str = ""  # GitHub org or username
    token: str = ""  # personal access token (stored locally only)
    created_at: float = field(default_factory=time.time)

    def repo_url(self, repo_name: str) -> str:
        """Build the full remote URL for a given repo name."""
        if self.url_template:
            url = self.url_template.replace("{owner}", self.owner).replace(
                "{repo}", repo_name
            )
        elif self.provider == "github":
            url = f"https://github.com/{self.owner}/{repo_name}.git"
        elif self.provider == "gitlab":
            url = f"https://gitlab.com/{self.owner}/{repo_name}.git"
        elif self.provider == "bitbucket":
            url = f"https://bitbucket.org/{self.owner}/{repo_name}.git"
        else:
            url = f"https://github.com/{self.owner}/{repo_name}.git"

        # Inject token for HTTPS auth if available
        if self.token and url.startswith("https://"):
            # https://TOKEN@github.com/...
            url = url.replace("https://", f"https://{self.token}@", 1)
        return url

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "url_template": self.url_template,
            "owner": self.owner,
            "token": self.token,
            "created_at": self.created_at,
        }

    def to_safe_dict(self) -> dict[str, Any]:
        """Dict without the token (for API responses)."""
        d = self.to_dict()
        d["token"] = "***" if self.token else ""
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitRemote:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            name=data.get("name", ""),
            provider=data.get("provider", ""),
            url_template=data.get("url_template", ""),
            owner=data.get("owner", ""),
            token=data.get("token", ""),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class SyncResult:
    """Result of a git sync operation."""

    success: bool
    message: str
    commit_hash: str = ""
    remote_url: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "commit_hash": self.commit_hash,
            "remote_url": self.remote_url,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Git remote store (SQLite)
# ---------------------------------------------------------------------------

_REMOTE_SCHEMA = """\
CREATE TABLE IF NOT EXISTS git_remotes (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    name TEXT DEFAULT '',
    provider TEXT DEFAULT '',
    owner TEXT DEFAULT '',
    created_at REAL NOT NULL
);
"""


class GitRemoteStore:
    """Persists Git remote configurations to SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self._db_path)
        await conn.execute(_REMOTE_SCHEMA)
        await conn.commit()
        return conn

    async def save(self, remote: GitRemote) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                "INSERT OR REPLACE INTO git_remotes "
                "(id, data, name, provider, owner, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    remote.id,
                    json.dumps(remote.to_dict()),
                    remote.name,
                    remote.provider,
                    remote.owner,
                    remote.created_at,
                ),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def load(self, remote_id: str) -> GitRemote | None:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "SELECT data FROM git_remotes WHERE id = ?", (remote_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return GitRemote.from_dict(data)
        finally:
            await conn.close()

    async def list_remotes(self) -> list[dict[str, Any]]:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "SELECT data FROM git_remotes ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                remote = GitRemote.from_dict(data)
                results.append(remote.to_safe_dict())
            return results
        finally:
            await conn.close()

    async def delete(self, remote_id: str) -> bool:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "DELETE FROM git_remotes WHERE id = ?", (remote_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# Git operations (subprocess-based)
# ---------------------------------------------------------------------------


async def _run_git(
    *args: str, cwd: str | Path | None = None, timeout: float = 60.0
) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    cmd = ["git"] + list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", "Git command timed out"

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    return proc.returncode or 0, stdout, stderr


class GitSync:
    """Handles git init, commit, push, pull for project directories."""

    @staticmethod
    async def init_repo(project_dir: str | Path, branch: str = "main") -> SyncResult:
        """Initialize a git repository in the given directory."""
        d = str(project_dir)
        rc, out, err = await _run_git("init", "-b", branch, cwd=d)
        if rc != 0:
            return SyncResult(success=False, message=f"git init failed: {err}")

        # Configure local user for commits
        await _run_git("config", "user.email", "meta-harness@local", cwd=d)
        await _run_git("config", "user.name", "Meta-Harness", cwd=d)

        return SyncResult(success=True, message="Repository initialized")

    @staticmethod
    async def add_and_commit(
        project_dir: str | Path, message: str = "Update project"
    ) -> SyncResult:
        """Stage all changes and commit."""
        d = str(project_dir)
        rc, _, err = await _run_git("add", "-A", cwd=d)
        if rc != 0:
            return SyncResult(success=False, message=f"git add failed: {err}")

        rc, out, err = await _run_git("commit", "-m", message, "--allow-empty", cwd=d)
        if rc != 0:
            return SyncResult(success=False, message=f"git commit failed: {err}")

        # Extract commit hash
        rc2, hash_out, _ = await _run_git("rev-parse", "HEAD", cwd=d)
        commit_hash = hash_out.strip() if rc2 == 0 else ""

        return SyncResult(
            success=True, message="Changes committed", commit_hash=commit_hash
        )

    @staticmethod
    async def add_remote(
        project_dir: str | Path, remote_url: str, remote_name: str = "origin"
    ) -> SyncResult:
        """Add or update a git remote."""
        d = str(project_dir)
        # Check if remote already exists
        rc, out, _ = await _run_git("remote", "get-url", remote_name, cwd=d)
        if rc == 0:
            # Remote exists — update it
            await _run_git("remote", "set-url", remote_name, remote_url, cwd=d)
        else:
            rc, _, err = await _run_git("remote", "add", remote_name, remote_url, cwd=d)
            if rc != 0:
                return SyncResult(success=False, message=f"Failed to add remote: {err}")

        return SyncResult(
            success=True, message=f"Remote '{remote_name}' set", remote_url=remote_url
        )

    @staticmethod
    async def push(
        project_dir: str | Path,
        branch: str = "main",
        remote_name: str = "origin",
        force: bool = False,
    ) -> SyncResult:
        """Push to the remote."""
        d = str(project_dir)
        args = ["push", "-u", remote_name, branch]
        if force:
            args.append("--force")
        rc, out, err = await _run_git(*args, cwd=d, timeout=120.0)
        if rc != 0:
            return SyncResult(success=False, message=f"Push failed: {err}")
        return SyncResult(success=True, message=f"Pushed to {remote_name}/{branch}")

    @staticmethod
    async def pull(
        project_dir: str | Path,
        branch: str = "main",
        remote_name: str = "origin",
    ) -> SyncResult:
        """Pull from the remote."""
        d = str(project_dir)
        rc, out, err = await _run_git("pull", remote_name, branch, cwd=d, timeout=120.0)
        if rc != 0:
            return SyncResult(success=False, message=f"Pull failed: {err}")
        return SyncResult(success=True, message=f"Pulled from {remote_name}/{branch}")

    @staticmethod
    async def status(project_dir: str | Path) -> dict[str, Any]:
        """Get git status summary."""
        d = str(project_dir)
        rc, out, _ = await _run_git("status", "--porcelain", cwd=d)
        if rc != 0:
            return {"initialized": False, "clean": False, "changes": []}

        changes = [line for line in out.split("\n") if line.strip()]

        # Get current branch
        rc2, branch_out, _ = await _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=d)
        branch = branch_out.strip() if rc2 == 0 else "unknown"

        # Get remote URL
        rc3, remote_out, _ = await _run_git("remote", "get-url", "origin", cwd=d)
        remote = remote_out.strip() if rc3 == 0 else ""

        # Get last commit
        rc4, log_out, _ = await _run_git("log", "-1", "--format=%H %s", cwd=d)
        last_commit = log_out.strip() if rc4 == 0 else ""

        return {
            "initialized": True,
            "branch": branch,
            "remote": remote,
            "clean": len(changes) == 0,
            "changes": changes[:20],  # limit output
            "last_commit": last_commit,
        }

    @classmethod
    async def full_sync(
        cls,
        project_dir: str | Path,
        remote_url: str,
        branch: str = "main",
        commit_message: str = "Update project",
    ) -> SyncResult:
        """Full sync: init if needed, add, commit, set remote, push."""
        d = Path(project_dir)

        # Init if not already a git repo
        if not (d / ".git").exists():
            result = await cls.init_repo(d, branch)
            if not result.success:
                return result

        # Add and commit
        result = await cls.add_and_commit(d, commit_message)
        if not result.success:
            return result

        # Set remote
        result = await cls.add_remote(d, remote_url)
        if not result.success:
            return result

        # Push (force on first push to handle empty remote)
        result = await cls.push(d, branch, force=True)
        result.remote_url = remote_url
        return result
