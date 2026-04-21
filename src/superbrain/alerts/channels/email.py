"""SMTP-over-TLS email channel.

A single dispatch produces **one** email per sweep: the body batches
every admitted alert into a multipart (plain-text + HTML) message with a
cleanly-formatted table. Implicit TLS on the configured port
(``smtplib.SMTP_SSL`` — 465 is a safe default) is chosen over STARTTLS
because every provider we care about (Gmail, Mailgun, Zoho) speaks it,
and it avoids the race where the underlying socket is briefly
plaintext.

When no alerts are admitted the channel returns the empty list and
sends nothing — the dispatcher must not call us with an empty list, but
we guard against it anyway to keep the contract simple.
"""

from __future__ import annotations

import asyncio
import html
import logging
import smtplib
from collections.abc import Sequence
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Final

from superbrain.alerts.config import AlertSettings
from superbrain.alerts.models import AlertRecord, ChannelResult

logger = logging.getLogger(__name__)

DEFAULT_SUBJECT_PREFIX: Final = "[superbrain]"


class EmailChannel:
    """SMTP_SSL-based email delivery of batched alerts.

    :param host: SMTP host (must support implicit TLS on ``port``).
    :param port: SMTP port; defaults to 465.
    :param username: SMTP auth user.
    :param password: SMTP auth password.
    :param sender: ``From:`` header address (must match auth in most
        providers, e.g. Gmail).
    :param recipients: ``To:`` addresses.
    :param subject_prefix: fixed prefix for the generated subject.
    """

    name: str = "email"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        recipients: Sequence[str],
        subject_prefix: str = DEFAULT_SUBJECT_PREFIX,
    ) -> None:
        if not host:
            raise ValueError("host must be non-empty")
        if not recipients:
            raise ValueError("at least one recipient is required")
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._recipients = tuple(recipients)
        self._subject_prefix = subject_prefix

    @classmethod
    def from_settings(cls, settings: AlertSettings) -> EmailChannel | None:
        """Return a channel bound to ``settings`` or ``None`` when disabled."""
        if not settings.email_enabled:
            return None
        assert settings.smtp_host is not None
        assert settings.smtp_user is not None
        assert settings.smtp_password is not None
        assert settings.smtp_from is not None
        return cls(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            sender=settings.smtp_from,
            recipients=settings.alert_email_recipients,
        )

    async def send(self, alerts: Sequence[AlertRecord]) -> list[ChannelResult]:
        """Send a single digest email covering every alert.

        :param alerts: admitted alerts.
        :return: one :class:`ChannelResult` per alert — identical status
            across the batch because the entire batch succeeds or fails
            together (one SMTP transaction).
        """
        if not alerts:
            return []

        message = self._build_message(alerts)
        try:
            await asyncio.to_thread(self._send_sync, message)
            status = "sent"
            error = ""
        except Exception as exc:
            logger.exception("alerts.email send failed")
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
        now = datetime.now(tz=UTC)
        return [
            ChannelResult(
                alert_id=alert.alert_id,
                channel=self.name,
                status=status,
                sent_at=now,
                error=error,
            )
            for alert in alerts
        ]

    def _send_sync(self, message: EmailMessage) -> None:
        with smtplib.SMTP_SSL(self._host, self._port) as server:
            server.login(self._username, self._password)
            server.send_message(message)

    def _build_message(self, alerts: Sequence[AlertRecord]) -> EmailMessage:
        subject = _format_subject(alerts, prefix=self._subject_prefix)
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._sender
        msg["To"] = ", ".join(self._recipients)

        text_body = render_text(alerts)
        html_body = render_html(alerts)
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
        return msg


def _format_subject(alerts: Sequence[AlertRecord], *, prefix: str) -> str:
    count = len(alerts)
    if count == 1:
        alert = alerts[0]
        return f"{prefix} {alert.home_team} vs {alert.away_team} — {alert.edge * 100:+.1f}% edge"
    top_edge = max(a.edge for a in alerts) * 100
    return f"{prefix} {count} value bets ({top_edge:+.1f}% top edge)"


def render_text(alerts: Sequence[AlertRecord]) -> str:
    """Plain-text digest for the ``text/plain`` alternative."""
    lines = [f"{len(alerts)} value bet(s):", ""]
    for alert in alerts:
        market_label = alert.label or alert.market.replace("_", " ").title()
        lines.append(
            f"- {alert.home_team} vs {alert.away_team} ({alert.league or '?'}, "
            f"{alert.kickoff.isoformat()})"
        )
        lines.append(
            f"    {market_label} -> {alert.selection} @ {alert.odds:.2f} ({alert.bookmaker})"
        )
        lines.append(
            f"    edge {alert.edge * 100:+.2f}%, model "
            f"{alert.probability * 100:.1f}% vs book "
            f"{alert.book_probability * 100:.1f}%"
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(alerts: Sequence[AlertRecord]) -> str:
    """HTML digest used as the ``text/html`` alternative."""

    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    rows: list[str] = []
    for alert in alerts:
        market_label = alert.label or alert.market.replace("_", " ").title()
        rows.append(
            "<tr>"
            f"<td>{esc(alert.home_team)} vs {esc(alert.away_team)}</td>"
            f"<td>{esc(alert.league or '')}</td>"
            f"<td>{esc(alert.kickoff.isoformat())}</td>"
            f"<td>{esc(market_label)}</td>"
            f"<td>{esc(alert.selection)}</td>"
            f"<td>{alert.odds:.2f}</td>"
            f"<td>{esc(alert.bookmaker)}</td>"
            f"<td><strong>{alert.edge * 100:+.2f}%</strong></td>"
            f"<td>{alert.probability * 100:.1f}% / {alert.book_probability * 100:.1f}%</td>"
            "</tr>"
        )

    thead = (
        "<tr>"
        "<th>Match</th><th>League</th><th>Kickoff</th><th>Market</th>"
        "<th>Selection</th><th>Odds</th><th>Book</th><th>Edge</th>"
        "<th>Model / Book</th>"
        "</tr>"
    )
    table = (
        '<table border="1" cellpadding="6" cellspacing="0" '
        'style="border-collapse:collapse;font-family:-apple-system,Segoe UI,sans-serif;">'
        f"<thead>{thead}</thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )
    return f"<!doctype html><html><body><p>{len(alerts)} value bet(s):</p>{table}</body></html>"
