from __future__ import annotations

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from backend.core import paths

PROJECT_ROOT = paths.project_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(paths.settings_file()),
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
    # On-device embedding model for RAG. Multilingual by default (~50 languages); must be 384-dim to
    # fit the existing vector column (a mismatch is refused at load time — see rag._get_embedder).
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    max_upload_bytes: int = 64 * 1024 * 1024  # request body cap (multi-image messages)
    generated_file_ttl_hours: int = 168  # auto-delete generated files older than this (7 days)

    # Model-backed intent decider: before an expensive/irreversible generative action (file/image/
    # audio/project), confirm the route with the model reading the ACTUAL current turn — the
    # root-cause fix for regex misroutes (a calc after a song made a WAV). Plain chat never calls it.
    model_intent_decider: bool = True

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Insert the TOML layers below `.env` (ADR-004).

        Order here is highest precedence first, so real environment variables still win, then
        `.env`, then the profile/home TOML files, then field defaults. `backend.core.profiles`
        owns what those files are and `--dump-config` reports which one supplied each value.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _TomlLayers(settings_cls),
            file_secret_settings,
        )


class _TomlLayers(PydanticBaseSettingsSource):
    """The profile and home TOML layers, merged so home wins over profile."""

    def get_field_value(self, field, field_name):  # pragma: no cover - required by the interface
        return None, field_name, False

    def __call__(self) -> dict[str, object]:
        from backend.core import profiles

        known = set(self.settings_cls.model_fields)
        return {k: v for k, v in profiles.merged_file_values().items() if k in known}


settings = Settings()
