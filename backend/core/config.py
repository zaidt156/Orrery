from __future__ import annotations

import pathlib

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # local-dev only; real credentials live in the keychain (security.md §1)
    database_url: str | None = None
    api_host: str = "127.0.0.1"  # localhost only (security.md §7)
    api_port: int = 8765
    orrery_dev: bool = False  # True = Vite dev server; False = serve built ui/dist
    vite_url: str = "http://localhost:5173"

    # production-tunable limits (override via .env) — plan P3 #24
    sandbox_timeout_seconds: int = 60   # max wall-clock for model-written code in the sandbox
    rag_top_k: int = 5                  # chunks retrieved per "use my data" query
    max_upload_bytes: int = 64 * 1024 * 1024  # request body cap (multi-image messages)


settings = Settings()
