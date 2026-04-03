"""Training engine — iterative correction loop for Ollama models.

Runs tasks against a model, evaluates outputs, generates corrective feedback,
and re-runs with improved prompts. Stores full session history in SQLite for
progressive improvement and offline analysis.

The loop works as follows:
1. Present a task to the model.
2. Evaluate the model's response against expected criteria.
3. If errors are found, build a correction prompt that explains the mistakes.
4. Re-run the task with the correction context appended.
5. Repeat until the response passes evaluation or max iterations are reached.
6. Record every attempt, evaluation, and correction in the session database.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import aiosqlite

from training_interface.ollama_client import ChatMessage, OllamaClient


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TaskDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class AttemptVerdict(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"


@dataclass
class Task:
    """A single training task presented to the model."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    instruction: str = ""
    expected_behavior: str = ""
    evaluation_criteria: list[str] = field(default_factory=list)
    difficulty: TaskDifficulty = TaskDifficulty.MEDIUM
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "instruction": self.instruction,
            "expected_behavior": self.expected_behavior,
            "evaluation_criteria": self.evaluation_criteria,
            "difficulty": self.difficulty.value,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            title=data.get("title", ""),
            instruction=data.get("instruction", ""),
            expected_behavior=data.get("expected_behavior", ""),
            evaluation_criteria=data.get("evaluation_criteria", []),
            difficulty=TaskDifficulty(data.get("difficulty", "medium")),
            tags=data.get("tags", []),
        )


@dataclass
class Attempt:
    """One attempt at solving a task."""

    attempt_number: int
    model_response: str
    verdict: AttemptVerdict
    score: float  # 0.0 – 1.0
    errors: list[str] = field(default_factory=list)
    correction_prompt: str = ""
    duration_sec: float = 0.0
    eval_count: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "model_response": self.model_response,
            "verdict": self.verdict.value,
            "score": self.score,
            "errors": self.errors,
            "correction_prompt": self.correction_prompt,
            "duration_sec": self.duration_sec,
            "eval_count": self.eval_count,
            "timestamp": self.timestamp,
        }


@dataclass
class TrainingSession:
    """A full training session: one task, multiple attempts."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task: Task = field(default_factory=Task)
    model_name: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    status: str = "pending"  # pending | running | completed | failed
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    max_iterations: int = 5
    temperature: float = 0.7

    @property
    def best_score(self) -> float:
        if not self.attempts:
            return 0.0
        return max(a.score for a in self.attempts)

    @property
    def improvement(self) -> float:
        """Score delta between first and best attempt."""
        if len(self.attempts) < 2:
            return 0.0
        return self.best_score - self.attempts[0].score

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task.to_dict(),
            "model_name": self.model_name,
            "attempts": [a.to_dict() for a in self.attempts],
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "max_iterations": self.max_iterations,
            "temperature": self.temperature,
            "best_score": self.best_score,
            "improvement": self.improvement,
        }


# ---------------------------------------------------------------------------
# Evaluator — uses the same model to judge its own output
# ---------------------------------------------------------------------------

_EVAL_SYSTEM_PROMPT = """\
You are a strict evaluator. You will receive:
1. A TASK that was given to an AI assistant.
2. The EXPECTED BEHAVIOR describing what a correct response looks like.
3. EVALUATION CRITERIA — a checklist of requirements.
4. The ACTUAL RESPONSE produced by the assistant.

Evaluate the response and return a JSON object (no markdown fences) with:
{
  "verdict": "pass" | "partial" | "fail",
  "score": <float 0.0 to 1.0>,
  "errors": ["list of specific errors or missing requirements"],
  "feedback": "brief explanation of what went wrong and how to fix it"
}

Be precise. A score of 1.0 means every criterion is fully met.
Only output the JSON object, nothing else."""

_CORRECTION_TEMPLATE = """\
Your previous response had the following issues:

{errors}

Evaluator feedback: {feedback}

Please try again. Here is the original task:

{instruction}

Expected behavior: {expected_behavior}

