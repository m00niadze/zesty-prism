import asyncio
import logging

import aiohttp

from clients.polymarket import PolymarketClient
from clients.predictfun import PredictFunClient
from config import Settings
from database import utcnow
from services.arb_scanner import ArbScanner
from services.market_matcher import MarketMatcher
from services.portfolio_tracker import PortfolioTracker
from services.price_cache import PriceCache

logger = logging.getLogger(__name__)


class AppState:
    def __init__(self):
        self.db = None
        self.http_session: aiohttp.ClientSession | None = None
        self.poly_client: PolymarketClient | None = None
        self.pf_client: PredictFunClient | None = None
        self.pf_ws = None  # PFWebSocketClient — real-time PF order books
        self.price_cache: PriceCache | None = None
        self.arb_scanner: ArbScanner | None = None
        self.market_matcher: MarketMatcher | None = None
        self.portfolio_tracker: PortfolioTracker | None = None
        self.alert_queue: asyncio.Queue | None = None
        self.settings: Settings | None = None
        self._tasks: list[asyncio.Task] = []

    def add_task(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        return task

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()


async def polymarket_poll_loop(state: AppState) -> None:
    """Poll Polymarket prices every POLL_INTERVAL_POLY_SECONDS for all active
    matched markets. Uses the CLOB batch /prices endpoint so a handful of
    requests cover hundreds of markets each cycle."""
    settings = state.settings
    while True:
        try:
            async with state.db.execute(
                "SELECT id, poly_yes_token_id, poly_no_token_id FROM matched_markets WHERE is_active=1"
            ) as cur:
                markets = await cur.fetchall()

            if markets:
                token_ids: list[str] = []
                for m in markets:
                    token_ids.append(m["poly_yes_token_id"])
                    token_ids.append(m["poly_no_token_id"])

                prices = await state.poly_client.get_prices_batch(token_ids)

                for m in markets:
                    yes_p = prices.get(m["poly_yes_token_id"])
                    no_p = prices.get(m["poly_no_token_id"])
                    if yes_p is None and no_p is None:
                        continue
                    changed = state.price_cache.update_poly(m["id"], yes_p, no_p)
                    if changed:
                        await state.db.execute(
                            """UPDATE market_prices SET poly_yes_price=?, poly_no_price=?, poly_fetched_at=?
                               WHERE matched_market_id=?""",
                            (yes_p, no_p, utcnow(), m["id"]),
                        )
                await state.db.commit()

        except Exception as e:
            logger.error("Polymarket poll loop error: %s", e)

        await asyncio.sleep(settings.POLL_INTERVAL_POLY_SECONDS)


_PF_POLL_SEMAPHORE: asyncio.Semaphore | None = None
# The WebSocket is the primary source of live PF prices; this REST sweep is a
# slow fallback. Keep it light so it doesn't eat the Predict.fun rate budget the
# Stage-2 taker book-walks need (heavy PF polling triggers 429s → empty books).
_PF_POLL_CONCURRENCY = 20
_PF_POLL_INTERVAL = 30


async def predictfun_rest_poll_loop(state: AppState) -> None:
    """Fast Predict.fun price refresh: sweep every active market concurrently so
    the whole book of best-asks refreshes every few seconds (needed to catch
    fast-moving live-match arbs). Order books for actual arb confirmation are
    fetched live in the taker stage; this keeps the Stage-1 screen fresh.
    Cache is updated inside the concurrent sweep; DB writes are batched after."""
    global _PF_POLL_SEMAPHORE
    _PF_POLL_SEMAPHORE = asyncio.Semaphore(_PF_POLL_CONCURRENCY)
    while True:
        try:
            async with state.db.execute(
                "SELECT id, pf_market_id FROM matched_markets WHERE is_active=1"
            ) as cur:
                markets = await cur.fetchall()

            if markets:
                results = await asyncio.gather(
                    *(_fetch_pf_market(state, m["id"], m["pf_market_id"]) for m in markets),
                    return_exceptions=True,
                )
                changed = [r for r in results if isinstance(r, tuple)]
                for mid, yes_p, no_p, fee_rate in changed:
                    await state.db.execute(
                        """UPDATE market_prices SET pf_yes_price=?, pf_no_price=?,
                           pf_taker_fee_rate=?, pf_fetched_at=? WHERE matched_market_id=?""",
                        (yes_p, no_p, fee_rate, utcnow(), mid),
                    )
                if changed:
                    await state.db.commit()
                logger.debug("PF sweep: %d markets, %d changed", len(markets), len(changed))
        except Exception as e:
            logger.error("PF REST poll error: %s", e)
        await asyncio.sleep(_PF_POLL_INTERVAL)


async def predictfun_ws_loop(state: AppState) -> None:
    """Maintain the Predict.fun WebSocket: live order books for every matched
    market push straight into the price cache (sub-second freshness, no REST
    rate limits). The REST sweep stays as a slow fallback."""
    async def on_update(market_id: str) -> None:
        book = state.pf_ws.get_book(market_id)
        if not book:
            return
        asks, bids = book["asks"], book["bids"]
        yes = asks[0][0] if asks else None        # best YES ask
        no = (1.0 - bids[0][0]) if bids else None  # best NO ask = 1 - best YES bid
        state.price_cache.update_pf_prices(market_id, yes, no)

    await state.pf_ws.run(on_update)


async def pf_ws_stats_loop(state: AppState) -> None:
    """Log WebSocket health so we can see it's live and subscribed."""
    while True:
        await asyncio.sleep(60)
        if state.pf_ws is not None:
            s = state.pf_ws.stats()
            logger.info("PF WS: connected=%s subscribed=%d live_books=%d",
                        s["connected"], s["subscribed"], s["books"])


async def _fetch_pf_market(state: AppState, mid: int, pf_market_id: str):
    """Refresh one PF market's best-ask into the in-memory cache. Returns
    (mid, yes, no, fee) when the price changed (for a batched DB write), else None."""
    async with _PF_POLL_SEMAPHORE:
        data = await state.pf_client.get_market_price(pf_market_id)
    if not data:
        return None
    yes_p, no_p, fee_rate = state.pf_client.extract_prices(data)
    if yes_p is not None and no_p is not None:
        _, changed = state.price_cache.update_pf(pf_market_id, yes_p, no_p, fee_rate)
        if changed:
            return (mid, yes_p, no_p, fee_rate)
    return None


def _fnum(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _pf_book_stats(state: "AppState", pf_market_id: str):
    """(liquidity, spread) from the live PF WS book. liquidity = Σ price×size
    over both sides; spread = best ask − best bid."""
    if state.pf_ws is None:
        return None, None
    book = state.pf_ws.get_book(pf_market_id)
    if not book:
        return None, None
    asks = book.get("asks") or []
    bids = book.get("bids") or []
    liq = sum(p * s for p, s in asks) + sum(p * s for p, s in bids)
    spread = (asks[0][0] - bids[0][0]) if (asks and bids) else None
    return (liq or None), spread


async def market_sync_loop(state: AppState) -> None:
    """Re-match markets every MARKET_SYNC_INTERVAL_SECONDS."""
    settings = state.settings
    while True:
        try:
            logger.info("Starting market sync...")
            pf_markets = await state.pf_client.get_markets()
            # Match by conditionId: fetch exactly the Poly markets PF references
            # (offset pagination caps at ~10,100; many matchable markets are
            # beyond it, so we fetch them by id instead).
            cids = [c for m in pf_markets for c in (m.get("polymarketConditionIds") or [])]
            poly_markets = await state.poly_client.get_markets_by_condition_ids(cids)
            active = await state.market_matcher.sync_and_match(poly_markets, pf_markets)

            # Point the WebSocket at the current set of matched markets so their
            # order books stream live.
            if state.pf_ws is not None:
                await state.pf_ws.set_markets([m["pf_market_id"] for m in active])

            # Catalog all PF markets for the manual-add position picker. Use the
            # full `question` (e.g. "Extended FDV above $150M one day after
            # launch?"), not the short `title` ("$150M"), so markets are
            # identifiable and searchable.
            now = utcnow()
            for m in pf_markets:
                await state.db.execute(
                    """INSERT INTO pf_markets (id, title, category_slug, updated_at)
                       VALUES (?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                         category_slug=excluded.category_slug, updated_at=excluded.updated_at""",
                    (str(m.get("id", "")), m.get("question") or m.get("title", ""),
                     m.get("categorySlug", ""), now),
                )
            await state.db.commit()

            # Build a quick lookup of pf_market_id → market data (prices already fetched)
            pf_by_id = {str(m["id"]): m for m in pf_markets}
            poly_by_cond = {m.get("conditionId"): m for m in poly_markets if m.get("conditionId")}

            for m in active:
                state.price_cache.register(m["id"], m["pf_market_id"], m["poly_fee_rate"])
                # Market stats (volume / liquidity / spread) for the Details rankings.
                pm = poly_by_cond.get(m["poly_condition_id"])
                pf_liq, pf_spread = _pf_book_stats(state, m["pf_market_id"])
                await state.db.execute(
                    """INSERT INTO market_stats
                       (matched_market_id, poly_volume, poly_liquidity, poly_spread,
                        pf_liquidity, pf_spread, updated_at)
                       VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(matched_market_id) DO UPDATE SET
                         poly_volume=excluded.poly_volume, poly_liquidity=excluded.poly_liquidity,
                         poly_spread=excluded.poly_spread, pf_liquidity=excluded.pf_liquidity,
                         pf_spread=excluded.pf_spread, updated_at=excluded.updated_at""",
                    (
                        m["id"],
                        _fnum(pm.get("volume")) if pm else None,
                        (_fnum(pm.get("liquidityNum")) or _fnum(pm.get("liquidity"))) if pm else None,
                        _fnum(pm.get("spread")) if pm else None,
                        pf_liq, pf_spread, now,
                    ),
                )
                # Seed prices from market sync data into both cache and DB
                raw = pf_by_id.get(str(m["pf_market_id"]))
                if raw:
                    yes_p, no_p, fee_rate = state.pf_client.extract_prices(raw)
                    if yes_p is not None and no_p is not None:
                        state.price_cache.update_pf(m["pf_market_id"], yes_p, no_p, fee_rate)
                        await state.db.execute(
                            """INSERT INTO market_prices
                               (matched_market_id, pf_yes_price, pf_no_price, pf_taker_fee_rate, pf_fetched_at)
                               VALUES (?, ?, ?, ?, ?)
                               ON CONFLICT(matched_market_id) DO UPDATE SET
                               pf_yes_price=excluded.pf_yes_price,
                               pf_no_price=excluded.pf_no_price,
                               pf_taker_fee_rate=excluded.pf_taker_fee_rate,
                               pf_fetched_at=excluded.pf_fetched_at""",
                            (m["id"], yes_p, no_p, fee_rate, utcnow()),
                        )
                else:
                    await state.db.execute(
                        "INSERT OR IGNORE INTO market_prices (matched_market_id) VALUES (?)",
                        (m["id"],),
                    )
            await state.db.commit()

            logger.info("Market sync complete: %d active matched markets", len(active))
        except Exception as e:
            logger.error("Market sync loop error: %s", e)

        await asyncio.sleep(settings.MARKET_SYNC_INTERVAL_SECONDS)


async def portfolio_sync_loop(state: AppState) -> None:
    """Sync wallet positions every PORTFOLIO_SYNC_INTERVAL_SECONDS."""
    settings = state.settings
    while True:
        try:
            await state.portfolio_tracker.sync_all_wallets()
        except Exception as e:
            logger.error("Portfolio sync error: %s", e)
        await asyncio.sleep(settings.PORTFOLIO_SYNC_INTERVAL_SECONDS)


async def taker_refresh_loop(state: AppState) -> None:
    """Stage 2 of detection: every TAKER_REFRESH_SECONDS, re-screen the price
    cache and walk real order books for candidates, so the live list only holds
    genuinely taker-profitable arbs (and stale ones are expired)."""
    settings = state.settings
    while True:
        await asyncio.sleep(settings.TAKER_REFRESH_SECONDS)
        try:
            await state.arb_scanner.refresh_taker(state.poly_client, state.pf_client, state.pf_ws)
        except Exception as e:
            logger.error("Taker refresh error: %s", e)


async def exit_scan_loop(state: AppState) -> None:
    """Every EXIT_SCAN_SECONDS, re-price open hedged pairs and emit a take-profit
    EXIT ALERT when one can be closed for a profit above the user's threshold."""
    settings = state.settings
    while True:
        await asyncio.sleep(settings.EXIT_SCAN_SECONDS)
        try:
            await state.exit_alerter.scan()
        except Exception as e:
            logger.error("Exit scan error: %s", e)


async def alert_push_loop(state: AppState) -> None:
    """Forward alert queue items to the bot container via HTTP."""
    import aiohttp as _aiohttp
    settings = state.settings
    while True:
        item = await state.alert_queue.get()
        try:
            async with state.http_session.post(
                settings.BOT_INTERNAL_URL,
                json=_serialize_alert(item),
                headers={"X-Internal-Secret": settings.INTERNAL_ALERT_SECRET},
                timeout=_aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status not in (200, 204):
                    logger.warning("Bot alert push returned %d", r.status)
        except Exception as e:
            logger.debug("Bot alert push failed (bot may not be ready): %s", e)
        finally:
            state.alert_queue.task_done()


def _serialize_alert(item: dict) -> dict:
    if item.get("kind") == "exit":
        return {"kind": "exit", **item["exit"]}
    opp = item["opp"]
    return {
        "kind": "entry",
        "db_id": item["db_id"],
        "matched_market_id": opp.matched_market_id,
        "strategy": opp.strategy,
        "poly_side": opp.poly_side,
        "pf_side": opp.pf_side,
        "poly_price": opp.poly_price,
        "pf_price": opp.pf_price,
        "combined_cost": opp.combined_cost,
        "gross_profit_pct": opp.gross_profit_pct,
        "poly_fee_usd": opp.poly_fee_usd,
        "pf_fee_usd": opp.pf_fee_usd,
        "total_fee_usd": opp.total_fee_usd,
        "net_profit_pct": opp.net_profit_pct,
        "net_profit_usd": opp.net_profit_usd,
        "notional_usd": opp.notional_usd,
        "net_pct_top": opp.net_pct_top,
        "max_profit_usd": opp.max_profit_usd,
        "max_wager_usd": opp.max_wager_usd,
        "detected_at": opp.detected_at.isoformat(),
    }


async def start_all(state: AppState) -> None:
    await state.arb_scanner.load_live_from_db()
    state.add_task(polymarket_poll_loop(state))
    state.add_task(predictfun_rest_poll_loop(state))
    state.add_task(predictfun_ws_loop(state))
    state.add_task(pf_ws_stats_loop(state))
    state.add_task(market_sync_loop(state))
    state.add_task(portfolio_sync_loop(state))
    state.add_task(taker_refresh_loop(state))
    state.add_task(exit_scan_loop(state))
    state.add_task(alert_push_loop(state))
    logger.info("All background tasks started")
