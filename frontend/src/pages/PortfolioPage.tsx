import { useEffect, useState } from "react";
import {
  PositionLeg,
  addWallet,
  deletePosition,
  fetchWallets,
  refreshPositions,
  removeWallet,
} from "../api/client";
import { usePortfolioSummary } from "../hooks/usePortfolio";
import ArbPositionRow from "../components/ArbPositionRow";
import PositionDetail from "../components/PositionDetail";
import ClosingPairCard from "../components/ClosingPairCard";
import AddPfPositionModal from "../components/AddPfPositionModal";

const money = (n: number | null) => (n == null ? "—" : `$${n.toFixed(2)}`);

export default function PortfolioPage() {
  const { data, loading, reload } = usePortfolioSummary();
  const [wallets, setWallets] = useState<string[]>([]);
  const [showWallets, setShowWallets] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedPairId, setSelectedPairId] = useState<number | null>(null);

  const loadWallets = () => fetchWallets().then((r) => setWallets(r.data.wallets));
  useEffect(() => { loadWallets(); }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    await refreshPositions();
    setTimeout(() => { reload(); setRefreshing(false); }, 4000);
  };

  const { stats, pairs, closing, standalone } = data;
  const nothing = wallets.length === 0 && pairs.length === 0 && standalone.length === 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Portfolio</h1>
          <p className="mt-1 text-sm text-gray-400">Cross-exchange positions & arbitrage tracking</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={onRefresh} disabled={refreshing}
            className="rounded-lg bg-gray-800 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 disabled:opacity-50">
            {refreshing ? "Refreshing…" : "↻ Refresh positions"}
          </button>
          <button onClick={() => setShowWallets(true)}
            className="rounded-lg bg-blue-900/60 px-3 py-2 text-sm font-medium text-blue-300 hover:bg-blue-800">
            Connect Polymarket
          </button>
          <button onClick={() => setShowAdd(true)}
            className="rounded-lg bg-purple-900/60 px-3 py-2 text-sm font-medium text-purple-300 hover:bg-purple-800">
            + Add Predict.fun position
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Open EV" value={money(stats.open_ev)} accent={stats.open_ev >= 0 ? "text-emerald-400" : "text-red-400"} />
        <StatCard label="Deployed" value={money(stats.deployed)} accent="text-white" />
        <StatCard label="Payout" value={money(stats.max_payoff)} accent="text-blue-400" />
        <StatCard label="Active Pairs" value={String(stats.active_pairs)} accent="text-purple-400" />
      </div>

      {loading && nothing && <div className="py-16 text-center text-gray-500">Loading…</div>}

      {!loading && nothing && (
        <div className="rounded-xl border border-gray-800 bg-gray-900 py-16 text-center">
          <div className="text-lg font-semibold text-white">Connect your trading wallets</div>
          <p className="mx-auto mt-2 max-w-sm text-sm text-gray-400">
            Add your Polymarket wallet to auto-load positions, and add Predict.fun positions manually.
          </p>
          <button onClick={() => setShowWallets(true)}
            className="mt-4 rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600">
            Connect Polymarket
          </button>
        </div>
      )}

      {!nothing && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">
            Arbitrage Positions ({pairs.length})
          </h2>
          {pairs.length > 0 ? (
            <>
              <div className="overflow-x-auto rounded-xl border border-gray-800">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-900 text-left text-gray-400">
                      <th className="px-4 py-2 font-medium">Est EV</th>
                      <th className="px-4 py-2 font-medium">Market</th>
                      <th className="px-4 py-2 font-medium">Shares</th>
                      <th className="px-4 py-2 text-right font-medium">Bought At</th>
                      <th className="px-4 py-2 text-right font-medium">Now (bid)</th>
                      <th className="px-4 py-2 text-right font-medium">Paid</th>
                      <th className="px-4 py-2 text-right font-medium">Ask P&L</th>
                      <th className="px-4 py-2 text-right font-medium">Bid P&L</th>
                      <th className="px-2 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {pairs.map((p) => (
                      <ArbPositionRow
                        key={p.matched_market_id}
                        pair={p}
                        selected={selectedPairId === p.matched_market_id}
                        onSelect={() => setSelectedPairId(selectedPairId === p.matched_market_id ? null : p.matched_market_id)}
                        onRemoved={() => { setSelectedPairId(null); reload(); }}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
              {selectedPairId != null && (() => {
                const sp = pairs.find((p) => p.matched_market_id === selectedPairId);
                return sp ? (
                  <PositionDetail
                    matchedMarketId={selectedPairId}
                    polyLeg={sp.poly}
                    pfLeg={sp.pf}
                    onClose={() => setSelectedPairId(null)}
                    onChanged={reload}
                  />
                ) : null;
              })()}
            </>
          ) : (
            <div className="rounded-xl border border-dashed border-gray-800 bg-gray-900/40 px-4 py-8 text-center text-sm text-gray-500">
              No arbitrage positions yet. When you hold <span className="text-gray-300">opposite sides of the same market on both platforms</span>, the pair shows up here with its locked profit.
            </div>
          )}
        </section>
      )}

      {closing.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-amber-500/80">
            Closing Arbitrage ({closing.length})
          </h2>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            {closing.map((c) => <ClosingPairCard key={c.matched_market_id} closing={c} onChanged={reload} />)}
          </div>
        </section>
      )}

      {standalone.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">
            Positions ({standalone.length})
          </h2>
          <div className="overflow-x-auto rounded-xl border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-900 text-left text-gray-400">
                  <th className="px-4 py-2 font-medium">Platform</th>
                  <th className="px-4 py-2 font-medium">Market</th>
                  <th className="px-4 py-2 font-medium">Side</th>
                  <th className="px-4 py-2 text-right font-medium">Shares</th>
                  <th className="px-4 py-2 text-right font-medium">Avg</th>
                  <th className="px-4 py-2 text-right font-medium">Cost</th>
                  <th className="px-4 py-2 text-right font-medium">Value</th>
                  <th className="px-4 py-2 text-right font-medium">PnL</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {standalone.map((l) => <StandaloneRow key={`${l.platform}-${l.id}`} leg={l} onRemoved={reload} />)}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {showAdd && <AddPfPositionModal onClose={() => setShowAdd(false)} onAdded={reload} />}
      {showWallets && (
        <WalletModal
          wallets={wallets}
          onClose={() => setShowWallets(false)}
          onChange={async () => { await loadWallets(); reload(); }}
        />
      )}
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${accent}`}>{value}</div>
    </div>
  );
}

function StandaloneRow({ leg, onRemoved }: { leg: PositionLeg; onRemoved: () => void }) {
  const sideClass = leg.side === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300";
  const pnlClass = (leg.pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400";
  const remove = async () => { await deletePosition(leg.id); onRemoved(); };
  return (
    <tr className="border-t border-gray-800/40 hover:bg-gray-800/30">
      <td className="px-4 py-2 capitalize text-gray-300">{leg.platform === "polymarket" ? "Polymarket" : "Predict.fun"}</td>
      <td className="max-w-xs truncate px-4 py-2 text-white" title={leg.market_title}>{leg.market_title}</td>
      <td className="px-4 py-2"><span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${sideClass}`}>{leg.side}</span></td>
      <td className="px-4 py-2 text-right font-mono text-gray-300">{Math.round(leg.shares).toLocaleString()}</td>
      <td className="px-4 py-2 text-right font-mono text-gray-400">{leg.avg_price != null ? `$${leg.avg_price.toFixed(4)}` : "—"}</td>
      <td className="px-4 py-2 text-right font-mono text-gray-300">{money(leg.cost)}</td>
      <td className="px-4 py-2 text-right font-mono text-gray-300">{money(leg.current_value)}</td>
      <td className={`px-4 py-2 text-right font-mono ${leg.pnl != null ? pnlClass : "text-gray-500"}`}>{leg.pnl != null ? money(leg.pnl) : "—"}</td>
      <td className="px-2 py-2 text-right">
        {leg.source === "manual" && (
          <button onClick={remove} className="text-gray-600 hover:text-red-400" title="Remove">✕</button>
        )}
      </td>
    </tr>
  );
}

