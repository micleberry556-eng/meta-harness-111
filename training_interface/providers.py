"""External API providers — connect to Z.ai (Grok), OpenAI, Anthropic, Google,
or any OpenAI-compatible API endpoint.

All providers use the OpenAI chat completions format since most modern APIs
(including xAI/Grok, Anthropic via proxy, Google Gemini) support it.

Providers are stored in SQLite and managed through the admin panel.
The ``UnifiedClient`` wraps both local Ollama and external providers behind
a single ``chat()`` interface so the rest of the app doesn't need to care
which backend is being used.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite
import httpx

from training_interface.ollama_client import ChatMessage, GenerationResult, OllamaClient

# ---------------------------------------------------------------------------
# Known provider presets
# ---------------------------------------------------------------------------

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "xai": {
        "name": "Z.ai / Grok (xAI)",
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-3-latest",
        "docs": "https://docs.x.ai/docs",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "docs": "https://platform.openai.com/docs",
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-4-20250514",
        "docs": "https://docs.anthropic.com",
    },
    "google": {
        "name": "Google (Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.0-flash",
        "docs": "https://ai.google.dev/docs",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "docs": "https://platform.deepseek.com/docs",
    },
    "meta_llama": {
        "name": "Meta Llama (official API)",
        "base_url": "https://api.llama.com/v1",
        "default_model": "Llama-4-Maverick-17B-128E-Instruct-FP8",
        "docs": "https://llama.developer.meta.com/docs/overview/",
    },
    "custom": {
        "name": "Custom OpenAI-compatible",
        "base_url": "",
        "default_model": "",
        "docs": "",
    },
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class APIProvider:
    """A configured external API provider."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    provider_type: str = ""  # xai, openai, anthropic, google, custom
    name: str = ""  # human-readable label
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    models: list[str] = field(default_factory=list)  # available model names
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_type": self.provider_type,
            "name": self.name,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "default_model": self.default_model,
            "models": self.models,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    def to_safe_dict(self) -> dict[str, Any]:
        """Dict with masked API key for UI display."""
        d = self.to_dict()
        if self.api_key:
            d["api_key"] = self.api_key[:8] + "..." + self.api_key[-4:]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> APIProvider:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            provider_type=data.get("provider_type", ""),
            name=data.get("name", ""),
            base_url=data.get("base_url", ""),
            api_key=data.get("api_key", ""),
            default_model=data.get("default_model", ""),
            models=data.get("models", []),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", time.time()),
        )


# ---------------------------------------------------------------------------
# Provider store (SQLite)
# ---------------------------------------------------------------------------

_PROVIDER_SCHEMA = """\
CREATE TABLE IF NOT EXISTS api_providers (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    name TEXT DEFAULT '',
    provider_type TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    created_at REAL NOT NULL
);
"""


class ProviderStore:
    """Persists API provider configurations to SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self._db_path)
        await conn.execute(_PROVIDER_SCHEMA)
        await conn.commit()
        return conn

    async def save(self, provider: APIProvider) -> None:
        conn = await self._connect()
        try:
            await conn.execute(
                "INSERT OR REPLACE INTO api_providers "
                "(id, data, name, provider_type, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    provider.id,
                    json.dumps(provider.to_dict()),
                    provider.name,
                    provider.provider_type,
                    1 if provider.enabled else 0,
                    provider.created_at,
                ),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def load(self, provider_id: str) -> APIProvider | None:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "SELECT data FROM api_providers WHERE id = ?", (provider_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return APIProvider.from_dict(data)
        finally:
            await conn.close()

    async def list_providers(self, enabled_only: bool = False) -> list[APIProvider]:
        conn = await self._connect()
        try:
            query = "SELECT data FROM api_providers"
            if enabled_only:
                query += " WHERE enabled = 1"
            query += " ORDER BY created_at"
            cursor = await conn.execute(query)
            rows = await cursor.fetchall()
            results: list[APIProvider] = []
            for row in rows:
                data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                results.append(APIProvider.from_dict(data))
            return results
        finally:
            await conn.close()

    async def delete(self, provider_id: str) -> bool:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "DELETE FROM api_providers WHERE id = ?", (provider_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# External API client (OpenAI-compatible)
# ---------------------------------------------------------------------------


class ExternalAPIClient:
    """Calls any OpenAI-compatible chat completions endpoint."""

    def __init__(self, provider: APIProvider) -> None:
        self._provider = provider
        self._base_url = provider.base_url.rstrip("/")

    async def chat(
        self,
        model: str,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> GenerationResult:
        """Send a chat completion request."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }

        # Auth header varies by provider
        if self._provider.provider_type == "anthropic":
            headers["x-api-key"] = self._provider.api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {self._provider.api_key}"

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = f"{self._base_url}/chat/completions"

        t0 = time.time()
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        duration_ns = int((time.time() - t0) * 1e9)

        # Parse OpenAI-format response
        choices = data.get("choices", [])
        content = ""
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "")

        usage = data.get("usage", {})

        return GenerationResult(
            content=content,
            model=data.get("model", model),
            total_duration_ns=duration_ns,
            eval_count=usage.get("completion_tokens", 0),
            prompt_eval_count=usage.get("prompt_tokens", 0),
        )

    async def test_connection(self) -> tuple[bool, str]:
        """Test if the provider is reachable and the API key works."""
        try:
            result = await self.chat(
                model=self._provider.default_model,
                messages=[ChatMessage(role="user", content="Hi")],
                max_tokens=10,
            )
            return True, f"OK — model responded: {result.content[:50]}"
        except httpx.HTTPStatusError as exc:
            return False, f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        except Exception as exc:
            return False, str(exc)


