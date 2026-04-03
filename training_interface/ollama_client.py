"""Ollama HTTP client — manages models and runs inference against a local Ollama server.

Communicates with the Ollama REST API (default http://localhost:11434).
All methods are async and use httpx for non-blocking I/O.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx


def _base_url() -> str:
    """Return the Ollama API base URL from env or default."""
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


@dataclass
class OllamaModel:
    """Metadata for a locally available Ollama model."""

    name: str
    size: int = 0  # bytes
    parameter_size: str = ""
    quantization: str = ""
    family: str = ""
    digest: str = ""
    modified_at: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> OllamaModel:
        """Build from the Ollama /api/tags response item."""
        details = data.get("details", {})
        return cls(
            name=data.get("name", ""),
            size=data.get("size", 0),
            parameter_size=details.get("parameter_size", ""),
            quantization=details.get("quantization_level", ""),
            family=details.get("family", ""),
            digest=data.get("digest", ""),
            modified_at=data.get("modified_at", ""),
        )


@dataclass
class ChatMessage:
    """A single message in a chat conversation."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class GenerationResult:
    """Result of a single generation (non-streaming)."""

    content: str
    model: str
    total_duration_ns: int = 0
    eval_count: int = 0
    prompt_eval_count: int = 0
    done: bool = True


@dataclass
class PullProgress:
    """Progress update while pulling a model."""

    status: str
    digest: str = ""
    total: int = 0
    completed: int = 0

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(100.0, (self.completed / self.total) * 100.0)


@dataclass
class OllamaClient:
    """Async client for the Ollama REST API."""

    base_url: str = field(default_factory=_base_url)
    timeout: float = 600.0  # generous timeout for large model pulls

    # --- Health ---

    async def is_available(self) -> bool:
        """Check whether the Ollama server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            return False

    # --- Model management ---

    async def list_models(self) -> list[OllamaModel]:
        """Return all locally available models."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        return [OllamaModel.from_api(m) for m in data.get("models", [])]

    async def pull_model(self, name: str) -> AsyncIterator[PullProgress]:
        """Pull a model from the Ollama registry, yielding progress updates."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/pull",
                json={"name": name, "stream": True},
                timeout=self.timeout,
            ) as resp:
                resp.raise_for_status()
                import json as _json

                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue
                    yield PullProgress(
                        status=chunk.get("status", ""),
                        digest=chunk.get("digest", ""),
                        total=chunk.get("total", 0),
                        completed=chunk.get("completed", 0),
                    )

    async def delete_model(self, name: str) -> bool:
        """Delete a locally stored model. Returns True on success."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                "DELETE",
                f"{self.base_url}/api/delete",
                json={"name": name},
            )
            return resp.status_code == 200

    async def show_model(self, name: str) -> dict[str, Any]:
        """Return detailed info about a model (parameters, template, etc.)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/show",
                json={"name": name},
            )
            resp.raise_for_status()
            return resp.json()

    # --- Inference ---

    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        num_predict: int = 2048,
    ) -> GenerationResult:
        """Send a chat completion request (non-streaming)."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

        msg = data.get("message", {})
        return GenerationResult(
            content=msg.get("content", ""),
            model=data.get("model", model),
            total_duration_ns=data.get("total_duration", 0),
            eval_count=data.get("eval_count", 0),
            prompt_eval_count=data.get("prompt_eval_count", 0),
        )

    async def chat_stream(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        num_predict: int = 2048,
    ) -> AsyncIterator[str]:
        """Stream chat tokens one by one."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            ) as resp:
                resp.raise_for_status()
                import json as _json

                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue
                    msg = chunk.get("message", {})
                    token = msg.get("content", "")
                    if token:
                        yield token

    async def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.7,
        num_predict: int = 2048,
    ) -> GenerationResult:
        """Raw generate endpoint (non-chat, non-streaming)."""
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

        return GenerationResult(
            content=data.get("response", ""),
            model=data.get("model", model),
            total_duration_ns=data.get("total_duration", 0),
            eval_count=data.get("eval_count", 0),
            prompt_eval_count=data.get("prompt_eval_count", 0),
        )
