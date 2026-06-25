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


class SaleOut(BaseModel):
    id: int
    shares: float
    proceeds: float | None = None   # None = pending (cash not entered yet)
    source: str = "manual"          # 'manual' | 'auto'
    sold_at: str


class SaleIn(BaseModel):
    shares: float
    proceeds: float | None = None


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
    status: str = "open"
    sold_proceeds: float | None = None
    sales: list[SaleOut] = []


class ClosingLegOut(BaseModel):
    id: int
    platform: str
    side: str
    total_shares: float
    sold_shares: float
    sold_proceeds: float
    open_shares: float
    open_value: float
    sales: list[SaleOut] = []


class ClosingPairOut(BaseModel):
    matched_market_id: int
    title: str
    legs: list[ClosingLegOut]
    realized: float
    open_value: float
    paid: float
    exit_now_pnl: float
    # Hedge status of the REMAINING open shares (a partial sell on one leg leaves
    # the open portions unequal → directional exposure on the difference).
    hedged: bool = True
    imbalance_shares: float = 0.0
    hedge_action: str | None = None


class MarkSoldIn(BaseModel):
    sold_shares: float
    proceeds: float


class ArbPairOut(BaseModel):
    matched_market_id: int
    title: str
    poly: PositionLegOut
    pf: PositionLegOut
    combined_cost: float
    max_payoff: float
    ev: float
    # Hedge status: the two legs must hold EQUAL shares to be a full hedge.
    # matched_shares = min(poly, pf); the excess on the larger leg is unhedged.
    hedged: bool = True
    matched_shares: float = 0.0
    imbalance_shares: float = 0.0
    long_platform: str | None = None   # leg holding the excess (unhedged) shares
    long_side: str | None = None
    short_platform: str | None = None  # leg to add shares to, to hedge
    short_side: str | None = None
    hedge_action: str | None = None    # human-readable fix


class PortfolioStatsOut(BaseModel):
    open_ev: float
    deployed: float
    max_payoff: float
    active_pairs: int


class PortfolioSummaryOut(BaseModel):
    stats: PortfolioStatsOut
    pairs: list[ArbPairOut]
    closing: list[ClosingPairOut] = []
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
    holding_poly_side: str | None = None  # "YES"/"NO" if user holds a Poly position here
    holding_poly_shares: float | None = None
    holding_poly_cost: float | None = None


class WalletIn(BaseModel):
    address: str


# ── Exit / sell a pair ────────────────────────────────────────────────────────

class ExitLegOut(BaseModel):
    kind: str          # "market" | "limit"
    shares: float
    avg_price: float
    value: float
    fee: float


class ExitStrategyOut(BaseModel):
    name: str
    poly: ExitLegOut
    pf: ExitLegOut
    total_value: float
    net: float
    roi: float


class DetailLegOut(BaseModel):
    platform: str
    title: str
    side: str
    shares: float
    avg_price: float | None   # bought-at price (paid/shares)
    paid: float
    best_ask: float
    best_bid: float
    at_ask: float
    at_bid: float
    ask_pnl: float
    bid_pnl: float


class StatItemOut(BaseModel):
    value: float | None = None
    rank: int | None = None
    total: int | None = None
    label: str | None = None


class PairStatsOut(BaseModel):
    poly_volume: StatItemOut
    poly_liquidity: StatItemOut
    poly_spread: StatItemOut
    pf_liquidity: StatItemOut
    pf_spread: StatItemOut


class OrderBookOut(BaseModel):
    asks: list[tuple[float, float]]
    bids: list[tuple[float, float]]


class HedgeRouteLegOut(BaseModel):
    kind: str            # "market" | "limit"
    fillable: float
    exec_price: float
    slippage_pct: float
    fee: float
    net_cost: float      # + = you pay, − = you receive
    pl_impact: float


class HedgeRouteOut(BaseModel):
    action: str          # "SELL" | "BUY"
    platform: str        # "polymarket" | "predictfun"
    side: str            # "YES" | "NO"
    shares: float        # imbalance to fix
    current_shares: float
    bought_at: float | None = None
    market: HedgeRouteLegOut
    limit: HedgeRouteLegOut
    executable: bool
    note: str | None = None
    lowest_cost: bool = False
    best_pl: bool = False


class HedgeOut(BaseModel):
    hedged: bool
    imbalance_shares: float
    imbalance_pct: float
    target_shares: float
    overweight_platform: str
    overweight_side: str
    total_paid: float
    routes: list[HedgeRouteOut] = []


class PairExitOut(BaseModel):
    matched_market_id: int
    title: str
    poly_url: str
    pf_url: str
    est_ev: float
    paid: float
    bought_at: float       # combined ¢ (paid / matched shares)
    now_bid: float         # combined ¢ (sell-now value / matched shares)
    ask_pnl: float
    bid_pnl: float
    strategies: list[ExitStrategyOut]
    best_index: int
    legs: list[DetailLegOut]
    combined: DetailLegOut
    stats: PairStatsOut
    poly_book: OrderBookOut
    pf_book: OrderBookOut
    hedge: HedgeOut | None = None


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