function WalletModal({ wallets, onClose, onChange }: { wallets: string[]; onClose: () => void; onChange: () => void }) {
  const [addr, setAddr] = useState("");
  const add = async () => { if (addr.trim()) { await addWallet(addr.trim()); setAddr(""); onChange(); } };
  const remove = async (w: string) => { await removeWallet(w); onChange(); };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl border border-gray-800 bg-gray-950 p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Polymarket wallets (read-only)</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">✕</button>
        </div>
        <div className="space-y-2">
          {wallets.map((w) => (
            <div key={w} className="flex items-center justify-between rounded-lg bg-gray-800 px-3 py-2 text-sm">
              <span className="truncate font-mono text-gray-300">{w}</span>
              <button onClick={() => remove(w)} className="ml-2 text-gray-500 hover:text-red-400">✕</button>
            </div>
          ))}
          {wallets.length === 0 && <div className="text-sm text-gray-600">No wallets connected.</div>}
        </div>
        <div className="mt-3 flex gap-2">
          <input value={addr} onChange={(e) => setAddr(e.target.value)} placeholder="0xYourWalletAddress"
            onKeyDown={(e) => e.key === "Enter" && add()}
            className="flex-1 rounded-lg bg-gray-800 px-3 py-2 text-sm text-white focus:outline-none" />
          <button onClick={add} className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600">Add</button>
        </div>
      </div>
    </div>
  );
}
