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
        async with self._db.execute(
            "SELECT poly_condition_id, poly_fee_rate FROM matched_markets"
        ) as cur:
            fee_rates = {r["poly_condition_id"]: (r["poly_fee_rate"] or 0.0) for r in await cur.fetchall()}

        def _cost(size, avg, mid):
            # Cost basis WITH the Polymarket taker fee (rate*shares*p*(1-p)).
            if not avg:
                return None
            return size * avg + fee_rates.get(mid, 0.0) * size * avg * (1.0 - avg)

        # Poly markets with an OPEN Predict.fun partner = arb legs. These are tracked
        # through the sales log so partial sells are itemized and the cost basis
        # stays put when shares leave the wallet; everything else keeps the simple
        # wallet-mirror behaviour (size follows the wallet, sold ⇒ drops off).
        # A Poly leg counts as an arb leg while its PF partner is still being
        # tracked — open OR already sold (a half-/fully-closed arb). Using 'open'
        # only would drop a Poly leg to 'closed' (and out of every view) if you
        # sold the PF leg FIRST and the Poly leg second.
        async with self._db.execute(
            """SELECT DISTINCT mm.poly_condition_id AS mid FROM matched_markets mm
               JOIN positions pf ON pf.market_id=mm.pf_market_id
                    AND pf.platform='predictfun' AND pf.status IN ('open','sold')"""
        ) as cur:
            arb_mids = {r["mid"] for r in await cur.fetchall()}

        wallet_poly: dict[str, dict] = {}
        for pos in positions:
            market_id = str(pos.get("conditionId") or pos.get("market_id") or pos.get("marketId", ""))
            size = float(pos.get("size") or 0.0)
            if not market_id or size == 0:
                continue
            wallet_poly[market_id] = {
                "title": pos.get("title") or pos.get("question") or pos.get("marketTitle", ""),
                "outcome": (pos.get("outcome") or pos.get("side") or "").upper(),
                "size": size,
                "avg": _safe_float(pos.get("avgPrice") or pos.get("averagePrice")),
                "cur": _safe_float(pos.get("curPrice") or pos.get("currentPrice")),
                "initial": _safe_float(pos.get("initialValue")),
            }

        def _unreal(w):
            return (w["cur"] - w["avg"]) * w["size"] if (w["avg"] is not None and w["cur"] is not None) else None

        # ── Non-arb auto positions: legacy wallet-mirror (unchanged behaviour) ──
        if arb_mids:
            ph = ",".join("?" * len(arb_mids))
            await self._db.execute(
                f"UPDATE positions SET status='closed' WHERE wallet_address=? AND platform='polymarket' "
                f"AND source='auto' AND status='open' AND market_id NOT IN ({ph})",
                (wallet, *arb_mids),
            )
        else:
            await self._db.execute(
                "UPDATE positions SET status='closed' WHERE wallet_address=? AND platform='polymarket' "
                "AND source='auto' AND status='open'",
                (wallet,),
            )
        for mid, w in wallet_poly.items():
            if mid in arb_mids:
                continue
            await self._upsert(wallet, "polymarket", "auto", mid, w["title"], w["outcome"],
                               w["size"], w["avg"], w["cur"], _unreal(w), _cost(w["size"], w["avg"], mid), now)

        # ── Arb legs: reconcile wallet vs DB through the sales log ──
        db_arb: dict[str, dict] = {}
        if arb_mids:
            ph = ",".join("?" * len(arb_mids))
            async with self._db.execute(
                f"SELECT id, market_id, side, size, sold_shares, avg_entry_price, cost_usd "
                f"FROM positions WHERE wallet_address=? AND platform='polymarket' AND source='auto' "
                f"AND status='open' AND market_id IN ({ph})",
                (wallet, *arb_mids),
            ) as cur:
                db_arb = {r["market_id"]: dict(r) for r in await cur.fetchall()}

        for mid in arb_mids:
            w = wallet_poly.get(mid)
            db = db_arb.get(mid)
            if db is None:
                if w is not None:  # a newly-bought arb leg
                    await self._upsert(wallet, "polymarket", "auto", mid, w["title"], w["outcome"],
                                       w["size"], w["avg"], w["cur"], _unreal(w),
                                       _cost(w["size"], w["avg"], mid), now)
                continue
            db_open = (db["size"] or 0.0) - (db["sold_shares"] or 0.0)
            W = w["size"] if w else 0.0
            if W < db_open - 1e-6:
                # shares left the wallet → log a PENDING sale of the drop (cash TBD)
                await self._add_sale_row(db["id"], db_open - W, None, "auto", now)
                await self._recompute_sold(db["id"])
                if w and w["cur"] is not None:
                    await self._db.execute(
                        "UPDATE positions SET current_price=?, fetched_at=? WHERE id=?",
                        (w["cur"], now, db["id"]))
            elif W > db_open + 1e-6 and w:
                # bought more → grow the original size & cost basis
                new_size = (db["size"] or 0.0) + (W - db_open)
                avg = w["avg"] or db["avg_entry_price"] or 0.0
                await self._db.execute(
                    "UPDATE positions SET size=?, avg_entry_price=?, current_price=?, cost_usd=?, "
                    "status='open', fetched_at=? WHERE id=?",
                    (new_size, avg, w["cur"], _cost(new_size, avg, mid), now, db["id"]))
            elif w:
                await self._db.execute(
                    "UPDATE positions SET current_price=?, fetched_at=? WHERE id=?",
                    (w["cur"], now, db["id"]))

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

    # ── Sales log ─────────────────────────────────────────────────────────────
    # Each partial sell is a row in position_sales; a position's sold_shares /
    # sold_proceeds are the SUM of its rows (a NULL proceeds = a 'pending' sale,
    # counted in sold_shares so open_shares/hedge stay right, $0 in proceeds until
    # the user enters the cash).

    async def _add_sale_row(self, position_id: int, shares: float,
                            proceeds: float | None, source: str, now: str | None = None) -> None:
        await self._db.execute(
            "INSERT INTO position_sales (position_id, shares, proceeds, source, sold_at) "
            "VALUES (?,?,?,?,?)",
            (position_id, shares, proceeds, source, now or utcnow()),
        )

    async def _recompute_sold(self, position_id: int) -> None:
        """Refresh a position's cached sold_shares/sold_proceeds/status from its
        sales log."""
        async with self._db.execute(
            "SELECT COALESCE(SUM(shares),0) AS s, SUM(proceeds) AS p, COUNT(*) AS n "
            "FROM position_sales WHERE position_id=?",
            (position_id,),
        ) as cur:
            r = await cur.fetchone()
        sold = r["s"] or 0.0
        proceeds = r["p"]  # NULL if every lot is still pending
        if sold <= 1e-9:
            # No (live) sales rows. Don't wipe a legacy sold_shares that predates
            # the sales log (e.g. a position settled the old way).
            async with self._db.execute(
                "SELECT sold_shares FROM positions WHERE id=?", (position_id,)
            ) as cur:
                pr = await cur.fetchone()
            if r["n"] == 0 and pr and (pr["sold_shares"] or 0) > 0:
                return
            await self._db.execute(
                "UPDATE positions SET sold_shares=0, sold_proceeds=NULL, sold_at=NULL, status='open' "
                "WHERE id=?",
                (position_id,),
            )
            return
        async with self._db.execute(
            "SELECT size, sold_at FROM positions WHERE id=?", (position_id,)
        ) as cur:
            pr = await cur.fetchone()
        size = (pr["size"] if pr else 0.0) or 0.0
        status = "sold" if sold >= size - 1e-9 else "open"
        sold_at = (pr["sold_at"] if pr and pr["sold_at"] else utcnow())
        await self._db.execute(
            "UPDATE positions SET sold_shares=?, sold_proceeds=?, sold_at=?, status=? WHERE id=?",
            (sold, proceeds, sold_at, status, position_id),
        )

    async def list_sales(self, position_id: int) -> list[dict]:
        async with self._db.execute(
            "SELECT id, shares, proceeds, source, sold_at FROM position_sales "
            "WHERE position_id=? ORDER BY id",
            (position_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def add_sale(self, position_id: int, shares: float,
                       proceeds: float | None, source: str = "manual") -> None:
        await self._add_sale_row(position_id, shares, proceeds, source)
        await self._recompute_sold(position_id)
        await self._db.commit()

    async def update_sale(self, sale_id: int, shares: float, proceeds: float | None) -> None:
        async with self._db.execute(
            "SELECT position_id FROM position_sales WHERE id=?", (sale_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return
        await self._db.execute(
            "UPDATE position_sales SET shares=?, proceeds=? WHERE id=?",
            (shares, proceeds, sale_id),
        )
        await self._recompute_sold(row["position_id"])
        await self._db.commit()

    async def delete_sale(self, sale_id: int) -> None:
        async with self._db.execute(
            "SELECT position_id FROM position_sales WHERE id=?", (sale_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return
        await self._db.execute("DELETE FROM position_sales WHERE id=?", (sale_id,))
        await self._recompute_sold(row["position_id"])
        await self._db.commit()

    async def mark_sold(self, position_id: int, sold_shares: float, proceeds: float) -> None:
        """Legacy 'set the cumulative total' entry point (old Closing-card edit).
        Reimplemented on the sales log: replace the log with a single lot."""
        await self._db.execute("DELETE FROM position_sales WHERE position_id=?", (position_id,))
        if sold_shares and sold_shares > 0:
            await self._add_sale_row(position_id, sold_shares, proceeds, "manual")
        await self._recompute_sold(position_id)
        await self._db.commit()

    async def reopen_position(self, position_id: int) -> None:
        """Undo all sales for this leg → fully open again."""
        await self._db.execute("DELETE FROM position_sales WHERE position_id=?", (position_id,))
        await self._db.execute(
            "UPDATE positions SET status='open', sold_proceeds=NULL, sold_at=NULL, sold_shares=0 WHERE id=?",
            (position_id,),
        )
        await self._db.commit()

    async def build_summary(self) -> dict:
        async with self._db.execute(
            "SELECT * FROM positions WHERE status IN ('open','sold') ORDER BY platform, market_title"
        ) as cur:
            positions = [dict(r) for r in await cur.fetchall()]

        async with self._db.execute(
            """SELECT id, poly_condition_id, pf_market_id, poly_title,
                      poly_yes_token_id, poly_no_token_id, poly_fee_rate
               FROM matched_markets WHERE is_active=1"""
        ) as cur:
            matched = [dict(r) for r in await cur.fetchall()]
        poly_to_mm = {m["poly_condition_id"]: m for m in matched}
        pf_to_mm = {str(m["pf_market_id"]): m for m in matched}

        groups: dict[int, dict] = {}
        standalone: list[dict] = []
        for p in positions:
            is_poly = p["platform"] == "polymarket"
            mm = poly_to_mm.get(p["market_id"]) if is_poly else pf_to_mm.get(str(p["market_id"]))
            leg = await self._leg(p, mm)
            if mm:
                g = groups.setdefault(mm["id"], {"mm": mm, "poly": None, "pf": None})
                g["poly" if is_poly else "pf"] = leg
            elif leg["status"] == "open":
                standalone.append(leg)

        def _open_view(leg: dict) -> dict:
            """A leg restricted to its still-OPEN shares (cost/value prorated), so a
            partly-sold position can be shown as a normal arbitrage ROW, not a card."""
            if (leg.get("sold_shares") or 0) <= 0:
                return leg
            total = leg["shares"] or 0.0
            op = leg["open_shares"]
            frac = (op / total) if total > 0 else 0.0
            cost = (leg.get("cost") or 0.0) * frac
            cv = (leg["current_price"] * op) if leg.get("current_price") is not None else None
            return {**leg, "shares": op, "cost": cost, "current_value": cv,
                    "pnl": (cv - cost) if cv is not None else None}

        _name = {"polymarket": "Polymarket", "predictfun": "Predict.fun"}
        EPS = 1e-6
        pairs, closing, closed = [], [], []
        for g in groups.values():
            poly_leg, pf_leg = g["poly"], g["pf"]
            legs = [l for l in (poly_leg, pf_leg) if l]
            if len(legs) < 2:
                for leg in legs:
                    if leg["sold_shares"] <= 0:
                        standalone.append(leg)
                continue

            poly_open = poly_leg["open_shares"]
            pf_open = pf_leg["open_shares"]
            total_sold = poly_leg["sold_shares"] + pf_leg["sold_shares"]

            if poly_open > EPS and pf_open > EPS and poly_leg["side"] != pf_leg["side"]:
                # BOTH legs still hold open shares (incl. a partial sell on one leg)
                # → a normal arbitrage-position ROW using the OPEN shares; flag Not
                # Hedged when they're unequal. The position keeps its form (a row);
                # it does NOT turn into a separate card just because a leg was sold.
                pv, fv = _open_view(poly_leg), _open_view(pf_leg)
                cost = (pv["cost"] or 0) + (fv["cost"] or 0)
                guaranteed = min(poly_open, pf_open)
                imbalance = abs(poly_open - pf_open)
                hedged = imbalance < 1.0
                long_leg = pv if poly_open > pf_open else fv
                short_leg = fv if poly_open > pf_open else pv
                action = None
                if not hedged:
                    n = round(imbalance)
                    action = (
                        f"Buy {n} more {short_leg['side']} on {_name.get(short_leg['platform'], short_leg['platform'])}, "
                        f"or sell {n} {long_leg['side']} on {_name.get(long_leg['platform'], long_leg['platform'])}"
                    )
                pairs.append({
                    "matched_market_id": g["mm"]["id"], "title": g["mm"]["poly_title"],
                    "poly": pv, "pf": fv, "combined_cost": cost,
                    "max_payoff": guaranteed, "ev": guaranteed - cost,
                    "hedged": hedged, "matched_shares": guaranteed, "imbalance_shares": imbalance,
                    "long_platform": long_leg["platform"] if not hedged else None,
                    "long_side": long_leg["side"] if not hedged else None,
                    "short_platform": short_leg["platform"] if not hedged else None,
                    "short_side": short_leg["side"] if not hedged else None,
                    "hedge_action": action,
                })
            elif total_sold > EPS and (poly_open > EPS or pf_open > EPS):
                # One leg FULLY sold (the other still open) → Closing Arbitrage card.
                paid = (poly_leg["cost"] or 0) + (pf_leg["cost"] or 0)
                realized = sum(l.get("sold_proceeds") or 0.0 for l in legs)
                closing_legs, open_value = [], 0.0
                for l in legs:
                    ov = await self._open_leg_market_value(l, g["mm"]) if l["open_shares"] > 0 else 0.0
                    open_value += ov
                    closing_legs.append({
                        "id": l["id"], "platform": l["platform"], "side": l["side"],
                        "total_shares": l["shares"], "sold_shares": l["sold_shares"],
                        "sold_proceeds": l.get("sold_proceeds") or 0.0,
                        "open_shares": l["open_shares"], "open_value": ov,
                        "sales": l.get("sales") or [],
                    })
                c_imbalance = abs(poly_open - pf_open)
                c_hedged = c_imbalance < 1.0
                c_action = None
                if not c_hedged:
                    c_long = poly_leg if poly_open > pf_open else pf_leg
                    c_action = (f"Sell {round(c_imbalance)} {c_long['side']} on "
                                f"{_name.get(c_long['platform'], c_long['platform'])} to flatten")
                closing.append({
                    "matched_market_id": g["mm"]["id"], "title": g["mm"]["poly_title"],
                    "legs": closing_legs, "realized": realized, "open_value": open_value,
                    "paid": paid, "exit_now_pnl": realized + open_value - paid,
                    "hedged": c_hedged, "imbalance_shares": c_imbalance, "hedge_action": c_action,
                })
            elif total_sold > EPS and poly_open <= EPS and pf_open <= EPS and poly_leg["side"] != pf_leg["side"]:
                # BOTH legs fully sold → a completed (closed) arbitrage. Surface it
                # in the PNL history with its realized profit; deletable from there.
                paid = (poly_leg["cost"] or 0) + (pf_leg["cost"] or 0)
                proceeds = sum(l.get("sold_proceeds") or 0.0 for l in legs)
                closed.append({
                    "matched_market_id": g["mm"]["id"], "title": g["mm"]["poly_title"],
                    "paid": paid, "proceeds": proceeds, "profit": proceeds - paid,
                    "closed_at": max((l.get("sold_at") or "") for l in legs) or None,
                    "leg_ids": [l["id"] for l in legs],
                    "legs": [
                        {"platform": l["platform"], "side": l["side"],
                         "sold_proceeds": l.get("sold_proceeds") or 0.0,
                         "sales": l.get("sales") or []}
                        for l in legs
                    ],
                })
            else:
                for leg in legs:  # same-side / leftover
                    if leg["sold_shares"] <= 0:
                        standalone.append(leg)

        deployed = sum(p["combined_cost"] for p in pairs)
        max_payoff = sum(p["max_payoff"] for p in pairs)
        return {
            "stats": {
                "open_ev": max_payoff - deployed,
                "deployed": deployed,
                "max_payoff": max_payoff,
                "active_pairs": len(pairs),
            },
            "pairs": pairs,
            "closing": closing,
            "closed": closed,
            "standalone": standalone,
        }

    async def scan_pair_exits(self, min_profit_pct: float) -> list[dict]:
        """For every OPEN hedged pair, compute the best exit route right now and
        return the ones whose best-route ROI ≥ min_profit_pct, as plain (JSON-
        serializable) dicts ready to hand to the exit-alert formatter. Lean on
        purpose (no stats/ranking) so it can run on a few-second cadence."""
        async with self._db.execute(
            "SELECT * FROM positions WHERE status='open'"
        ) as c:
            positions = [dict(r) for r in await c.fetchall()]
        poly_by = {p["market_id"]: p for p in positions if p["platform"] == "polymarket"}
        pf_by = {str(p["market_id"]): p for p in positions if p["platform"] == "predictfun"}
        if not poly_by or not pf_by:
            return []

        async with self._db.execute(
            """SELECT id, poly_condition_id, pf_market_id, poly_title, poly_slug,
                      pf_category_slug, poly_yes_token_id, poly_no_token_id, poly_fee_rate
               FROM matched_markets WHERE is_active=1"""
        ) as c:
            mms = [dict(r) for r in await c.fetchall()]

        out: list[dict] = []
        for mm in mms:
            poly_pos = poly_by.get(mm["poly_condition_id"])
            pf_pos = pf_by.get(str(mm["pf_market_id"]))
            if not poly_pos or not pf_pos:
                continue
            poly_side = (poly_pos["side"] or "").upper()
            pf_side = (pf_pos["side"] or "").upper()
            if poly_side == pf_side or poly_side not in ("YES", "NO") or pf_side not in ("YES", "NO"):
                continue  # only true YES/NO hedges
            poly_open = (poly_pos["size"] or 0.0) - (poly_pos.get("sold_shares") or 0.0)
            pf_open = (pf_pos["size"] or 0.0) - (pf_pos.get("sold_shares") or 0.0)
            if poly_open <= 1e-6 or pf_open <= 1e-6:
                continue
            try:
                res = await self._evaluate_exit(mm, poly_pos, pf_pos, poly_side, pf_side, poly_open, pf_open)
            except Exception as e:
                logger.debug("exit scan eval failed mm=%s: %s", mm["id"], e)
                continue
            if res and res["best"]["roi"] >= min_profit_pct:
                out.append(res)
        return out

    async def _evaluate_exit(self, mm, poly_pos, pf_pos, poly_side, pf_side, poly_open, pf_open) -> dict | None:
        from services.arb_taker import exit_strategies

        poly_token = mm["poly_yes_token_id"] if poly_side == "YES" else mm["poly_no_token_id"]
        poly_book = await self._poly.get_book(poly_token)
        pf_ob = await self._pf.get_order_book(str(mm["pf_market_id"]))
        pf_book = _pf_side_book(pf_ob.get("yes_asks", []), pf_ob.get("yes_bids", []), pf_side)

        poly_best_ask = poly_book["asks"][0][0] if poly_book["asks"] else 0.0
        pf_best_ask = pf_book["asks"][0][0] if pf_book["asks"] else 0.0

        # Cost basis for the OPEN (unsold) shares only.
        poly_paid = _open_cost(poly_pos, poly_open)
        pf_paid = _open_cost(pf_pos, pf_open)
        paid = poly_paid + pf_paid
        if paid <= 0:
            return None

        poly_rate = mm["poly_fee_rate"] or 0.0
        pf_rate = await self._pf_fee_rate(mm["id"])
        strategies, best = exit_strategies(
            poly_book["bids"], poly_best_ask, poly_open, poly_rate,
            pf_book["bids"], pf_best_ask, pf_open, pf_rate, paid,
        )
        matched = min(poly_open, pf_open) or 1.0
        # The guaranteed-executable floor: sell both legs at market right now.
        market_only = next((s for s in strategies if s.name == "Two Market Sells"), strategies[best])
        return {
            "matched_market_id": mm["id"],
            "title": mm["poly_title"],
            "poly_url": f"https://polymarket.com/event/{mm['poly_slug']}" if mm.get("poly_slug") else "https://polymarket.com",
            "pf_url": f"https://predict.fun/market/{mm['pf_category_slug']}" if mm.get("pf_category_slug") else "https://predict.fun",
            "paid": paid,
            "bought_pct": (paid / matched) * 100.0,
            "now_sell_pct": (strategies[best].total_value / matched) * 100.0,
            "poly": {"side": poly_side, "shares": poly_open,
                     "avg_price": (poly_paid / poly_open) if poly_open else 0.0},
            "pf": {"side": pf_side, "shares": pf_open,
                   "avg_price": (pf_paid / pf_open) if pf_open else 0.0},
            "best": _strat_dict(strategies[best]),
            "market_only": _strat_dict(market_only),
            "strategies": [_strat_dict(s) for s in strategies],
        }

    async def _open_leg_market_value(self, leg: dict, mm: dict) -> float:
        """Net proceeds from market-selling the OPEN (unsold) portion now."""
        from services.arb_taker import sell_market
        shares = leg["open_shares"]
        side = leg["side"]
        if leg["platform"] == "polymarket":
            token = mm["poly_yes_token_id"] if side == "YES" else mm["poly_no_token_id"]
            book = await self._poly.get_book(token)
            return sell_market(book["bids"], shares, mm.get("poly_fee_rate") or 0.0, "poly").value
        ob = await self._pf.get_order_book(str(mm["pf_market_id"]))
        sb = _pf_side_book(ob.get("yes_asks", []), ob.get("yes_bids", []), side)
        rate = await self._pf_fee_rate(mm["id"])
        return sell_market(sb["bids"], shares, rate, "pf").value

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
            "status": p.get("status", "open"),
            "sold_proceeds": p.get("sold_proceeds"),
            "sold_shares": p.get("sold_shares") or 0.0,
            "open_shares": max(0.0, shares - (p.get("sold_shares") or 0.0)),
            "sales": await self.list_sales(p["id"]),
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

    async def build_pair_exit(self, mm_id: int) -> dict | None:
        """Everything the position-detail view needs to EXIT an arb pair:
        per-leg details, the three sell-all strategies (with fees), stats, books."""
        from services.arb_taker import exit_strategies, hedge_routes

        async with self._db.execute("SELECT * FROM matched_markets WHERE id=?", (mm_id,)) as c:
            mm = await c.fetchone()
        if not mm:
            return None
        mm = dict(mm)

        async with self._db.execute(
            """SELECT * FROM positions WHERE status='open' AND (
                 (platform='polymarket' AND market_id=?) OR (platform='predictfun' AND market_id=?))""",
            (mm["poly_condition_id"], str(mm["pf_market_id"])),
        ) as c:
            rows = [dict(r) for r in await c.fetchall()]
        poly_pos = next((r for r in rows if r["platform"] == "polymarket"), None)
        pf_pos = next((r for r in rows if r["platform"] == "predictfun"), None)
        if not poly_pos or not pf_pos:
            return None

        poly_side = (poly_pos["side"] or "").upper()
        pf_side = (pf_pos["side"] or "").upper()
        poly_token = mm["poly_yes_token_id"] if poly_side == "YES" else mm["poly_no_token_id"]

        poly_book = await self._poly.get_book(poly_token)
        pf_ob = await self._pf.get_order_book(str(mm["pf_market_id"]))
        pf_book = _pf_side_book(pf_ob.get("yes_asks", []), pf_ob.get("yes_bids", []), pf_side)

        poly_bids = poly_book["bids"]
        poly_best_ask = poly_book["asks"][0][0] if poly_book["asks"] else 0.0
        poly_best_bid = poly_bids[0][0] if poly_bids else 0.0
        pf_bids = pf_book["bids"]
        pf_best_ask = pf_book["asks"][0][0] if pf_book["asks"] else 0.0
        pf_best_bid = pf_bids[0][0] if pf_bids else 0.0

        # The exit applies to what's STILL HELD (size − already-sold), with the
        # cost basis prorated to those open shares — otherwise a partly-sold pair
        # is shown as if you can still sell the shares you already sold.
        poly_shares = (poly_pos["size"] or 0.0) - (poly_pos.get("sold_shares") or 0.0)
        pf_shares = (pf_pos["size"] or 0.0) - (pf_pos.get("sold_shares") or 0.0)
        poly_cost = _open_cost(poly_pos, poly_shares)
        pf_cost = _open_cost(pf_pos, pf_shares)
        paid = poly_cost + pf_cost
        poly_rate = mm["poly_fee_rate"] or 0.0
        pf_rate = await self._pf_fee_rate(mm["id"])

        strategies, best = exit_strategies(
            poly_bids, poly_best_ask, poly_shares, poly_rate,
            pf_bids, pf_best_ask, pf_shares, pf_rate, paid,
        )

        poly_leg = _detail_leg("polymarket", mm["poly_title"], poly_side, poly_shares, poly_cost, poly_best_ask, poly_best_bid)
        pf_leg = _detail_leg("predictfun", mm["pf_title"], pf_side, pf_shares, pf_cost, pf_best_ask, pf_best_bid)
        combined = _combined_leg(poly_leg, pf_leg)
        matched = min(poly_shares, pf_shares) or 1.0

        # poly_shares/pf_shares are already the OPEN (still-held) shares, so the
        # hedge status is judged on what's still held — consistent with the row.
        poly_open = poly_shares
        pf_open = pf_shares
        poly_avg = (poly_cost / poly_shares) if poly_shares > 0 else (poly_pos.get("avg_entry_price") or 0.0)
        pf_avg = (pf_cost / pf_shares) if pf_shares > 0 else (pf_pos.get("avg_entry_price") or 0.0)
        imbalance = abs(poly_open - pf_open)
        hedged = imbalance < 1.0
        poly_h = {"platform": "polymarket", "side": poly_side, "shares": poly_open,
                  "bought_at": poly_avg, "book": poly_book, "best_ask": poly_best_ask,
                  "best_bid": poly_best_bid, "fee_rate": poly_rate}
        pf_h = {"platform": "predictfun", "side": pf_side, "shares": pf_open,
                "bought_at": pf_avg, "book": pf_book, "best_ask": pf_best_ask,
                "best_bid": pf_best_bid, "fee_rate": pf_rate}
        over, under = (poly_h, pf_h) if poly_open >= pf_open else (pf_h, poly_h)
        target = min(poly_open, pf_open)
        hedge = {
            "hedged": hedged,
            "imbalance_shares": imbalance,
            "imbalance_pct": (imbalance / target * 100.0) if target > 0 else 0.0,
            "target_shares": target,
            "overweight_platform": over["platform"],
            "overweight_side": over["side"],
            "total_paid": paid,
            "routes": [] if hedged else hedge_routes(over, under, imbalance),
        }

        return {
            "matched_market_id": mm["id"],
            "title": mm["poly_title"],
            "poly_url": f"https://polymarket.com/event/{mm['poly_slug']}",
            "pf_url": f"https://predict.fun/market/{mm['pf_category_slug']}",
            "est_ev": matched - paid,
            "paid": paid,
            "bought_at": (paid / matched) * 100.0,
            "now_bid": ((poly_leg["at_bid"] + pf_leg["at_bid"]) / matched) * 100.0,
            "ask_pnl": combined["ask_pnl"],
            "bid_pnl": combined["bid_pnl"],
            "strategies": [_strat_dict(s) for s in strategies],
            "best_index": best,
            "legs": [poly_leg, pf_leg],
            "combined": combined,
            "stats": await self._market_stats(mm["id"]),
            "poly_book": {"asks": poly_book["asks"], "bids": poly_book["bids"]},
            "pf_book": {"asks": pf_book["asks"], "bids": pf_book["bids"]},
            "hedge": hedge,
        }

    async def _pf_fee_rate(self, mm_id: int) -> float:
        async with self._db.execute(
            "SELECT pf_taker_fee_rate FROM market_prices WHERE matched_market_id=?", (mm_id,)
        ) as c:
            r = await c.fetchone()
        if r and r["pf_taker_fee_rate"]:
            return r["pf_taker_fee_rate"]
        return self._settings.PF_FALLBACK_FEE_BPS / 10000.0

    async def _market_stats(self, mm_id: int) -> dict:
        async with self._db.execute("SELECT * FROM market_stats WHERE matched_market_id=?", (mm_id,)) as c:
            row = await c.fetchone()
        s = dict(row) if row else {}
        out: dict = {}
        for key, better in (("poly_volume", "high"), ("poly_liquidity", "high"),
                            ("poly_spread", "low"), ("pf_liquidity", "high"), ("pf_spread", "low")):
            val = s.get(key)
            if val is None:
                out[key] = {"value": None, "rank": None, "total": None, "label": None}
                continue
            async with self._db.execute(f"SELECT COUNT(*) FROM market_stats WHERE {key} IS NOT NULL") as c:
                total = (await c.fetchone())[0]
            op = ">" if better == "high" else "<"
            async with self._db.execute(
                f"SELECT COUNT(*) FROM market_stats WHERE {key} IS NOT NULL AND {key} {op} ?", (val,)
            ) as c:
                rank = (await c.fetchone())[0] + 1
            out[key] = {"value": val, "rank": rank, "total": total, "label": _stat_label(key, rank, total)}
        return out

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


def _pf_side_book(yes_asks, yes_bids, side: str) -> dict:
    """Order book for the held PF outcome. YES uses the raw book; NO is the
    complement (NO ask @ p = YES bid @ 1−p; NO bid @ p = YES ask @ 1−p)."""
    if side == "YES":
        return {"asks": list(yes_asks), "bids": list(yes_bids)}
    asks = sorted([(round(1.0 - p, 6), s) for p, s in yes_bids], key=lambda x: x[0])
    bids = sorted([(round(1.0 - p, 6), s) for p, s in yes_asks], key=lambda x: x[0], reverse=True)
    return {"asks": asks, "bids": bids}


def _detail_leg(platform, title, side, shares, paid, best_ask, best_bid) -> dict:
    at_ask = shares * best_ask
    at_bid = shares * best_bid
    return {
        "platform": platform, "title": title, "side": side, "shares": shares,
        "avg_price": (paid / shares) if shares else None,
        "paid": paid, "best_ask": best_ask, "best_bid": best_bid,
        "at_ask": at_ask, "at_bid": at_bid,
        "ask_pnl": at_ask - paid, "bid_pnl": at_bid - paid,
    }


def _combined_leg(a: dict, b: dict) -> dict:
    paid = a["paid"] + b["paid"]
    at_ask = a["at_ask"] + b["at_ask"]
    at_bid = a["at_bid"] + b["at_bid"]
    matched = min(a["shares"], b["shares"]) or 1.0
    return {
        "platform": "combined", "title": "Combined arbitrage pair", "side": "",
        "shares": matched, "avg_price": paid / matched,
        "paid": paid, "best_ask": a["best_ask"] + b["best_ask"], "best_bid": a["best_bid"] + b["best_bid"],
        "at_ask": at_ask, "at_bid": at_bid, "ask_pnl": at_ask - paid, "bid_pnl": at_bid - paid,
    }


def _strat_dict(s) -> dict:
    return {"name": s.name, "poly": vars(s.poly), "pf": vars(s.pf),
            "total_value": s.total_value, "net": s.net, "roi": s.roi}


def _open_cost(pos: dict, open_shares: float) -> float:
    """Cost basis of the still-open shares: prorate cost_usd by the open fraction
    (falls back to avg_entry_price * open_shares)."""
    size = pos.get("size") or 0.0
    cost = pos.get("cost_usd")
    if cost is not None and size > 0:
        return cost * (open_shares / size)
    return open_shares * (pos.get("avg_entry_price") or 0.0)


def _stat_label(key: str, rank: int, total: int) -> str | None:
    if not total:
        return None
    pct = rank / total
    if "spread" in key:
        return "Tight" if pct <= 0.33 else ("Normal" if pct <= 0.66 else "Wide")
    if "liquidity" in key:
        return "Deep" if pct <= 0.33 else ("Average" if pct <= 0.66 else "Shallow")
    return "High" if pct <= 0.33 else ("Average" if pct <= 0.66 else "Low")
