import json
import logging

import aiosqlite

from clients.polymarket import PolymarketClient
from clients.predictfun import PredictFunClient
from config import Settings
from database import get_setting, utcnow
from services.price_cache import PriceCache

logger = logging.getLogger(__name__)


class PortfolioTracker:
    def __init__(
        self,
        db: aiosqlite.Connection,
        poly_client: PolymarketClient,
        pf_client: PredictFunClient,
        settings: Settings,
        price_cache: PriceCache | None = None,
    ):
        self._db = db
        self._poly = poly_client
        self._pf = pf_client
        self._settings = settings
        self._cache = price_cache

    async def _wallets(self) -> list[str]:
        raw = await get_setting(self._db, "wallet_addresses", "[]")
        try:
            wallets = json.loads(raw or "[]")
        except Exception:
            wallets = self._settings.wallet_list
        return [w for w in wallets if w]

    async def sync_all_wallets(self) -> None:
        for wallet in await self._wallets():
            await self.sync_wallet(wallet)

    async def sync_wallet(self, wallet: str) -> None:
        await self._sync_polymarket(wallet)
        await self._sync_predictfun(wallet)

    async def _sync_polymarket(self, wallet: str) -> None:
        positions = await self._poly.get_positions(wallet)
        now = utcnow()
        # Mark all auto Poly positions for this wallet closed; the upserts below
        # reopen the ones still held, so positions that closed drop off.
        await self._db.execute(
            "UPDATE positions SET status='closed' WHERE wallet_address=? AND platform='polymarket' AND source='auto'",
            (wallet,),
        )
        for pos in positions:
            market_id = str(pos.get("conditionId") or pos.get("market_id") or pos.get("marketId", ""))
            title = pos.get("title") or pos.get("question") or pos.get("marketTitle", "")
            outcome = (pos.get("outcome") or pos.get("side") or "").upper()
            size = float(pos.get("size") or 0.0)
            avg_price = _safe_float(pos.get("avgPrice") or pos.get("averagePrice"))
            cur_price = _safe_float(pos.get("curPrice") or pos.get("currentPrice"))
            if not market_id or size == 0:
                continue
            cost = size * avg_price if avg_price else _safe_float(pos.get("initialValue"))
            unrealized = (cur_price - avg_price) * size if (avg_price is not None and cur_price is not None) else None
            await self._upsert(wallet, "polymarket", "auto", market_id, title, outcome,
                               size, avg_price, cur_price, unrealized, cost, now)
        await self._db.commit()

    async def _sync_predictfun(self, wallet: str) -> None:
        # PF positions can't be auto-read for a BNB wallet (API returns nothing);
        # kept for completeness. Manual PF positions (source='manual') are untouched.
        positions = await self._pf.get_positions(wallet)
        now = utcnow()
        for pos in positions:
            market_id = str(pos.get("marketId") or pos.get("market_id") or pos.get("id", ""))
            title = pos.get("marketTitle") or pos.get("title") or pos.get("question", "")
            outcome = (pos.get("outcome") or pos.get("side") or "").upper()
            size = float(pos.get("size") or pos.get("amount") or 0.0)
            avg_price = _safe_float(pos.get("avgPrice") or pos.get("averagePrice"))
            cur_price = _safe_float(pos.get("currentPrice") or pos.get("curPrice"))
            if not market_id or size == 0:
                continue
            cost = size * avg_price if avg_price else None
            unrealized = (cur_price - avg_price) * size if (avg_price is not None and cur_price is not None) else None
            await self._upsert(wallet, "predictfun", "auto", market_id, title, outcome,
                               size, avg_price, cur_price, unrealized, cost, now)
        await self._db.commit()

    async def _upsert(self, wallet, platform, source, market_id, title, side,
                      size, avg_price, cur_price, unrealized, cost, now) -> None:
        await self._db.execute(
            """INSERT INTO positions
               (wallet_address, platform, market_id, market_title, side, size,
                avg_entry_price, current_price, unrealized_pnl, cost_usd, source, status, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'open',?)
               ON CONFLICT(wallet_address, platform, market_id, side) DO UPDATE SET
                 market_title=excluded.market_title, size=excluded.size,
                 avg_entry_price=excluded.avg_entry_price, current_price=excluded.current_price,
                 unrealized_pnl=excluded.unrealized_pnl, cost_usd=excluded.cost_usd,
                 status='open', fetched_at=excluded.fetched_at""",
            (wallet, platform, market_id, title, side, size,
             avg_price, cur_price, unrealized, cost, source, now),
        )

    async def add_manual_pf_position(
        self, market_id: str, title: str, side: str, shares: float, total_cost: float
    ) -> None:
        avg = total_cost / shares if shares else 0.0
        await self._upsert("manual", "predictfun", "manual", market_id, title,
                           side.upper(), shares, avg, None, None, total_cost, utcnow())
        await self._db.commit()

    async def delete_position(self, position_id: int) -> None:
        await self._db.execute("DELETE FROM positions WHERE id=?", (position_id,))
        await self._db.commit()

    async def build_summary(self) -> dict:
        async with self._db.execute(
            "SELECT * FROM positions WHERE status='open' ORDER BY platform, market_title"
        ) as cur:
            positions = [dict(r) for r in await cur.fetchall()]

        # matched-market lookup keyed by each platform's market id
        async with self._db.execute(
            "SELECT id, poly_condition_id, pf_market_id, poly_title FROM matched_markets WHERE is_active=1"
        ) as cur:
            matched = [dict(r) for r in await cur.fetchall()]
        poly_to_mm = {m["poly_condition_id"]: m for m in matched}
        pf_to_mm = {str(m["pf_market_id"]): m for m in matched}

        # group positions by matched_market id (when they belong to one)
        groups: dict[int, dict] = {}
        standalone: list[dict] = []
        for p in positions:
            is_poly = p["platform"] == "polymarket"
            mm = poly_to_mm.get(p["market_id"]) if is_poly else pf_to_mm.get(str(p["market_id"]))
            leg = await self._leg(p, mm)
            if mm:
                g = groups.setdefault(mm["id"], {"mm": mm, "poly": None, "pf": None})
                g["poly" if is_poly else "pf"] = leg
            else:
                standalone.append(leg)

        pairs = []
        for g in groups.values():
            poly_leg, pf_leg = g["poly"], g["pf"]
            if poly_leg and pf_leg:
                cost = (poly_leg["cost"] or 0) + (pf_leg["cost"] or 0)
                payoff = poly_leg["shares"] + pf_leg["shares"]
                pairs.append({
                    "matched_market_id": g["mm"]["id"],
                    "title": g["mm"]["poly_title"],
                    "poly": poly_leg,
                    "pf": pf_leg,
                    "combined_cost": cost,
                    "max_payoff": payoff,
                    "ev": payoff - cost,
                })
            else:
                # only one leg present on a matched market → treat as standalone
                standalone.append(poly_leg or pf_leg)

        all_legs = [l for p in pairs for l in (p["poly"], p["pf"])] + standalone
        deployed = sum((l["cost"] or 0) for l in all_legs)
        max_payoff = sum(l["shares"] for l in all_legs)
        return {
            "stats": {
                "open_ev": max_payoff - deployed,
                "deployed": deployed,
                "max_payoff": max_payoff,
                "active_pairs": len(pairs),
            },
            "pairs": pairs,
            "standalone": standalone,
        }

    async def _leg(self, p: dict, mm: dict | None) -> dict:
        """Build a live-priced position leg."""
        cur_price = p.get("current_price")
        if p["platform"] == "predictfun":
            cur_price = await self._pf_current_price(p["market_id"], p["side"], mm)
        shares = p["size"] or 0.0
        cost = p.get("cost_usd")
        if cost is None and p.get("avg_entry_price"):
            cost = shares * p["avg_entry_price"]
        cur_value = shares * cur_price if cur_price is not None else None
        pnl = (cur_value - cost) if (cur_value is not None and cost is not None) else None
        return {
            "id": p["id"],
            "platform": p["platform"],
            "market_id": p["market_id"],
            "market_title": p["market_title"],
            "side": p["side"],
            "shares": shares,
            "avg_price": p.get("avg_entry_price"),
            "cost": cost,
            "current_price": cur_price,
            "current_value": cur_value,
            "pnl": pnl,
            "source": p.get("source", "auto"),
        }

    async def _pf_current_price(self, market_id: str, side: str, mm: dict | None) -> float | None:
        """Current price of a PF outcome: from the live cache if the market is
        matched/cached, else fetched on demand."""
        is_yes = side.upper() in ("YES", "UP", "TRUE")
        if mm and self._cache:
            mp = self._cache.get(mm["id"])
            if mp:
                price = mp.pf_yes if is_yes else mp.pf_no
                if price is not None:
                    return price
        data = await self._pf.get_market_price(str(market_id))
        if data:
            yes_p, no_p, _ = self._pf.extract_prices(data)
            return yes_p if is_yes else no_p
        return None

    async def get_summary(self, wallet: str) -> dict:
        async with self._db.execute(
            """SELECT platform, COUNT(*) as count, SUM(unrealized_pnl) as total_pnl,
                      SUM(cost_usd) as total_invested
               FROM positions WHERE wallet_address = ? AND status = 'open'
               GROUP BY platform""",
            (wallet,),
        ) as cur:
            rows = await cur.fetchall()
        return {r["platform"]: dict(r) for r in rows}


def _safe_float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
