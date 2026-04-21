"""Regression tests for the env-driven settings pipeline.

These tests exercise ``EnvSettingsSource`` — the real path owners hit when
they set ``SUPERBRAIN_*`` variables via ``.env`` or the shell — rather than
the tuple-injection fast path the rest of the API test suite uses. Without
this guard, a future ``pydantic_settings`` release that re-broke the
``NoDecode`` / CSV interplay would surface only at runtime.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from superbrain.api.config import Settings

_ENV_KEYS = (
    "SUPERBRAIN_LAKE_PATH",
    "SUPERBRAIN_API_TOKENS",
    "SUPERBRAIN_CORS_ORIGINS",
    "SUPERBRAIN_LOG_LEVEL",
    "SUPERBRAIN_REQUEST_ID_HEADER",
)


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Strip superbrain env vars so each test starts from a known state.

    ``EnvSettingsSource`` reads live ``os.environ`` and — critically —
    ``env_file='.env'`` loads a repo-root dotenv when one exists; that
    would otherwise shadow our ``setenv`` calls.
    """
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SUPERBRAIN_DISABLE_ENV_FILE", "1")
    yield monkeypatch


def _settings_no_env_file() -> Settings:
    # Disable the .env loader for this instantiation so the tests don't
    # depend on whether the owner has a local .env committed beside them.
    return Settings(_env_file=None)


def test_api_tokens_parse_csv_from_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SUPERBRAIN_API_TOKENS", "alpha,beta,  gamma  ")
    settings = _settings_no_env_file()
    assert settings.api_tokens == ("alpha", "beta", "gamma")


def test_api_tokens_single_value_from_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SUPERBRAIN_API_TOKENS", "dev-token")
    settings = _settings_no_env_file()
    assert settings.api_tokens == ("dev-token",)


def test_cors_origins_parse_csv_from_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv(
        "SUPERBRAIN_CORS_ORIGINS",
        "http://localhost:5273,http://localhost:3000",
    )
    settings = _settings_no_env_file()
    assert settings.cors_origins == (
        "http://localhost:5273",
        "http://localhost:3000",
    )


def test_defaults_when_env_unset(clean_env: pytest.MonkeyPatch) -> None:
    settings = _settings_no_env_file()
    assert settings.api_tokens == ("dev-token",)
    assert settings.cors_origins == ("http://localhost:5273",)
    assert settings.log_level == "INFO"
    assert settings.request_id_header == "x-request-id"


def test_log_level_is_uppercased_from_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("SUPERBRAIN_LOG_LEVEL", "debug")
    settings = _settings_no_env_file()
    assert settings.log_level == "DEBUG"
