from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ArbOpportunityOut(BaseModel):
    id: int
    matched_market_id: int
    poly_title: str
    pf_title: str
    poly_category: str
    poly_slug: str
    pf_slug: str
    strategy: str
    poly_side: str
    pf_side: str
    poly_price: float
    pf_price: float
    combined_cost: float
    gross_profit_pct: float
    poly_fee_usd: float
    pf_fee_usd: float
    total_fee_usd: float
    net_profit_pct: float
    net_profit_usd: float
    notional_usd: float
    max_wager_usd: float
    max_profit_usd: float
    net_pct_top: float
    detected_at: str
    is_live: bool


class ArbListOut(BaseModel):
    total: int
    items: list[ArbOpportunityOut]


class CalculatorLegOut(BaseModel):
    platform: str               # 'polymarket' | 'predictfun'
    side: str                   # 'YES' | 'NO'
    title: str
    url: str
    fee_bps: float              # taker fee in basis points
    fee_mode: str               # 'poly_formula' | 'pct_of_cost'
    ladder: list[tuple[float, float]]   # ascending ask levels [(price, size), ...]


class CalculatorOut(BaseModel):
    opportunity_id: int
    matched_market_id: int
    strategy: str
    poly: CalculatorLegOut
    pf: CalculatorLegOut
    fetched_at: str


class PositionOut(BaseModel):
    id: int
    wallet_address: str
    platform: str
    market_id: str
    market_title: str
    side: str
    size: float
    avg_entry_price: float | None
    current_price: float | None
    unrealized_pnl: float | None
    status: str
    fetched_at: str


class PortfolioOut(BaseModel):
    wallet: str
    positions: list[PositionOut]
    total_unrealized_pnl: float


class PositionLegOut(BaseModel):
    id: int
    platform: str
    market_id: str
    market_title: str
    side: str
    shares: float
    avg_price: float | None
    cost: float | None
    current_price: float | None
    current_value: float | None
    pnl: float | None
    source: str


class ArbPairOut(BaseModel):
    matched_market_id: int
    title: str
    poly: PositionLegOut
    pf: PositionLegOut
    combined_cost: float
    max_payoff: float
    ev: float


class PortfolioStatsOut(BaseModel):
    open_ev: float
    deployed: float
    max_payoff: float
    active_pairs: int


class PortfolioSummaryOut(BaseModel):
    stats: PortfolioStatsOut
    pairs: list[ArbPairOut]
    standalone: list[PositionLegOut]


class ManualPositionIn(BaseModel):
    market_id: str
    title: str
    side: str
    shares: float
    total_cost: float


class PfMarketOut(BaseModel):
    id: str
    title: str
    category_slug: str


class WalletIn(BaseModel):
    address: str


class PnlSummaryOut(BaseModel):
    unrealized_pnl: float
    realized_pnl: float
    total_fees_paid: float
    net_pnl: float


class FeesSummaryOut(BaseModel):
    polymarket_fees: float
    predictfun_fees: float
    total_fees: float


class SettingOut(BaseModel):
    key: str
    value: str


class SettingsOut(BaseModel):
    settings: dict[str, str]


class SettingUpdateIn(BaseModel):
    key: str
    value: str
