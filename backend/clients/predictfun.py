import asyncio
import logging

import aiohttp

from config import Settings

logger = logging.getLogger(__name__)


def _parse_price(outcomes: list[dict], name: str) -> float | None:
    """Extract best ask price for a given outcome name (Yes/No/Up/Down).
    bestAsk/bestBid are objects {price: float, size: float}, not scalars."""
    for o in outcomes:
        if o.get("name", "").lower() == name.lower():
            ask = o.get("bestAsk")
            if ask is None:
                return None
            if isinstance(ask, dict):
                return float(ask["price"]) if ask.get("price") is not None else None
            return float(ask)
    return None


def _yes_no_names(outcomes: list[dict]) -> tuple[str, str]:
    """Return the (yes-like, no-like) outcome names for a market."""
    names = [o.get("name", "") for o in outcomes]
    for yes_name in ("Yes", "Up", "True", "Higher"):
        for no_name in ("No", "Down", "False", "Lower"):
            if yes_name in names and no_name in names:
                return yes_name, no_name
    if len(names) >= 2:
        return names[0], names[1]
    return "Yes", "No"


class PredictFunClient:
    def __init__(self, session: aiohttp.ClientSession, settings: Settings):
        self._session = session
        self._base = settings.PREDICTFUN_REST_URL
        self._api_key = settings.PREDICTFUN_API_KEY

    @property
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    async def get_markets(self) -> list[dict]:
        """Fetch all open markets using status=OPEN filter. Paginates all pages."""
        all_markets: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        # Fetch EVERY open market. The loop ends naturally when PF returns an
        # empty page or the cursor stops advancing; this is only an anti-
        # infinite-loop backstop (≈200k markets), never a truncation.
        max_pages = 10000

        for page in range(max_pages):
            params: dict = {"status": "OPEN", "limit": 20}
            if cursor:
                params["after"] = cursor
            data = None
            # Retry a page on 429 (rate limit) so a transient throttle doesn't
            # abort the whole market sync.
            for attempt in range(4):
                try:
                    async with self._session.get(
                        f"{self._base}/v1/markets",
                        headers=self._headers,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as r:
                        if r.status == 429:
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                        r.raise_for_status()
                        data = await r.json(content_type=None)
                        break
                except Exception as e:
                    logger.warning("PF get_markets page %d error: %s", page, e)
                    break
            if data is None:
                break

            batch = data.get("data", [])
            if not batch:
                break

            for m in batch:
                if len(m.get("outcomes", [])) == 2:
                    all_markets.append(m)

            new_cursor = data.get("cursor")
            if not new_cursor or new_cursor in seen_cursors:
                break
            seen_cursors.add(new_cursor)
            cursor = new_cursor

        logger.info("PF get_markets: found %d open markets", len(all_markets))
        return all_markets

    async def get_market_price(self, market_id: str) -> dict | None:
        try:
            async with self._session.get(
                f"{self._base}/v1/markets/{market_id}",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status == 404:
                    return None
                r.raise_for_status()
                raw = await r.json(content_type=None)
                # Individual endpoint wraps the market in {"data": {...}}
                return raw.get("data", raw) if isinstance(raw, dict) else raw
        except Exception as e:
            logger.debug("PF get_market_price(%s) error: %s", market_id, e)
            return None

    def extract_prices(self, market_data: dict) -> tuple[float | None, float | None, float]:
        """Return (yes_price, no_price, fee_rate) from a market dict."""
        outcomes = market_data.get("outcomes", [])
        yes_name, no_name = _yes_no_names(outcomes)
        yes_p = _parse_price(outcomes, yes_name)
        no_p = _parse_price(outcomes, no_name)
        fee_bps = float(market_data.get("feeRateBps") or 0)
        fee_rate = fee_bps / 10000.0
        return yes_p, no_p, fee_rate

    async def get_order_book(self, market_id: str) -> dict[str, list[tuple[float, float]]]:
        """Order book for a PF market. The endpoint returns the YES side only:
        {asks: YES asks, bids: YES bids}. Returns both as ascending ladders.
        The NO-side taker ladder is derived from YES bids via no_asks_from_bids."""
        try:
            async with self._session.get(
                f"{self._base}/v1/markets/{market_id}/orderbook",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status == 404:
                    return {"yes_asks": [], "yes_bids": []}
                r.raise_for_status()
                raw = await r.json(content_type=None)
        except Exception as e:
            logger.debug("PF get_order_book(%s) error: %s", market_id, e)
            return {"yes_asks": [], "yes_bids": []}

        data = raw.get("data", raw) if isinstance(raw, dict) else {}

        def _clean(rows, ascending: bool) -> list[tuple[float, float]]:
            out: list[tuple[float, float]] = []
            for row in rows or []:
                try:
                    price, size = float(row[0]), float(row[1])
                except (IndexError, TypeError, ValueError):
                    continue
                if size > 0 and 0.0 < price < 1.0:
                    out.append((price, size))
            out.sort(key=lambda lv: lv[0], reverse=not ascending)
            return out

        return {
            "yes_asks": _clean(data.get("asks"), ascending=True),
            "yes_bids": _clean(data.get("bids"), ascending=False),  # best bid first
        }

    @staticmethod
    def no_asks_from_bids(
        yes_bids: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """Buying NO as a taker matches against YES bids: a NO ask at price p
        (size s) is equivalent to a YES bid at price (1-p) (size s). Returns the
        NO ask ladder ASCENDING by NO price (i.e. from the highest YES bid down)."""
        no_asks = [(round(1.0 - p, 6), s) for p, s in yes_bids]
        no_asks.sort(key=lambda lv: lv[0])
        return no_asks

    async def get_positions(self, wallet: str) -> list[dict]:
        try:
            async with self._session.get(
                f"{self._base}/v1/positions",
                headers=self._headers,
                params={"wallet": wallet, "limit": 500},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 404:
                    return []
                r.raise_for_status()
                data = await r.json(content_type=None)
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.warning("PF get_positions(%s) error: %s", wallet[:8], e)
            return []
