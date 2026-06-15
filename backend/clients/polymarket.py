import asyncio
import logging
from typing import Any

import aiohttp

from config import Settings

logger = logging.getLogger(__name__)

# Polymarket taker fee rates by category (from docs)
POLY_FEE_RATES: dict[str, float] = {
    "crypto": 0.07,
    "sports": 0.03,
    "finance": 0.04,
    "politics": 0.04,
    "economics": 0.05,
    "culture": 0.05,
    "weather": 0.05,
    "other": 0.05,
    "general": 0.05,
    "mentions": 0.04,
    "tech": 0.04,
    "technology": 0.04,
    "geopolitics": 0.0,
}


def get_poly_fee_rate(category: str) -> float:
    return POLY_FEE_RATES.get(category.lower().strip(), 0.05)


def calc_poly_fee(shares: float, fee_rate: float, price: float) -> float:
    """fee = C × feeRate × p × (1 - p)"""
    return shares * fee_rate * price * (1.0 - price)


class PolymarketClient:
    def __init__(self, session: aiohttp.ClientSession, settings: Settings):
        self._session = session
        self._gamma = settings.POLYMARKET_GAMMA_URL
        self._clob = settings.POLYMARKET_CLOB_URL
        self._data = settings.POLYMARKET_DATA_URL
        self._sem = asyncio.Semaphore(30)

    # Gamma /markets caps each response at 100 rows regardless of the limit param.
    PAGE_SIZE = 100

    async def get_markets(self, limit: int = PAGE_SIZE, offset: int = 0) -> list[dict]:
        """Fetch active markets from Gamma API. include_tag exposes each market's
        category tags (used to pick the correct per-category taker fee)."""
        params = {
            "limit": limit, "offset": offset,
            "active": "true", "closed": "false", "include_tag": "true",
        }
        try:
            async with self._session.get(f"{self._gamma}/markets", params=params) as r:
                r.raise_for_status()
                data = await r.json()
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.warning("Polymarket get_markets error: %s", e)
            return []

    async def get_all_active_markets(self, max_markets: int = 20000) -> list[dict]:
        """Paginate through every active market. The API returns at most
        PAGE_SIZE rows per call, so we keep advancing the offset until a short
        or empty page (or the API's max-offset 422) ends the loop."""
        all_markets: list[dict] = []
        offset = 0
        while offset < max_markets:
            batch = await self.get_markets(limit=self.PAGE_SIZE, offset=offset)
            if not batch:
                break
            all_markets.extend(batch)
            if len(batch) < self.PAGE_SIZE:
                break
            offset += self.PAGE_SIZE
        logger.info("Polymarket: fetched %d active markets", len(all_markets))
        return all_markets

    async def get_markets_by_condition_ids(self, condition_ids: list[str]) -> list[dict]:
        """Fetch Poly markets for specific condition ids (chunks of 100, in
        parallel). This is how we match against Predict.fun: PF tells us each
        market's Polymarket conditionId, and offset pagination caps at ~10,100
        active markets (Polymarket has more), so fetching by id is the only way
        to reach EVERY referenced market. Returns markets incl. closed ones."""
        unique = [c for c in dict.fromkeys(condition_ids) if c]
        chunk = 100
        out: list[dict] = []

        async def _one(batch: list[str]) -> list[dict]:
            params = [("condition_ids", c) for c in batch]
            params += [("limit", str(len(batch))), ("include_tag", "true")]
            async with self._sem:
                try:
                    async with self._session.get(f"{self._gamma}/markets", params=params) as r:
                        if r.status != 200:
                            return []
                        data = await r.json()
                        return data if isinstance(data, list) else data.get("data", [])
                except Exception as e:
                    logger.debug("get_markets_by_condition_ids chunk error: %s", e)
                    return []

        results = await asyncio.gather(
            *(_one(unique[i:i + chunk]) for i in range(0, len(unique), chunk))
        )
        for r in results:
            out.extend(r)
        logger.info("Polymarket: fetched %d markets by conditionId (from %d ids)", len(out), len(unique))
        return out

    async def get_midprice(self, token_id: str) -> float | None:
        """Get best ask price for a CLOB token (what you pay to buy)."""
        async with self._sem:
            try:
                async with self._session.get(
                    f"{self._clob}/price",
                    params={"token_id": token_id, "side": "buy"},
                ) as r:
                    if r.status == 404:
                        return None
                    r.raise_for_status()
                    data = await r.json()
                    price_str = data.get("price")
                    return float(price_str) if price_str else None
            except Exception as e:
                logger.debug("get_midprice(%s) error: %s", token_id[:8], e)
                return None

    async def get_market_prices(
        self, yes_token_id: str, no_token_id: str
    ) -> tuple[float | None, float | None]:
        """Fetch both Yes and No prices in parallel."""
        yes_price, no_price = await asyncio.gather(
            self.get_midprice(yes_token_id),
            self.get_midprice(no_token_id),
        )
        return yes_price, no_price

    async def get_prices_batch(self, token_ids: list[str]) -> dict[str, float]:
        """Best ask (buy) price for many tokens at once via the CLOB /prices
        POST endpoint. Returns {token_id: price}. Splits into chunks so a few
        requests cover hundreds of markets instead of one request per token."""
        out: dict[str, float] = {}
        chunk = 250
        unique = [t for t in dict.fromkeys(token_ids) if t]

        async def _one(batch: list[str]) -> None:
            body = [{"token_id": t, "side": "BUY"} for t in batch]
            async with self._sem:
                try:
                    async with self._session.post(f"{self._clob}/prices", json=body) as r:
                        r.raise_for_status()
                        data = await r.json()
                except Exception as e:
                    logger.debug("get_prices_batch chunk error: %s", e)
                    return
            for tid, sides in (data or {}).items():
                price = sides.get("BUY") if isinstance(sides, dict) else None
                if price is not None:
                    try:
                        out[tid] = float(price)
                    except (TypeError, ValueError):
                        pass

        await asyncio.gather(
            *(_one(unique[i:i + chunk]) for i in range(0, len(unique), chunk))
        )
        return out

    async def get_order_book(self, token_id: str) -> list[tuple[float, float]]:
        """Full ask ladder for a CLOB token as a taker would consume it:
        [(price, size), ...] sorted ASCENDING by price (cheapest fill first).
        The API returns asks descending, so we re-sort."""
        async with self._sem:
            try:
                async with self._session.get(
                    f"{self._clob}/book", params={"token_id": token_id}
                ) as r:
                    if r.status == 404:
                        return []
                    r.raise_for_status()
                    data = await r.json()
            except Exception as e:
                logger.debug("get_order_book(%s) error: %s", token_id[:8], e)
                return []
        levels: list[tuple[float, float]] = []
        for a in data.get("asks") or []:
            try:
                price = float(a["price"])
                size = float(a["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if size > 0 and 0.0 < price < 1.0:
                levels.append((price, size))
        levels.sort(key=lambda lv: lv[0])
        return levels

    async def get_clob_market_info(self, condition_id: str) -> dict[str, Any] | None:
        """Fetch market fee info: fd.r = feeRate, fd.e = exponent, fd.to = takerOnly."""
        try:
            async with self._session.get(
                f"{self._clob}/markets/{condition_id}"
            ) as r:
                if r.status == 404:
                    return None
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            logger.debug("get_clob_market_info(%s) error: %s", condition_id[:8], e)
            return None

    async def get_positions(self, wallet: str) -> list[dict]:
        """Fetch user positions from Data API."""
        try:
            async with self._session.get(
                f"{self._data}/positions",
                params={"user": wallet, "limit": 500},
            ) as r:
                if r.status == 404:
                    return []
                r.raise_for_status()
                data = await r.json()
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.warning("get_positions(%s) error: %s", wallet[:8], e)
            return []

    async def get_trades(self, wallet: str, limit: int = 200) -> list[dict]:
        """Fetch user trade history from Data API."""
        try:
            async with self._session.get(
                f"{self._data}/activity",
                params={"user": wallet, "limit": limit},
            ) as r:
                if r.status == 404:
                    return []
                r.raise_for_status()
                data = await r.json()
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.warning("get_trades(%s) error: %s", wallet[:8], e)
            return []
