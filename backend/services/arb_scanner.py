import asyncio
import logging
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
        # currently-live windows: (matched_market_id, strategy) → db id
        self._live: dict[tuple[int, str], int] = {}
        # last time we alerted each window — used for a cooldown so a flapping
        # market doesn't spam, without permanently muting it.
        self._last_alert: dict[tuple[int, str], datetime] = {}

    # Don't re-alert the same window more often than this (avoids flap spam).
    ALERT_COOLDOWN = timedelta(minutes=30)

    async def load_live_from_db(self) -> None:
        # Only load what's CURRENTLY live, so a restart doesn't re-alert markets
        # that are already open — but markets that aren't live now can alert
        # again when they next cross the threshold.
        async with self._db.execute(
            "SELECT id, matched_market_id, strategy FROM arb_opportunities WHERE is_live = 1"
        ) as cur:
            for r in await cur.fetchall():
                self._live[(r["matched_market_id"], r["strategy"])] = r["id"]

    async def refresh_taker(self, poly_client, pf_client, pf_ws=None) -> None:
        """Two-stage scan. Stage 1: cheap best-ask screen over the price cache.
        Stage 2: for the few candidates, walk full order books to the Max
        profitable size. PF books come live from the WebSocket (with a REST
        fallback); Poly books are fetched on demand. Only genuinely
        taker-profitable arbs go live."""
        pf_fallback = self._settings.PF_FALLBACK_FEE_BPS / 10000.0

        async def _pf_book(pf_market_id: str) -> dict:
            """{'yes_asks':[...], 'yes_bids':[...], 'ts': ms} from the WS if
            available, else REST (REST has no ts → treated as freshly fetched)."""
            if pf_ws is not None:
                b = pf_ws.get_book(pf_market_id)
                if b is not None:
                    return {"yes_asks": b["asks"], "yes_bids": b["bids"], "ts": b.get("ts")}
            return await pf_client.get_order_book(pf_market_id)

        async with self._db.execute(
            "SELECT id, poly_yes_token_id, poly_no_token_id, pf_market_id "
            "FROM matched_markets WHERE is_active=1"
        ) as cur:
            meta = {r["id"]: r for r in await cur.fetchall()}

        # Stage 1 — screen. Poly fee rate is per-market (its category), carried on
        # the price cache; PF rate from its API with a fallback.
        candidates: list[tuple[int, str, float, float]] = []  # (mid, strat, poly_rate, pf_rate)
        for p in self._cache.get_all_fresh(self._settings.PRICE_STALENESS_SECONDS):
            if p.matched_market_id not in meta:
                continue
            poly_rate = p.poly_fee_rate
            pf_rate = p.pf_taker_fee_rate or pf_fallback
            for strat in screen(p.poly_yes, p.poly_no, p.pf_yes, p.pf_no, poly_rate, pf_rate):
                candidates.append((p.matched_market_id, strat, poly_rate, pf_rate))

        # Stage 2 — walk full order books for candidates only
        sem = asyncio.Semaphore(20)

        book_max_age_ms = self._settings.BOOK_MAX_AGE_SECONDS * 1000

        async def evaluate(mid: int, strat: str, poly_rate: float, pf_rate: float):
            m = meta[mid]
            async with sem:
                ob = await _pf_book(m["pf_market_id"])
                # Stale-book guard: a PF book that hasn't changed in a long time
                # is a dead/illiquid cross (a resting order nobody takes), not a
                # tradeable arb — drop it so it doesn't stay live or alert.
                ts = ob.get("ts")
                if ts is not None:
                    age_ms = datetime.now(timezone.utc).timestamp() * 1000 - ts
                    if age_ms > book_max_age_ms:
                        return None
                if strat == YES_POLY_NO_PF:
                    poly_l = await poly_client.get_order_book(m["poly_yes_token_id"])
                    pf_l = PredictFunClient.no_asks_from_bids(ob["yes_bids"])
                    poly_side, pf_side = "YES", "NO"
                else:
                    poly_l = await poly_client.get_order_book(m["poly_no_token_id"])
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
            if key in self._live:
                await self._update_opportunity(self._live[key], opp)
            else:
                db_id = await self._insert_opportunity(opp)
                self._live[key] = db_id
                # Alert when a window first appears, gated by the user's
                # thresholds and a per-window cooldown (so flapping ≠ spam, but
                # a genuine fresh crossing later still notifies).
                meets = (
                    opp.net_pct_top >= s["min_arb_pct"]
                    and opp.max_profit_usd >= s["min_profit_usd"]
                    and opp.max_wager_usd >= s["min_wager_usd"]
                )
                last = self._last_alert.get(key)
                if meets and (last is None or now - last > self.ALERT_COOLDOWN):
                    self._last_alert[key] = now
                    await self._queue.put({"db_id": db_id, "opp": opp})
                    logger.info(
                        "NEW TAKER ARB (alerted): mid=%d %s top=%.2f%% max$%.2f wager$%.0f",
                        opp.matched_market_id, opp.strategy,
                        opp.net_pct_top, opp.max_profit_usd, opp.max_wager_usd,
                    )

        stale = [k for k in self._live if k not in live_keys]
        for key in stale:
            db_id = self._live.pop(key, None)
            if db_id:
                await self._db.execute(
                    "UPDATE arb_opportunities SET is_live=0, closed_at=? WHERE id=?",
                    (utcnow(), db_id),
                )
        await self._db.commit()

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
