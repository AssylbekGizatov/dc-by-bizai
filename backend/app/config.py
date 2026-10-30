from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    mode: str = field(default_factory=lambda: os.getenv("APP_MODE", "demo"))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "/tmp/grandmobile/copilot.sqlite3"))
    rules_path: str | None = field(default_factory=lambda: os.getenv("RULES_PATH") or None)
    taxonomy_path: str | None = field(default_factory=lambda: os.getenv("TAXONOMY_PATH") or None)
    api_token: str | None = field(default_factory=lambda: os.getenv("API_TOKEN") or None)
    enable_groq: bool = field(default_factory=lambda: flag("ENABLE_GROQ"))
    groq_api_key: str | None = field(default_factory=lambda: os.getenv("GROQ_API_KEY") or None)
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"))
    groq_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("GROQ_TIMEOUT_SECONDS", "4")))
    groq_max_retries: int = field(default_factory=lambda: int(os.getenv("GROQ_MAX_RETRIES", "1")))
    groq_input_usd_per_million: float | None = field(default_factory=lambda: float(os.environ["GROQ_INPUT_USD_PER_MILLION"]) if os.getenv("GROQ_INPUT_USD_PER_MILLION") else None)
    groq_output_usd_per_million: float | None = field(default_factory=lambda: float(os.environ["GROQ_OUTPUT_USD_PER_MILLION"]) if os.getenv("GROQ_OUTPUT_USD_PER_MILLION") else None)
    allow_private_data_to_groq: bool = field(default_factory=lambda: flag("ALLOW_PRIVATE_DATA_TO_GROQ"))
    local_encoder_path: str | None = field(default_factory=lambda: os.getenv("LOCAL_ENCODER_PATH") or None)
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()))
    frontend_dist: str | None = field(default_factory=lambda: os.getenv("FRONTEND_DIST") or None)
    max_request_bytes: int = 131_072
    cache_capacity: int = 512
    request_rate_per_minute: int = field(default_factory=lambda: int(os.getenv("REQUEST_RATE_PER_MINUTE", "120")))
    # Сколько обращений одного игрока за час считаются нормой; следующие помечаются как флуд.
    flood_limit_per_hour: int = field(default_factory=lambda: int(os.getenv("FLOOD_LIMIT_PER_HOUR", "5")))

    def __post_init__(self) -> None:
        if self.mode not in {"demo", "production", "test"}:
            raise ValueError("APP_MODE must be demo, test, or production")
        if self.enable_groq and self.groq_model not in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
            raise ValueError("This strict-schema Groq adapter supports openai/gpt-oss-20b or openai/gpt-oss-120b; select a verified model")
        if not 0.1 <= self.groq_timeout_seconds <= 30:
            raise ValueError("GROQ_TIMEOUT_SECONDS must be between 0.1 and 30")
        if not 0 <= self.groq_max_retries <= 2:
            raise ValueError("GROQ_MAX_RETRIES must be 0, 1, or 2")
        if self.mode == "production" and (not self.api_token or len(self.api_token) < 24):
            raise ValueError("Production requires API_TOKEN with at least 24 characters")
        if self.mode == "production" and not self.rules_path:
            raise ValueError("Production requires a private, approved RULES_PATH")
        if not 1 <= self.flood_limit_per_hour <= 1000:
            raise ValueError("FLOOD_LIMIT_PER_HOUR must be between 1 and 1000")
        if self.frontend_dist and not Path(self.frontend_dist).is_dir():
            raise ValueError("FRONTEND_DIST must be an existing frontend build directory")
