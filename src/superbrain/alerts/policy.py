"""Per-run filtering of value bets into alert-worthy records.

A single :class:`AlertPolicy` instance is stateful across one dispatch:
it tracks how many alerts have been admitted so far, which matches have
hit the per-match cap, and which ``alert_id`` collisions we've already
suppressed. The dispatcher builds a fresh policy per sweep and hands it
the previously-sent alert ids (loaded from the sink within the dedup
window) so that re-runs of the same sweep inside a day never re-alert.

``should_alert`` is the primary check — it is intentionally side-effect-ful
(it *admits* on success) so that callers can drive it in a single pass
without a separate ``admit`` step. Tests can introspect admissions via
:attr:`AlertPolicy.admitted`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from superbrain.alerts.models import AlertRecord

if TYPE_CHECKING:
    from superbrain.alerts.config import AlertSettings
    from superbrain.engine.pipeline import ValueBet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RejectionReason:
    """Why a value bet was rejected — useful for reports and tests."""

    kind: str
    detail: str = ""


class AlertPolicy:
    """Decide which value bets become alerts in one dispatch.

    :param settings: alert settings (thresholds + caps).
    :param previous_alert_ids: iterable of ``alert_id`` values already
        sent inside the dedup window; anything colliding with these is
        suppressed.
    """

    def __init__(
        self,
        settings: AlertSettings,
        previous_alert_ids: Iterable[str] | None = None,
    ) -> None:
        self._settings = settings
        self._suppressed: set[str] = set(previous_alert_ids or ())
        self._admitted: list[AlertRecord] = []
        self._per_match_counts: dict[str, int] = {}
        self._rejections: dict[str, RejectionReason] = {}

    @property
    def admitted(self) -> list[AlertRecord]:
        """Records admitted so far (stable order, oldest first)."""
        return list(self._admitted)

    @property
    def rejections(self) -> dict[str, RejectionReason]:
        """Map ``alert_id`` → reason for every rejected value bet."""
        return dict(self._rejections)

    def should_alert(self, value_bet: ValueBet) -> bool:
        """Decide whether ``value_bet`` becomes an alert.

        Applies, in order: edge threshold, minimum probability, per-run
        cap, per-match cap, dedup-window check. Records a rejection
        reason (for debugging) when the answer is ``False``. Admits the
        record on success so that subsequent calls see the updated
        per-match counter.

        :param value_bet: pipeline-produced value bet.
        :return: ``True`` if the bet was admitted and should be dispatched.
        """
        record = AlertRecord.from_value_bet(value_bet)
        s = self._settings

        if value_bet.edge < s.alert_edge_threshold:
            self._reject(record, "edge_below_threshold", f"{value_bet.edge:.4f}")
            return False
        if value_bet.priced.model_probability < s.alert_min_probability:
            self._reject(
                record,
                "probability_below_floor",
                f"{value_bet.priced.model_probability:.4f}",
            )
            return False
        if len(self._admitted) >= s.alert_max_per_run:
            self._reject(record, "max_per_run", str(s.alert_max_per_run))
            return False

        match_count = self._per_match_counts.get(record.match_id, 0)
        if match_count >= s.alert_per_match_cap:
            self._reject(record, "per_match_cap", str(s.alert_per_match_cap))
            return False

        if record.alert_id in self._suppressed:
            self._reject(record, "dedup")
            return False

        self._admit(record)
        return True

    def filter(self, value_bets: Iterable[ValueBet]) -> list[AlertRecord]:
        """Evaluate every bet in order and return the admitted records.

        :param value_bets: iterable of pipeline value bets.
        :return: admitted :class:`AlertRecord` list (oldest first).
        """
        for vb in value_bets:
            self.should_alert(vb)
        return self.admitted

    def _admit(self, record: AlertRecord) -> None:
        self._admitted.append(record)
        self._per_match_counts[record.match_id] = self._per_match_counts.get(record.match_id, 0) + 1
        self._suppressed.add(record.alert_id)

    def _reject(self, record: AlertRecord, kind: str, detail: str = "") -> None:
        self._rejections[record.alert_id] = RejectionReason(kind=kind, detail=detail)
        logger.debug(
            "alerts.policy rejected %s reason=%s detail=%s",
            record.alert_id,
            kind,
            detail,
        )
