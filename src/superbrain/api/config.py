"""Settings for the FastAPI backend.

All configuration is read from environment variables (or a ``.env`` file if
present). Settings are immutable once loaded; tests override them via
``create_app(settings=...)`` or by setting env vars before constructing a
``Settings`` instance.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Immutable env-driven configuration for the API server.

    :param lake_path: filesystem path that contains (or will contain) the Parquet lake
    :param api_tokens: tuple of shared bearer tokens that authorize API calls
    :param cors_origins: allowed origins for browser requests
    :param log_level: structlog / uvicorn root log level
    :param request_id_header: inbound + outbound header that carries the request id
    """

    model_config = SettingsConfigDict(
        env_prefix="SUPERBRAIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    lake_path: Path = Field(default=Path("./data/lake"), alias="SUPERBRAIN_LAKE_PATH")
    api_tokens: tuple[str, ...] = Field(default=("dev-token",), alias="SUPERBRAIN_API_TOKENS")
    cors_origins: tuple[str, ...] = Field(
        default=("http://localhost:5273",), alias="SUPERBRAIN_CORS_ORIGINS"
    )
    log_level: str = Field(default="INFO", alias="SUPERBRAIN_LOG_LEVEL")
    request_id_header: str = Field(default="x-request-id", alias="SUPERBRAIN_REQUEST_ID_HEADER")

    @field_validator("api_tokens", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            parts = tuple(item.strip() for item in v.split(",") if item.strip())
            return parts
        return v

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, v: str) -> str:
        return v.upper()
