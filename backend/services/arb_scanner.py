import asyncio
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiosqlite

from clients.predictfun import PredictFunClient
from config import Settings
from database import utcnow
from services.arb_taker import (
    NO_POLY_YES_PF,
    YES_POLY_NO_PF,
    TakerResult,
    compute_max,
    screen,
)
from services.price_cache import PriceCache

logger = logging.getLogger(__name__)


def _rel_change(new: float, old: float) -> float:
    """Fractional change of `new` vs `old`, with a $1 floor on the denominator so
    tiny dollar values don't look like huge swings."""
    return abs(new - old) / max(abs(old), 1.0)


@dataclass
class ArbOpportunity:
    matched_market_id: int
    strategy: str           # 'YES_POLY_NO_PF' | 'NO_POLY_YES_PF'
    poly_side: str          # 'YES' | 'NO'
    pf_side: str            # 'YES' | 'NO'
    poly_price: float       # avg taker fill price, Poly leg
    pf_price: float         # avg taker fill price, PF leg
    combined_cost: float    # poly_avg + pf_avg
    gross_profit_pct: float # ROI of the best (top) matched share
    poly_fee_usd: float
    pf_fee_usd: float
    total_fee_usd: float
    net_profit_pct: float   # ROI at the Max profitable size
    net_profit_usd: float   # total profit at the Max profitable size
    notional_usd: float     # = max_wager_usd (cost basis at Max)
    max_wager_usd: float
    max_profit_usd: float
    net_pct_top: float
    shares: float
    poly_ceiling: float
    pf_ceiling: float
    detected_at: datetime


def _taker_to_opp(
    mid: int, strategy: str, poly_side: str, pf_side: str, r: TakerResult
) -> ArbOpportunity:
    return ArbOpportunity(
        matched_market_id=mid,
        strategy=strategy,
        poly_side=poly_side,
        pf_side=pf_side,
        poly_price=r.poly_avg,
        pf_price=r.pf_avg,
        combined_cost=r.poly_avg + r.pf_avg,
        gross_profit_pct=r.net_pct_top,
        poly_fee_usd=r.poly_fee,
        pf_fee_usd=r.pf_fee,
        total_fee_usd=r.fees,
        net_profit_pct=r.net_pct,
        net_profit_usd=r.profit,
        notional_usd=r.wager,
        max_wager_usd=r.wager,
        max_profit_usd=r.profit,
        net_pct_top=r.net_pct_top,
        shares=r.shares,
        poly_ceiling=r.poly_ceiling,
        pf_ceiling=r.pf_ceiling,
        detected_at=datetime.now(timezone.utc),
    )


