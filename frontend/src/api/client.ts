import axios from "axios";

const api = axios.create({ baseURL: "/api" });

export interface ArbOpportunity {
  id: number;
  matched_market_id: number;
  poly_title: string;
  pf_title: string;
  poly_category: string;
  poly_slug: string;
  pf_slug: string;
  strategy: string;
  poly_side: string;
  pf_side: string;
  poly_price: number;
  pf_price: number;
  combined_cost: number;
  gross_profit_pct: number;
  poly_fee_usd: number;
  pf_fee_usd: number;
  total_fee_usd: number;
  net_profit_pct: number;
  net_profit_usd: number;
  notional_usd: number;
  max_wager_usd: number;
  max_profit_usd: number;
  net_pct_top: number;
  detected_at: string;
  is_live: boolean;
}

export interface CalculatorLeg {
  platform: string;
  side: string;
  title: string;
  url: string;
  fee_bps: number;
  fee_mode: string;
  ladder: [number, number][];
}

export interface CalculatorData {
  opportunity_id: number;
  matched_market_id: number;
  strategy: string;
  poly: CalculatorLeg;
  pf: CalculatorLeg;
  fetched_at: string;
}

export interface Position {
  id: number;
  wallet_address: string;
  platform: string;
  market_id: string;
  market_title: string;
  side: string;
  size: number;
  avg_entry_price: number | null;
  current_price: number | null;
  unrealized_pnl: number | null;
  status: string;
  fetched_at: string;
}

export const fetchOpportunities = (liveOnly = true, minPct = 0, limit = 2000) =>
  api.get<{ total: number; items: ArbOpportunity[] }>("/arb/opportunities", {
    params: { live_only: liveOnly, min_pct: minPct, limit },
  });

export const fetchHistory = (limit = 100) =>
  api.get<{ total: number; items: ArbOpportunity[] }>("/arb/history", {
    params: { limit },
  });

export const fetchCalculator = (opportunityId: number) =>
  api.get<CalculatorData>(`/arb/opportunities/${opportunityId}/calculator`);

export interface PositionLeg {
  id: number;
  platform: string;
  market_id: string;
  market_title: string;
  side: string;
  shares: number;
  avg_price: number | null;
  cost: number | null;
  current_price: number | null;
  current_value: number | null;
  pnl: number | null;
  source: string;
  status: string;
  sold_proceeds: number | null;
}

export interface ClosingLeg {
  id: number;
  platform: string;
  side: string;
  total_shares: number;
  sold_shares: number;
  sold_proceeds: number;
  open_shares: number;
  open_value: number;
}

export interface ClosingPair {
  matched_market_id: number;
  title: string;
  legs: ClosingLeg[];
  realized: number;
  open_value: number;
  paid: number;
  exit_now_pnl: number;
  hedged: boolean;
  imbalance_shares: number;
  hedge_action: string | null;
}

export interface ArbPair {
  matched_market_id: number;
  title: string;
  poly: PositionLeg;
  pf: PositionLeg;
  combined_cost: number;
  max_payoff: number;
  ev: number;
  hedged: boolean;
  matched_shares: number;
  imbalance_shares: number;
  long_platform: string | null;
  long_side: string | null;
  short_platform: string | null;
  short_side: string | null;
  hedge_action: string | null;
}

export interface PortfolioSummary {
  stats: { open_ev: number; deployed: number; max_payoff: number; active_pairs: number };
  pairs: ArbPair[];
  closing: ClosingPair[];
  standalone: PositionLeg[];
}

export interface PfMarket {
  id: string;
  title: string;
  category_slug: string;
  holding_poly_side: string | null;
  holding_poly_shares: number | null;
  holding_poly_cost: number | null;
}

export interface ExitLeg { kind: string; shares: number; avg_price: number; value: number; fee: number; }
export interface ExitStrategy { name: string; poly: ExitLeg; pf: ExitLeg; total_value: number; net: number; roi: number; }
export interface DetailLeg {
  platform: string; title: string; side: string; shares: number; avg_price: number | null;
  paid: number; best_ask: number; best_bid: number; at_ask: number; at_bid: number; ask_pnl: number; bid_pnl: number;
}
export interface StatItem { value: number | null; rank: number | null; total: number | null; label: string | null; }
export interface PairStats {
  poly_volume: StatItem; poly_liquidity: StatItem; poly_spread: StatItem; pf_liquidity: StatItem; pf_spread: StatItem;
}
export interface OrderBook { asks: [number, number][]; bids: [number, number][]; }
export interface HedgeRouteLeg {
  kind: string; fillable: number; exec_price: number; slippage_pct: number;
  fee: number; net_cost: number; pl_impact: number;
}
export interface HedgeRoute {
  action: string; platform: string; side: string; shares: number;
  current_shares: number; bought_at: number | null;
  market: HedgeRouteLeg; limit: HedgeRouteLeg;
  executable: boolean; note: string | null; lowest_cost: boolean; best_pl: boolean;
}
export interface Hedge {
  hedged: boolean; imbalance_shares: number; imbalance_pct: number; target_shares: number;
  overweight_platform: string; overweight_side: string; total_paid: number; routes: HedgeRoute[];
}
export interface PairExit {
  matched_market_id: number; title: string; poly_url: string; pf_url: string;
  est_ev: number; paid: number; bought_at: number; now_bid: number; ask_pnl: number; bid_pnl: number;
  strategies: ExitStrategy[]; best_index: number; legs: DetailLeg[]; combined: DetailLeg;
  stats: PairStats; poly_book: OrderBook; pf_book: OrderBook;
  hedge: Hedge | null;
}

export const fetchPortfolioSummary = () =>
  api.get<PortfolioSummary>("/portfolio/summary");

export const fetchPairExit = (mmId: number) =>
  api.get<PairExit>(`/portfolio/pairs/${mmId}/exit`);

export const refreshPositions = () => api.post("/portfolio/refresh");

export const addManualPosition = (body: {
  market_id: string;
  title: string;
  side: string;
  shares: number;
  total_cost: number;
}) => api.post("/portfolio/manual", body);

export const deletePosition = (id: number) => api.delete(`/portfolio/positions/${id}`);

export const markSold = (id: number, sold_shares: number, proceeds: number) =>
  api.post(`/portfolio/positions/${id}/sold`, { sold_shares, proceeds });

export const reopenPosition = (id: number) => api.post(`/portfolio/positions/${id}/reopen`);

export const searchPfMarkets = (q: string) =>
  api.get<PfMarket[]>("/portfolio/pf-markets", { params: { q } });

export const fetchWallets = () => api.get<{ wallets: string[] }>("/portfolio/wallets");

export const addWallet = (address: string) =>
  api.post<{ wallets: string[] }>("/portfolio/wallets", { address });

export const removeWallet = (address: string) =>
  api.delete<{ wallets: string[] }>(`/portfolio/wallets/${address}`);

export const fetchPnlSummary = () =>
  api.get<{ unrealized_pnl: number; realized_pnl: number; total_fees_paid: number; net_pnl: number }>(
    "/pnl/summary"
  );

export const fetchFeesSummary = () =>
  api.get<{ polymarket_fees: number; predictfun_fees: number; total_fees: number }>("/fees/summary");

export const fetchSettings = () =>
  api.get<{ settings: Record<string, string> }>("/settings");

export const updateSetting = (key: string, value: string) =>
  api.put("/settings", { key, value });
