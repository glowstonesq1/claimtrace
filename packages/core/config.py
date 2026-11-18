"""Settings from environment variables. Nothing secret is ever logged or returned by the API."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("CLAIMTRACE_DB", "./data/claimtrace.db"))
    host: str = field(default_factory=lambda: os.environ.get("CLAIMTRACE_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("CLAIMTRACE_PORT", "8000")))
    api_token: str | None = field(default_factory=lambda: os.environ.get("CLAIMTRACE_API_TOKEN") or None)
    allowed_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.environ.get("CLAIMTRACE_ALLOWED_ORIGINS", "").split(",") if o.strip()])
    allow_url_ingestion: bool = field(default_factory=lambda: _bool("CLAIMTRACE_ALLOW_URL_INGESTION"))
    llm_provider: str = field(default_factory=lambda: os.environ.get("CLAIMTRACE_LLM_PROVIDER", "rules"))
    llm_base_url: str | None = field(default_factory=lambda: os.environ.get("CLAIMTRACE_LLM_BASE_URL") or None)
    llm_model: str | None = field(default_factory=lambda: os.environ.get("CLAIMTRACE_LLM_MODEL") or None)
    llm_api_key: str | None = field(default_factory=lambda: os.environ.get("CLAIMTRACE_LLM_API_KEY") or None,
                                    repr=False)
    retention_days: int | None = field(default_factory=lambda: int(v) if (
        v := os.environ.get("CLAIMTRACE_RETENTION_DAYS")) else None)
    rate_limit_per_minute: int = field(default_factory=lambda: int(os.environ.get("CLAIMTRACE_RATE_LIMIT", "120")))

    @property
    def llm_host(self) -> str | None:
        return urlsplit(self.llm_base_url).hostname if self.llm_base_url else None

    @property
    def llm_is_external(self) -> bool:
        """Anything not on this machine counts as external and needs per-document opt-in (D14)."""
        host = self.llm_host
        return bool(host) and host not in ("localhost", "127.0.0.1", "::1", "ollama", "host.docker.internal")

    def public(self) -> dict:
        return {
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_endpoint_host": self.llm_host,
            "llm_is_external": self.llm_is_external,
            "url_ingestion_enabled": self.allow_url_ingestion,
            "auth_required": bool(self.api_token),
            "retention_days": self.retention_days,
        }
