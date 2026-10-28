from pathlib import Path
from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=("settings_",))
    database_url: str = "postgresql://medical_ai:local_dev_only@127.0.0.1:5433/medical_ai"
    api_base_url: str = "http://127.0.0.1:8000"
    ollama_base_url: str = "http://127.0.0.1:11434"
    chat_provider: str = "ollama"
    chat_model: str = "gemma3:4b"
    embedding_model: str = "qwen3-embedding:0.6b"
    data_dir: Path = Path("data")
    libreoffice_bin: str | None = None
    word_conversion_timeout_seconds: float = Field(90, gt=0, le=300)
    max_files: int = Field(5, ge=1, le=50)
    max_file_mb: int = Field(20, ge=1)
    max_total_mb: int = Field(50, ge=1)
    max_total_pages: int = Field(300, ge=1)
    chunk_target_chars: int = Field(1500, ge=200)
    chunk_overlap_chars: int = Field(200, ge=0)
    chunk_max_chars: int = Field(2000, ge=200)
    embedding_batch_size: int = Field(8, ge=1, le=32)
    retrieval_candidates: int = Field(8, ge=1, le=40)
    max_context_chunks: int = Field(6, ge=1, le=12)
    max_context_chars: int = Field(8000, ge=200)
    model_context_tokens: int = Field(16384, ge=2048)
    max_output_tokens: int = Field(512, ge=64)
    model_timeout_seconds: float = Field(120, gt=0)
    session_ttl_hours: int = Field(24, ge=1)
    min_similarity: float = Field(-1.0, ge=-1, le=1)

    @model_validator(mode="after")
    def validate_budgets(self):
        if not self.chunk_overlap_chars < self.chunk_target_chars <= self.chunk_max_chars:
            raise ValueError("Require overlap < target <= maximum chunk characters")
        return self


@lru_cache
def get_settings():
    return Settings()