Fix all the issues listed above and provide a correct response."""


class Evaluator:
    """Evaluates model responses using the model itself as a judge."""

    def __init__(self, client: OllamaClient) -> None:
        self._client = client

    async def evaluate(
        self,
        task: Task,
        response: str,
        model: str,
    ) -> tuple[AttemptVerdict, float, list[str], str]:
        """Evaluate a response. Returns (verdict, score, errors, feedback)."""
        user_prompt = (
            f"TASK:\n{task.instruction}\n\n"
            f"EXPECTED BEHAVIOR:\n{task.expected_behavior}\n\n"
            f"EVALUATION CRITERIA:\n"
            + "\n".join(f"- {c}" for c in task.evaluation_criteria)
            + f"\n\nACTUAL RESPONSE:\n{response}"
        )

        result = await self._client.chat(
            model=model,
            messages=[
                ChatMessage(role="system", content=_EVAL_SYSTEM_PROMPT),
                ChatMessage(role="user", content=user_prompt),
            ],
            temperature=0.1,  # low temperature for consistent evaluation
            num_predict=1024,
        )

        return self._parse_eval(result.content)

    @staticmethod
    def _parse_eval(
        raw: str,
    ) -> tuple[AttemptVerdict, float, list[str], str]:
        """Parse the evaluator JSON response, with fallback for malformed output."""
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: treat as a failure with the raw text as feedback
            return AttemptVerdict.FAIL, 0.0, ["Could not parse evaluation"], raw

        verdict_str = data.get("verdict", "fail")
        try:
            verdict = AttemptVerdict(verdict_str)
        except ValueError:
            verdict = AttemptVerdict.FAIL

        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        errors = data.get("errors", [])
        if isinstance(errors, str):
            errors = [errors]
        feedback = data.get("feedback", "")

        return verdict, score, errors, feedback

    @staticmethod
    def build_correction_prompt(
        task: Task,
        errors: list[str],
        feedback: str,
    ) -> str:
        """Build a correction prompt from evaluation results."""
        error_list = "\n".join(f"  - {e}" for e in errors) if errors else "  (none)"
        return _CORRECTION_TEMPLATE.format(
            errors=error_list,
            feedback=feedback,
            instruction=task.instruction,
            expected_behavior=task.expected_behavior,
        )


# ---------------------------------------------------------------------------
# Session database (SQLite)
# ---------------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at REAL NOT NULL,
    finished_at REAL DEFAULT 0,
    model_name TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    best_score REAL DEFAULT 0
);
"""


class SessionStore:
    """Persists training sessions to a local SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self._db_path)
        await conn.execute(_SCHEMA)
        await conn.commit()
        return conn

    async def save(self, session: TrainingSession) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                "INSERT OR REPLACE INTO sessions "
                "(id, data, created_at, finished_at, model_name, status, best_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session.id,
                    json.dumps(session.to_dict()),
                    session.created_at,
                    session.finished_at,
                    session.model_name,
                    session.status,
                    session.best_score,
                ),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def load(self, session_id: str) -> TrainingSession | None:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "SELECT data FROM sessions WHERE id = ?", (session_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._deserialize(row[0])
        finally:
            await conn.close()

    async def list_sessions(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return session summaries ordered by creation time (newest first)."""
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "SELECT id, model_name, status, best_score, created_at, finished_at "
                "FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "model_name": r[1],
                    "status": r[2],
                    "best_score": r[3],
                    "created_at": r[4],
                    "finished_at": r[5],
                }
                for r in rows
            ]
        finally:
            await conn.close()

    async def delete(self, session_id: str) -> bool:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()

    async def export_all(self) -> list[dict[str, Any]]:
        """Export all sessions as a list of dicts (for offline backup)."""
        conn = await self._connect()
        try:
            cursor = await conn.execute("SELECT data FROM sessions ORDER BY created_at")
            rows = await cursor.fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                try:
                    results.append(json.loads(row[0]))
                except json.JSONDecodeError:
                    continue
            return results
        finally:
            await conn.close()

    @staticmethod
    def _deserialize(raw: Any) -> TrainingSession:
        """Reconstruct a TrainingSession from stored JSON."""
        data = json.loads(raw) if isinstance(raw, str) else raw
        task = Task.from_dict(data.get("task", {}))
        attempts = []
        for a in data.get("attempts", []):
            attempts.append(
                Attempt(
                    attempt_number=a.get("attempt_number", 0),
                    model_response=a.get("model_response", ""),
                    verdict=AttemptVerdict(a.get("verdict", "fail")),
                    score=a.get("score", 0.0),
                    errors=a.get("errors", []),
                    correction_prompt=a.get("correction_prompt", ""),
                    duration_sec=a.get("duration_sec", 0.0),
                    eval_count=a.get("eval_count", 0),
                    timestamp=a.get("timestamp", 0.0),
                )
            )
        return TrainingSession(
            id=data.get("id", ""),
            task=task,
            model_name=data.get("model_name", ""),
            attempts=attempts,
            status=data.get("status", "pending"),
            created_at=data.get("created_at", 0.0),
            finished_at=data.get("finished_at", 0.0),
            max_iterations=data.get("max_iterations", 5),
            temperature=data.get("temperature", 0.7),
        )