class ArbScanner:
    def __init__(
        self,
        db: aiosqlite.Connection,
        price_cache: PriceCache,
        settings: Settings,
        alert_queue: asyncio.Queue,
    ):
        self._db = db
        self._cache = price_cache
        self._settings = settings
        self._queue = alert_queue
        # Short-TTL order-book cache so we don't re-fetch the same market's books
        # every 3s — heavy book polling gets rate-limited (empty books). Keyed by
        # ("poly"|"pf", id) → (monotonic_ts, book).
        self._book_cache: dict[tuple[str, str], tuple[float, object]] = {}
        # currently-live windows: (matched_market_id, strategy) → db id
        self._live: dict[tuple[int, str], int] = {}
        # Content-based de-dup so the SAME arb doesn't re-alert on every scan or
        # when it flickers out of a scan and back. Per window we remember the
        # economics we last alerted (edge %, max profit $, max wager $) and when,
        # plus when it went stale (to re-arm a genuinely fresh recurrence).
        self._alert_sig: dict[tuple[int, str], tuple[float, float, float]] = {}
        self._last_alert_at: dict[tuple[int, str], datetime] = {}
        self._gone_since: dict[tuple[int, str], datetime] = {}

    # Re-alert an already-known arb ONLY when its economics move materially — not
    # on a fixed timer, and not when it merely flickers out of a scan and back.
    ALERT_PCT_DELTA = 0.5                     # edge change to re-alert, percentage points
    ALERT_PROFIT_REL = 0.30                   # max-profit change to re-alert, fraction
    ALERT_WAGER_REL = 0.30                    # tradable-depth change to re-alert, fraction
    MIN_REALERT_GAP = timedelta(minutes=15)   # hard floor between alerts for one window
    ALERT_REARM = timedelta(hours=2)          # gone this long → next sighting counts as fresh

    async def load_live_from_db(self) -> None:
        # Only load what's CURRENTLY live, so a restart doesn't re-alert markets
        # that are already open — but markets that aren't live now can alert
        # again when they next cross the threshold. Seed the alert signature too,
        # so a restart never re-alerts a window that was already live (and already
        # notified) at its current economics.
        now = datetime.now(timezone.utc)
        s = await self._get_settings()
        async with self._db.execute(
            "SELECT id, matched_market_id, strategy, net_pct_top, max_profit_usd, "
            "max_wager_usd FROM arb_opportunities WHERE is_live = 1"
        ) as cur:
            for r in await cur.fetchall():
                key = (r["matched_market_id"], r["strategy"])
                self._live[key] = r["id"]
                # Only seed the alert signature for windows that already MEET the
                # thresholds (i.e. were presumably alerted before the restart), so
                # a restart doesn't re-announce them. A sub-threshold window is
                # left unseeded so it still alerts the moment it first crosses.
                if (
                    r["net_pct_top"] >= s["min_arb_pct"]
                    and r["max_profit_usd"] >= s["min_profit_usd"]
                    and r["max_wager_usd"] >= s["min_wager_usd"]
                ):
                    self._alert_sig[key] = (
                        r["net_pct_top"], r["max_profit_usd"], r["max_wager_usd"]
                    )
                    self._last_alert_at[key] = now

    async def refresh_taker(self, poly_client, pf_client, pf_ws=None) -> None:
        """Two-stage scan. Stage 1: cheap best-ask screen over the price cache.
        Stage 2: for the few candidates, walk full order books to the Max
        profitable size. PF books come live from the WebSocket (with a REST
        fallback); Poly books are fetched on demand. Only genuinely
        taker-profitable arbs go live."""
        pf_fallback = self._settings.PF_FALLBACK_FEE_BPS / 10000.0
        book_ttl = self._settings.BOOK_CACHE_TTL_SECONDS
        now_mono = time.monotonic()
        # Drop expired book-cache entries so it stays bounded.
        self._book_cache = {k: v for k, v in self._book_cache.items() if now_mono - v[0] < book_ttl}

        async def _pf_book(pf_market_id: str) -> dict:
            """Fresh-ish PF order book via REST, cached for BOOK_CACHE_TTL_SECONDS.
            The WS only pushes on change, so its book freezes for quiet markets;
            REST is accurate, and the cache keeps the request volume low enough to
            avoid rate-limit (empty books)."""
            key = ("pf", pf_market_id)
            hit = self._book_cache.get(key)
            if hit is not None and now_mono - hit[0] < book_ttl:
                return hit[1]
            book = await pf_client.get_order_book(pf_market_id)
            self._book_cache[key] = (now_mono, book)
            return book

        async with self._db.execute(
            "SELECT id, poly_yes_token_id, poly_no_token_id, pf_market_id "
            "FROM matched_markets WHERE is_active=1"
        ) as cur:
            meta = {r["id"]: r for r in await cur.fetchall()}

        # Stage 1 — screen on cached best-asks, then keep only the strongest
        # realistic crossings to walk in Stage 2. Stage 2 fetches fresh REST
        # books (PF rate-limits heavy polling), so it must be bounded.
        scored: list[tuple[float, int, str, float, float]] = []  # (combined, mid, strat, poly_rate, pf_rate)
        fresh = self._cache.get_all_fresh(self._settings.PRICE_STALENESS_SECONDS)
        for p in fresh:
            if p.matched_market_id not in meta:
                continue
            poly_rate = p.poly_fee_rate
            pf_rate = p.pf_taker_fee_rate or pf_fallback
            for strat in screen(p.poly_yes, p.poly_no, p.pf_yes, p.pf_no, poly_rate, pf_rate):
                if strat == YES_POLY_NO_PF:
                    combined = (p.poly_yes or 1.0) + (p.pf_no or 1.0)
                else:
                    combined = (p.poly_no or 1.0) + (p.pf_yes or 1.0)
                # A combined cost < 0.85 (>15% gross) is almost always a stale or
                # empty-book artifact, not a real arb — skip it so the limited
                # Stage-2 budget goes to plausible crossings.
                if combined < 0.85:
                    continue
                scored.append((combined, p.matched_market_id, strat, poly_rate, pf_rate))

        # Build the eval set within the per-scan budget: ALWAYS re-walk
        # currently-live windows (so they stay accurate and don't flicker), then
        # fill the rest with a RANDOM sample of the other crossings. Sorting by
        # edge only ever picks the biggest-looking crossings, which are
        # stale-price artifacts that fail the walk; random sampling reliably
        # surfaces the genuine (smaller-edge) arbs, and over successive scans
        # covers everything.
        all_cands = [(mid, strat, pr, fr) for _c, mid, strat, pr, fr in scored]
        live_keys = set(self._live.keys())
        prioritized = [c for c in all_cands if (c[0], c[1]) in live_keys]
        others = [c for c in all_cands if (c[0], c[1]) not in live_keys]
        random.shuffle(others)
        candidates: list[tuple[int, str, float, float]] = (prioritized + others)[
            : self._settings.MAX_TAKER_EVAL
        ]

        # Batch-fetch every candidate's Polymarket book in ONE request (POST
        # /books). Per-token GET /book gets rate-limited to empty books at scale;
        # batching keeps Polymarket happy. PF books stay per-candidate (cached).
        poly_token_for = {
            (mid, strat): (meta[mid]["poly_yes_token_id"] if strat == YES_POLY_NO_PF
                           else meta[mid]["poly_no_token_id"])
            for mid, strat, _pr, _fr in candidates
        }
        poly_books = await poly_client.get_books_batch(list(poly_token_for.values()))

        # Stage 2 — walk full order books for candidates only
        sem = asyncio.Semaphore(20)

        async def evaluate(mid: int, strat: str, poly_rate: float, pf_rate: float):
            m = meta[mid]
            poly_l = poly_books.get(poly_token_for[(mid, strat)]) or []
            async with sem:
                ob = await _pf_book(m["pf_market_id"])
            if strat == YES_POLY_NO_PF:
                pf_l = PredictFunClient.no_asks_from_bids(ob["yes_bids"])
                poly_side, pf_side = "YES", "NO"
            else:
                pf_l = ob["yes_asks"]
                poly_side, pf_side = "NO", "YES"
            res = compute_max(poly_l, pf_l, poly_rate, pf_rate)
            if res is None or res.profit <= 0:
                return None
            return _taker_to_opp(mid, strat, poly_side, pf_side, res)

        results = await asyncio.gather(
            *(evaluate(*c) for c in candidates), return_exceptions=True
        )
        live = [r for r in results if isinstance(r, ArbOpportunity)]
        await self._reconcile(live)

    async def _reconcile(self, live: list[ArbOpportunity]) -> None:
        s = await self._get_settings()
        now = datetime.now(timezone.utc)
        live_keys: set[tuple[int, str]] = set()

        for opp in live:
            key = (opp.matched_market_id, opp.strategy)
            live_keys.add(key)

            # If this window had gone away and stayed away long enough, treat its
            # return as a brand-new crossing (drop its last-alerted signature) so
            # a genuinely fresh recurrence still notifies.
            gone_at = self._gone_since.pop(key, None)
            if gone_at is not None and now - gone_at > self.ALERT_REARM:
                self._alert_sig.pop(key, None)
                self._last_alert_at.pop(key, None)

            if key in self._live:
                db_id = self._live[key]
                await self._update_opportunity(db_id, opp)
            else:
                db_id = await self._insert_opportunity(opp)
                self._live[key] = db_id

            # Alert only when it clears the user's thresholds AND it's materially
            # different from what we last alerted for this window — so the same
            # arb just sitting there (or flickering) doesn't spam.
            meets = (
                opp.net_pct_top >= s["min_arb_pct"]
                and opp.max_profit_usd >= s["min_profit_usd"]
                and opp.max_wager_usd >= s["min_wager_usd"]
            )
            if meets and self._should_alert(key, opp, now):
                self._alert_sig[key] = (
                    opp.net_pct_top, opp.max_profit_usd, opp.max_wager_usd
                )
                self._last_alert_at[key] = now
                await self._queue.put({"db_id": db_id, "opp": opp})
                logger.info(
                    "ARB ALERT mid=%d %s top=%.2f%% max$%.2f wager$%.0f",
                    opp.matched_market_id, opp.strategy,
                    opp.net_pct_top, opp.max_profit_usd, opp.max_wager_usd,
                )

        stale = [k for k in self._live if k not in live_keys]
        for key in stale:
            db_id = self._live.pop(key, None)
            # Start the re-arm clock but KEEP the alert signature, so a quick
            # flicker back doesn't count as a fresh arb.
            self._gone_since.setdefault(key, now)
            if db_id:
                await self._db.execute(
                    "UPDATE arb_opportunities SET is_live=0, closed_at=? WHERE id=?",
                    (utcnow(), db_id),
                )
        await self._db.commit()

    def _should_alert(self, key: tuple[int, str], opp: ArbOpportunity, now: datetime) -> bool:
        """True if this window has never been alerted (or was re-armed after a long
        absence), or its economics have moved past the re-alert thresholds. A hard
        MIN_REALERT_GAP floor damps oscillation around a threshold boundary."""
        prev = self._alert_sig.get(key)
        if prev is None:
            return True
        last_at = self._last_alert_at.get(key)
        if last_at is not None and now - last_at < self.MIN_REALERT_GAP:
            return False
        prev_pct, prev_profit, prev_wager = prev
        return (
            abs(opp.net_pct_top - prev_pct) >= self.ALERT_PCT_DELTA
            or _rel_change(opp.max_profit_usd, prev_profit) >= self.ALERT_PROFIT_REL
            or _rel_change(opp.max_wager_usd, prev_wager) >= self.ALERT_WAGER_REL
        )

    async def _insert_opportunity(self, opp: ArbOpportunity) -> int:
        async with self._db.execute(
            """INSERT INTO arb_opportunities
               (matched_market_id, strategy, poly_side, pf_side,
                poly_price, pf_price, combined_cost, gross_profit_pct,
                poly_fee_usd, pf_fee_usd, total_fee_usd,
                net_profit_pct, net_profit_usd, notional_usd,
                max_wager_usd, max_profit_usd, net_pct_top,
                detected_at, is_live)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (
                opp.matched_market_id, opp.strategy, opp.poly_side, opp.pf_side,
                opp.poly_price, opp.pf_price, opp.combined_cost, opp.gross_profit_pct,
                opp.poly_fee_usd, opp.pf_fee_usd, opp.total_fee_usd,
                opp.net_profit_pct, opp.net_profit_usd, opp.notional_usd,
                opp.max_wager_usd, opp.max_profit_usd, opp.net_pct_top,
                opp.detected_at.isoformat(),
            ),
        ) as cur:
            db_id = cur.lastrowid
        return db_id

    async def _update_opportunity(self, db_id: int, opp: ArbOpportunity) -> None:
        await self._db.execute(
            """UPDATE arb_opportunities SET
                 poly_price=?, pf_price=?, combined_cost=?, gross_profit_pct=?,
                 poly_fee_usd=?, pf_fee_usd=?, total_fee_usd=?,
                 net_profit_pct=?, net_profit_usd=?, notional_usd=?,
                 max_wager_usd=?, max_profit_usd=?, net_pct_top=?, is_live=1
               WHERE id=?""",
            (
                opp.poly_price, opp.pf_price, opp.combined_cost, opp.gross_profit_pct,
                opp.poly_fee_usd, opp.pf_fee_usd, opp.total_fee_usd,
                opp.net_profit_pct, opp.net_profit_usd, opp.notional_usd,
                opp.max_wager_usd, opp.max_profit_usd, opp.net_pct_top, db_id,
            ),
        )

    async def _get_settings(self) -> dict:
        from database import get_all_settings
        raw = await get_all_settings(self._db)
        return {
            "notional_usd": float(raw.get("notional_usd", self._settings.NOTIONAL_USD)),
            "min_arb_pct": float(raw.get("min_arb_pct", self._settings.MIN_ARB_PCT)),
            "min_profit_usd": float(raw.get("min_profit_usd", self._settings.MIN_PROFIT_USD)),
            "min_wager_usd": float(raw.get("min_wager_usd", self._settings.MIN_WAGER_USD)),
        }
