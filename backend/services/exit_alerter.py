import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

from database import get_setting

logger = logging.getLogger(__name__)


def _rel_change(new: float, old: float) -> float:
    """Fractional change of `new` vs `old`, with a $1 floor on the denominator so
    tiny dollar values don't look like huge swings."""
    return abs(new - old) / max(abs(old), 1.0)


class ExitAlerter:
    """Watches OPEN hedged pairs and fires a take-profit alert when a pair can be
    closed for a profit above the user's threshold (`min_exit_profit_pct`).

    De-dup mirrors the entry scanner: a pair re-alerts ONLY when the exit gets
    materially BETTER than what we last alerted — so a position sitting just over
    the line doesn't ping every few seconds. A pair that stops qualifying and
    comes back >2h later re-arms and alerts fresh.
    """

    # Re-alert the same pair only when the exit IMPROVES past these.
    ROI_DELTA = 0.5            # exit ROI improves by >= 0.5 percentage points, or
    VALUE_REL = 0.10           # net proceeds improve by >= 10%
    MIN_REALERT_GAP = timedelta(minutes=15)   # hard floor between alerts per pair
    ALERT_REARM = timedelta(hours=2)          # gone this long -> next qualify is fresh

    def __init__(self, db: aiosqlite.Connection, portfolio_tracker, queue):
        self._db = db
        self._pt = portfolio_tracker
        self._queue = queue
        # per matched_market_id: last-alerted (roi, net), when, and when it went away
        self._sig: dict[int, tuple[float, float]] = {}
        self._last_at: dict[int, datetime] = {}
        self._gone_since: dict[int, datetime] = {}

    async def scan(self) -> None:
        notify = await get_setting(self._db, "tg_notify_enabled", "1")
        if notify != "1":
            return  # alerts globally muted -> don't compute or ping
        try:
            min_pct = float(await get_setting(self._db, "min_exit_profit_pct", "1.0") or 1.0)
        except ValueError:
            min_pct = 1.0

        opps = await self._pt.scan_pair_exits(min_pct)
        now = datetime.now(timezone.utc)
        seen: set[int] = set()

        for o in opps:
            mm = o["matched_market_id"]
            seen.add(mm)
            roi = o["best"]["roi"]
            net = o["best"]["net"]

            gone = self._gone_since.pop(mm, None)
            if gone is not None and now - gone > self.ALERT_REARM:
                self._sig.pop(mm, None)
                self._last_at.pop(mm, None)

            if self._should_alert(mm, roi, net, now):
                self._sig[mm] = (roi, net)
                self._last_at[mm] = now
                await self._queue.put({"kind": "exit", "exit": o})
                logger.info(
                    "EXIT ALERT mm=%d roi=%.2f%% net$%.2f via %s",
                    mm, roi, net, o["best"]["name"],
                )

        # Pairs we knew about that no longer qualify: start the re-arm clock.
        for mm in list(self._sig.keys()):
            if mm not in seen:
                self._gone_since.setdefault(mm, now)

    def _should_alert(self, mm: int, roi: float, net: float, now: datetime) -> bool:
        prev = self._sig.get(mm)
        if prev is None:
            return True  # first time (or re-armed) this pair is exitable in profit
        last = self._last_at.get(mm)
        if last is not None and now - last < self.MIN_REALERT_GAP:
            return False
        prev_roi, prev_net = prev
        # Only ping again when the exit got BETTER (the user asked for improve-only).
        return (roi - prev_roi >= self.ROI_DELTA) or (
            net > prev_net and _rel_change(net, prev_net) >= self.VALUE_REL
        )
