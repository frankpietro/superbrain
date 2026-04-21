"""Pydantic-settings configuration for the alert pipeline.

Every knob is driven by an ``SUPERBRAIN_*`` environment variable (or a
``.env`` entry), matching the convention used by the rest of the backend.

Secrets are optional: if a backend's credentials are missing, the
corresponding channel is simply disabled — the dispatcher skips it
rather than erroring. This keeps the unit-test matrix small and makes
partial deployments (Telegram-only on a personal Fly machine, email-only
on GitHub Actions fallback) first-class.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AlertSettings(BaseSettings):
    """Env-driven configuration for the alert pipeline.

    :ivar alert_edge_threshold: minimum ``edge`` (model - book probability)
        to fire an alert. Default 0.05 — the same edge used by the engine.
    :ivar alert_min_probability: floor on ``model_probability``. Default
        0.35 so we don't alert on wildly improbable longshots even at
        positive EV.
    :ivar alert_max_per_run: upper bound on alerts fired per dispatch,
        to avoid spamming when the engine floods us.
    :ivar alert_per_match_cap: max alerts per unique match inside one
        dispatch. 3 is enough to surface the top edges without drowning
        a single fixture's feed.
    :ivar alert_dedup_hours: de-dup window (hours) against the sink.
        24 means "don't re-alert the same bet twice in a calendar day";
        the natural key also collapses to ``date(kickoff)`` so re-runs
        of the sweep inside a day are always idempotent.
    :ivar alert_lookahead_hours: how far into the future the scheduler
        hook pulls fixtures. 48 h covers tomorrow plus today.
    :ivar alert_concurrency: per-channel fan-out concurrency. For
        Telegram this controls the number of in-flight HTTP requests
        (per chat id x alert); default 4 is plenty for the 429 budget.
    :ivar alert_sink_path: where the parquet log of sent alerts lives.
    :ivar lake_path: fallback lake location for the CLI entry-point.
    """

    model_config = SettingsConfigDict(
        env_prefix="SUPERBRAIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    alert_edge_threshold: float = Field(
        default=0.05, alias="SUPERBRAIN_ALERT_EDGE_THRESHOLD", ge=0.0
    )
    alert_min_probability: float = Field(
        default=0.35, alias="SUPERBRAIN_ALERT_MIN_PROBABILITY", ge=0.0, le=1.0
    )
    alert_max_per_run: int = Field(default=20, alias="SUPERBRAIN_ALERT_MAX_PER_RUN", ge=0)
    alert_per_match_cap: int = Field(default=3, alias="SUPERBRAIN_ALERT_PER_MATCH_CAP", ge=1)
    alert_dedup_hours: int = Field(default=24, alias="SUPERBRAIN_ALERT_DEDUP_HOURS", ge=1)
    alert_lookahead_hours: int = Field(default=48, alias="SUPERBRAIN_ALERT_LOOKAHEAD_HOURS", ge=1)
    alert_concurrency: int = Field(default=4, alias="SUPERBRAIN_ALERT_CONCURRENCY", ge=1)

    alert_sink_path: Path = Field(
        default=Path("./data/alerts/sent_alerts.parquet"),
        alias="SUPERBRAIN_ALERT_SINK_PATH",
    )
    lake_path: Path = Field(default=Path("./data/lake"), alias="SUPERBRAIN_LAKE_PATH")

    telegram_bot_token: str | None = Field(default=None, alias="SUPERBRAIN_TELEGRAM_BOT_TOKEN")
    telegram_chat_ids: tuple[str, ...] = Field(default=(), alias="SUPERBRAIN_TELEGRAM_CHAT_IDS")

    smtp_host: str | None = Field(default=None, alias="SUPERBRAIN_SMTP_HOST")
    smtp_port: int = Field(default=465, alias="SUPERBRAIN_SMTP_PORT", ge=1, le=65535)
    smtp_user: str | None = Field(default=None, alias="SUPERBRAIN_SMTP_USER")
    smtp_password: str | None = Field(default=None, alias="SUPERBRAIN_SMTP_PASSWORD")
    smtp_from: str | None = Field(default=None, alias="SUPERBRAIN_SMTP_FROM")
    alert_email_recipients: tuple[str, ...] = Field(
        default=(), alias="SUPERBRAIN_ALERT_EMAIL_RECIPIENTS"
    )

    @field_validator("telegram_chat_ids", "alert_email_recipients", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return tuple(item.strip() for item in v.split(",") if item.strip())
        return v

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token) and bool(self.telegram_chat_ids)

    @property
    def email_enabled(self) -> bool:
        return (
            self.smtp_host is not None
            and self.smtp_user is not None
            and self.smtp_password is not None
            and self.smtp_from is not None
            and bool(self.alert_email_recipients)
        )
