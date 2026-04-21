"""Telegram delivery channel over the public Bot API.

Each alert becomes **one** Telegram ``sendMessage`` call per configured
chat id — no batching at the API level, so a single malformed payload
can't poison the rest of a sweep. Messages use ``parse_mode=HTML``
rather than MarkdownV2: HTML has a much smaller escape surface
(``< > &``) and every edge-case character we see in team names, market
labels and bookmaker slugs renders correctly without manual escaping
beyond those three.

429 backoff is explicit and bounded: we honour ``parameters.retry_after``
when Telegram returns one, otherwise we use an exponential schedule.
Failures propagate to the caller via :class:`ChannelResult`; we do not
raise.
"""

from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from superbrain.alerts.config import AlertSettings
from superbrain.alerts.models import AlertRecord, ChannelResult

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE: Final = "https://api.telegram.org"
DEFAULT_MAX_ATTEMPTS: Final = 3
DEFAULT_BACKOFF_BASE: Final = 1.0
DEFAULT_TIMEOUT_SECONDS: Final = 10.0


class TelegramChannel:
    """Async Telegram Bot API client scoped to the alert pipeline.

    :param bot_token: bot token from @BotFather.
    :param chat_ids: recipient chat ids (``-100…`` for channels,
        positive integers for users / groups).
    :param client: optional injected :class:`httpx.AsyncClient` (tests
        pass a respx-mocked one; production code uses the default).
    :param concurrency: per-alert fan-out over the configured chat ids.
    :param max_attempts: retry budget per (alert, chat id) pair.
    :param backoff_base: base delay (seconds) for the fallback exponential
        schedule when the API does not supply ``retry_after``.
    :param sleep: injectable sleep coroutine, for deterministic testing.
    """

    name: str = "telegram"

    def __init__(
        self,
        *,
        bot_token: str,
        chat_ids: Sequence[str],
        client: httpx.AsyncClient | None = None,
        concurrency: int = 4,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        sleep: Any = None,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token must be non-empty")
        if not chat_ids:
            raise ValueError("at least one chat id is required")
        self._bot_token = bot_token
        self._chat_ids = tuple(chat_ids)
        self._client = client
        self._owns_client = client is None
        self._concurrency = max(1, concurrency)
        self._max_attempts = max(1, max_attempts)
        self._backoff_base = backoff_base
        self._sleep = sleep if sleep is not None else asyncio.sleep

    @classmethod
    def from_settings(cls, settings: AlertSettings) -> TelegramChannel | None:
        """Build a channel from env-derived settings; ``None`` when disabled."""
        if not settings.telegram_enabled:
            return None
        assert settings.telegram_bot_token is not None
        return cls(
            bot_token=settings.telegram_bot_token,
            chat_ids=settings.telegram_chat_ids,
            concurrency=settings.alert_concurrency,
        )

    async def send(self, alerts: Sequence[AlertRecord]) -> list[ChannelResult]:
        """Deliver every alert to every configured chat id.

        :param alerts: value-bet alerts to deliver.
        :return: one :class:`ChannelResult` per input alert; the status
            is ``"sent"`` when every chat id received the message,
            ``"partial"`` when at least one succeeded and
            ``"failed"`` when none did.
        """
        if not alerts:
            return []

        client, owns = await self._ensure_client()
        try:
            results: list[ChannelResult] = []
            for alert in alerts:
                result = await self._send_one(client, alert)
                results.append(result)
            return results
        finally:
            if owns:
                await client.aclose()

    async def _send_one(self, client: httpx.AsyncClient, alert: AlertRecord) -> ChannelResult:
        semaphore = asyncio.Semaphore(self._concurrency)
        text = render_message(alert)

        async def _to_chat(chat_id: str) -> tuple[bool, str]:
            async with semaphore:
                return await self._post_with_retry(client, chat_id, text)

        pairs = await asyncio.gather(
            *(_to_chat(cid) for cid in self._chat_ids), return_exceptions=False
        )
        oks = [ok for ok, _ in pairs]
        errors = [err for ok, err in pairs if not ok]
        now = datetime.now(tz=UTC)
        if all(oks):
            status = "sent"
            error = ""
        elif any(oks):
            status = "partial"
            error = "; ".join(errors)
        else:
            status = "failed"
            error = "; ".join(errors) or "all chat ids failed"
        return ChannelResult(
            alert_id=alert.alert_id,
            channel=self.name,
            status=status,
            sent_at=now,
            error=error,
        )

    async def _post_with_retry(
        self, client: httpx.AsyncClient, chat_id: str, text: str
    ) -> tuple[bool, str]:
        url = f"{TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        last_error = "no attempt made"
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await client.post(url, json=payload, timeout=DEFAULT_TIMEOUT_SECONDS)
            except httpx.HTTPError as exc:
                last_error = f"transport: {exc}"
                if attempt >= self._max_attempts:
                    break
                await self._sleep(self._backoff_base * (2 ** (attempt - 1)))
                continue

            if response.status_code == 429:
                retry_after = _parse_retry_after(response) or (
                    self._backoff_base * (2 ** (attempt - 1))
                )
                last_error = f"429 retry_after={retry_after:.1f}s"
                logger.warning(
                    "telegram 429 chat=%s attempt=%d retry_after=%.1f",
                    chat_id,
                    attempt,
                    retry_after,
                )
                if attempt >= self._max_attempts:
                    break
                await self._sleep(retry_after)
                continue

            if response.status_code >= 500:
                last_error = f"http {response.status_code}"
                if attempt >= self._max_attempts:
                    break
                await self._sleep(self._backoff_base * (2 ** (attempt - 1)))
                continue

            try:
                body = response.json()
            except ValueError:
                return False, f"malformed body (status={response.status_code})"

            if not isinstance(body, dict) or not body.get("ok", False):
                description = ""
                if isinstance(body, dict):
                    description = str(body.get("description", ""))
                return False, f"api error: {description or response.text[:200]}"
            return True, ""
        return False, last_error

    async def _ensure_client(self) -> tuple[httpx.AsyncClient, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(), True


def render_message(alert: AlertRecord) -> str:
    """Render an :class:`AlertRecord` as an HTML-formatted Telegram body.

    The format is a compact, mobile-friendly block:

    ``<b>{match}</b>`` — ``{league}`` · ``{kickoff_iso}``

    :param alert: alert record to format.
    :return: HTML-safe message body.
    """

    def esc(value: object) -> str:
        return html.escape(str(value), quote=False)

    match_line = f"<b>{esc(alert.home_team)} vs {esc(alert.away_team)}</b>"
    meta_parts: list[str] = []
    if alert.league:
        meta_parts.append(esc(alert.league))
    meta_parts.append(esc(alert.kickoff.isoformat()))
    meta = " · ".join(meta_parts)

    market_label = alert.label or alert.market.replace("_", " ").title()
    selection_line = f"<b>{esc(market_label)}</b> → {esc(alert.selection)}"

    edge_pct = alert.edge * 100.0
    prob_pct = alert.probability * 100.0
    book_pct = alert.book_probability * 100.0

    stats_line = (
        f"Edge <b>{edge_pct:+.1f}%</b> · odds {alert.odds:.2f} @ <i>{esc(alert.bookmaker)}</i>"
    )
    prob_line = f"Model {prob_pct:.1f}% · book {book_pct:.1f}%"

    return "\n".join([match_line, meta, selection_line, stats_line, prob_line])


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Extract ``retry_after`` from a Telegram 429 response, in seconds."""
    try:
        body = response.json()
    except ValueError:
        return _parse_retry_header(response.headers.get("Retry-After"))
    if isinstance(body, dict):
        params = body.get("parameters")
        if isinstance(params, dict) and "retry_after" in params:
            try:
                return float(params["retry_after"])
            except (TypeError, ValueError):
                pass
    return _parse_retry_header(response.headers.get("Retry-After"))


def _parse_retry_header(header: str | None) -> float | None:
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        return None