# ---------------------------------------------------------------------------
# Training engine — orchestrates the correction loop
# ---------------------------------------------------------------------------


@dataclass
class TrainingEngine:
    """Orchestrates the iterative training/correction loop."""

    client: OllamaClient
    store: SessionStore
    evaluator: Evaluator | None = None

    def __post_init__(self) -> None:
        if self.evaluator is None:
            self.evaluator = Evaluator(self.client)

    async def run_session(
        self,
        task: Task,
        model: str,
        *,
        max_iterations: int = 5,
        temperature: float = 0.7,
        on_attempt: Any = None,
    ) -> TrainingSession:
        """Run a full training session.

        Args:
            task: The task to train on.
            model: Ollama model name.
            max_iterations: Maximum correction attempts.
            temperature: Sampling temperature.
            on_attempt: Optional async callback(session, attempt) called after
                        each attempt for real-time UI updates.

        Returns:
            The completed TrainingSession with all attempts recorded.
        """
        assert self.evaluator is not None

        session = TrainingSession(
            task=task,
            model_name=model,
            max_iterations=max_iterations,
            temperature=temperature,
            status="running",
        )
        await self.store.save(session)

        # Build initial messages
        messages = [
            ChatMessage(role="user", content=task.instruction),
        ]

        for iteration in range(max_iterations):
            # --- Generate response ---
            t0 = time.time()
            try:
                result = await self.client.chat(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                )
            except Exception as exc:
                attempt = Attempt(
                    attempt_number=iteration + 1,
                    model_response=f"[ERROR] {exc}",
                    verdict=AttemptVerdict.FAIL,
                    score=0.0,
                    errors=[str(exc)],
                    duration_sec=time.time() - t0,
                )
                session.attempts.append(attempt)
                session.status = "failed"
                session.finished_at = time.time()
                await self.store.save(session)
                return session

            duration = time.time() - t0

            # --- Evaluate ---
            verdict, score, errors, feedback = await self.evaluator.evaluate(
                task=task,
                response=result.content,
                model=model,
            )

            # Build correction prompt for next iteration (even if passing,
            # we store it for the record)
            correction = Evaluator.build_correction_prompt(task, errors, feedback)

            attempt = Attempt(
                attempt_number=iteration + 1,
                model_response=result.content,
                verdict=verdict,
                score=score,
                errors=errors,
                correction_prompt=correction,
                duration_sec=duration,
                eval_count=result.eval_count,
            )
            session.attempts.append(attempt)
            await self.store.save(session)

            if on_attempt is not None:
                await on_attempt(session, attempt)

            # --- Check if we're done ---
            if verdict == AttemptVerdict.PASS or score >= 0.95:
                break

            # --- Append correction context for next round ---
            messages.append(ChatMessage(role="assistant", content=result.content))
            messages.append(ChatMessage(role="user", content=correction))

        session.status = "completed"
        session.finished_at = time.time()
        await self.store.save(session)
        return session
