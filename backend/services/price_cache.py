import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MarketPrices:
    matched_market_id: int
    poly_yes: float | None = None
    poly_no: float | None = None
    pf_yes: float | None = None
    pf_no: float | None = None
    poly_fee_rate: float = 0.0
    pf_taker_fee_rate: float = 0.0
    poly_ts: datetime | None = None
    pf_ts: datetime | None = None

    def is_fresh(self, max_age_seconds: int = 30) -> bool:
        if self.poly_ts is None or self.pf_ts is None:
            return False
        now = datetime.now(timezone.utc)
        poly_age = (now - self.poly_ts).total_seconds()
        pf_age = (now - self.pf_ts).total_seconds()
        return poly_age <= max_age_seconds and pf_age <= max_age_seconds

    def poly_changed(self, yes: float | None, no: float | None) -> bool:
        return yes != self.poly_yes or no != self.poly_no

    def pf_changed(self, yes: float | None, no: float | None) -> bool:
        return yes != self.pf_yes or no != self.pf_no


class PriceCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[int, MarketPrices] = {}
        # mapping: pf_market_id (str) → matched_market_id (int)
        self._pf_id_map: dict[str, int] = {}

    def register(self, matched_market_id: int, pf_market_id: str, poly_fee_rate: float = 0.0) -> None:
        with self._lock:
            if matched_market_id not in self._data:
                self._data[matched_market_id] = MarketPrices(
                    matched_market_id=matched_market_id,
                    poly_fee_rate=poly_fee_rate,
                )
            else:
                self._data[matched_market_id].poly_fee_rate = poly_fee_rate
            self._pf_id_map[str(pf_market_id)] = matched_market_id

    def update_poly(self, mid: int, yes: float | None, no: float | None) -> bool:
        with self._lock:
            entry = self._data.get(mid)
            if entry is None:
                return False
            changed = entry.poly_changed(yes, no)
            entry.poly_yes = yes
            entry.poly_no = no
            entry.poly_ts = datetime.now(timezone.utc)
            return changed

    def update_pf(self, pf_market_id: str, yes: float, no: float, fee_rate: float) -> tuple[int | None, bool]:
        with self._lock:
            mid = self._pf_id_map.get(str(pf_market_id))
            if mid is None:
                return None, False
            entry = self._data.get(mid)
            if entry is None:
                return None, False
            changed = entry.pf_changed(yes, no)
            entry.pf_yes = yes
            entry.pf_no = no
            entry.pf_taker_fee_rate = fee_rate
            entry.pf_ts = datetime.now(timezone.utc)
            return mid, changed

    def update_pf_prices(self, pf_market_id: str, yes: float, no: float) -> tuple[int | None, bool]:
        """Real-time price update from the WebSocket — refreshes yes/no/ts but
        keeps the fee rate seeded by the REST sync."""
        with self._lock:
            mid = self._pf_id_map.get(str(pf_market_id))
            if mid is None:
                return None, False
            entry = self._data.get(mid)
            if entry is None:
                return None, False
            changed = entry.pf_changed(yes, no)
            entry.pf_yes = yes
            entry.pf_no = no
            entry.pf_ts = datetime.now(timezone.utc)
            return mid, changed

    def get(self, mid: int) -> MarketPrices | None:
        with self._lock:
            return self._data.get(mid)

    def get_all_fresh(self, max_age_seconds: int = 30) -> list[MarketPrices]:
        with self._lock:
            return [p for p in self._data.values() if p.is_fresh(max_age_seconds)]

    def get_all(self) -> list[MarketPrices]:
        with self._lock:
            return list(self._data.values())

    def remove(self, mid: int) -> None:
        with self._lock:
            self._data.pop(mid, None)
            for k, v in list(self._pf_id_map.items()):
                if v == mid:
                    del self._pf_id_map[k]