# ---------------------------------------------------------------------------
# Unified client — wraps Ollama + external providers
# ---------------------------------------------------------------------------


class UnifiedClient:
    """Single interface for both local Ollama and external API providers.

    Model names are prefixed to distinguish sources:
    - "ollama:codellama:latest" → local Ollama
    - "xai:grok-3-latest" → Z.ai/Grok
    - "openai:gpt-4o" → OpenAI
    - Plain names without prefix → assumed Ollama (backward compatible)
    """

    def __init__(self, ollama: OllamaClient, provider_store: ProviderStore) -> None:
        self._ollama = ollama
        self._provider_store = provider_store

    def parse_model_ref(self, model_ref: str) -> tuple[str, str]:
        """Parse 'provider:model' into (provider_id_or_type, model_name).

        Returns ("ollama", model_name) for local models.
        """
        if ":" in model_ref:
            # Check if it looks like a provider prefix (not an Ollama tag like "codellama:latest")
            prefix, rest = model_ref.split(":", 1)
            if prefix in (
                "ollama",
                "xai",
                "openai",
                "anthropic",
                "google",
                "deepseek",
                "meta_llama",
            ) or (
                len(prefix) == 12 and rest  # provider ID
            ):
                return prefix, rest
        # Default: treat as Ollama model name
        return "ollama", model_ref

    async def chat(
        self,
        model_ref: str,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> GenerationResult:
        """Route chat to the appropriate backend."""
        provider_key, model_name = self.parse_model_ref(model_ref)

        if provider_key == "ollama":
            return await self._ollama.chat(
                model=model_name,
                messages=messages,
                temperature=temperature,
                num_predict=max_tokens,
            )

        # Find the provider
        provider = await self._find_provider(provider_key)
        if provider is None:
            raise ValueError(f"Provider not found: {provider_key}")

        client = ExternalAPIClient(provider)
        return await client.chat(
            model=model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def list_all_models(self) -> list[dict[str, Any]]:
        """List all available models from all sources."""
        models: list[dict[str, Any]] = []

        # Ollama models
        try:
            ollama_models = await self._ollama.list_models()
            for m in ollama_models:
                models.append(
                    {
                        "ref": f"ollama:{m.name}",
                        "name": m.name,
                        "provider": "ollama",
                        "provider_name": "Ollama (local)",
                        "size": m.size,
                        "size_gb": round(m.size / (1024**3), 2) if m.size else 0,
                    }
                )
        except Exception:
            pass

        # External providers
        providers = await self._provider_store.list_providers(enabled_only=True)
        for p in providers:
            for model_name in p.models:
                models.append(
                    {
                        "ref": f"{p.id}:{model_name}",
                        "name": model_name,
                        "provider": p.provider_type,
                        "provider_name": p.name,
                        "size": 0,
                        "size_gb": 0,
                    }
                )
            # Always include default model if not in list
            if p.default_model and p.default_model not in p.models:
                models.append(
                    {
                        "ref": f"{p.id}:{p.default_model}",
                        "name": p.default_model,
                        "provider": p.provider_type,
                        "provider_name": p.name,
                        "size": 0,
                        "size_gb": 0,
                    }
                )

        return models

    async def _find_provider(self, key: str) -> APIProvider | None:
        """Find provider by ID or type."""
        # Try by ID first
        provider = await self._provider_store.load(key)
        if provider:
            return provider

        # Try by type (e.g., "xai", "openai")
        providers = await self._provider_store.list_providers(enabled_only=True)
        for p in providers:
            if p.provider_type == key:
                return p
        return None
