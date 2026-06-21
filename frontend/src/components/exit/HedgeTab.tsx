import { HedgeRoute, HedgeRouteLeg, PairExit } from "../../api/client";

const money = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
const cents = (p: number) => `${(p * 100).toFixed(1)}c`;
const platName = (p: string) => (p === "polymarket" ? "Polymarket" : "Predict.fun");
const platColor = (p: string) => (p === "polymarket" ? "text-blue-400" : "text-purple-400");
const sideClass = (s: string) => (s === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300");

function ExecBlock({ leg }: { leg: HedgeRouteLeg }) {
  const isLimit = leg.kind === "limit";
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
      <div className="mb-2 text-[10px] font-bold uppercase tracking-wide text-gray-400">
        {isLimit ? "Limit (maker, est.)" : "Market (taker)"}
      </div>
      <div className="space-y-1 text-xs">
        <div className="flex justify-between"><span className="text-gray-500">Execution price</span><span className="font-mono text-gray-200">{cents(leg.exec_price)}</span></div>
        <div className="flex justify-between"><span className="text-gray-500">Fillable</span><span className="font-mono text-gray-200">{leg.fillable.toFixed(1)}</span></div>
        <div className="flex justify-between"><span className="text-gray-500">Slippage</span><span className="font-mono text-gray-200">{leg.slippage_pct.toFixed(2)}%</span></div>
        <div className="flex justify-between"><span className="text-gray-500">Fees</span><span className="font-mono text-orange-400">${leg.fee.toFixed(2)}</span></div>
        <div className="flex justify-between border-t border-gray-800 pt-1"><span className="text-gray-500">Net cost</span><span className={`font-mono ${leg.net_cost <= 0 ? "text-emerald-400" : "text-gray-200"}`}>{money(leg.net_cost)}</span></div>
        <div className="flex justify-between"><span className="text-gray-500">P/L impact</span><span className={`font-mono font-semibold ${leg.pl_impact >= 0 ? "text-emerald-400" : "text-red-400"}`}>{leg.pl_impact >= 0 ? "+" : ""}{money(leg.pl_impact)}</span></div>
      </div>
    </div>
  );
}

function RouteCard({ r }: { r: HedgeRoute }) {
  return (
    <div className={`rounded-xl border p-4 ${r.best_pl ? "border-emerald-700/50 bg-emerald-950/10" : "border-gray-800 bg-gray-900"}`}>
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-white">{r.action}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${sideClass(r.side)}`}>{r.side}</span>
        <span className="text-sm text-gray-400">on</span>
        <span className={`text-sm font-semibold ${platColor(r.platform)}`}>{platName(r.platform)}</span>
        {r.lowest_cost && <span className="rounded bg-blue-900 px-1.5 py-0.5 text-[10px] font-bold text-blue-200">LOWEST COST</span>}
        {r.best_pl && <span className="rounded bg-emerald-800 px-1.5 py-0.5 text-[10px] font-bold text-emerald-200">BEST P/L</span>}
      </div>
      <div className="mb-3 text-xs text-gray-500">
        {r.action === "SELL" ? "Sell" : "Buy"} {r.shares.toFixed(1)} {r.side} shares on {platName(r.platform)}.
        <span className="ml-2 text-gray-600">Current {Math.round(r.current_shares)} · bought at {r.bought_at != null ? cents(r.bought_at) : "—"}</span>
      </div>
      {r.executable ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <ExecBlock leg={r.market} />
          <ExecBlock leg={r.limit} />
        </div>
      ) : (
        <div className="rounded-lg border border-amber-900/40 bg-amber-950/20 px-3 py-5 text-center text-xs text-amber-400/80">
          {r.note ?? "No executable liquidity for this route right now."}
        </div>
      )}
    </div>
  );
}

function SummaryCell({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex-1 rounded-lg border border-gray-800 bg-gray-900 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`font-mono text-sm ${strong ? "font-semibold text-white" : "text-gray-200"}`}>{value}</div>
    </div>
  );
}

export default function HedgeTab({ exit }: { exit: PairExit }) {
  const h = exit.hedge;
  if (!h) return <div className="py-10 text-center text-gray-500">No pair data.</div>;
  if (h.hedged)
    return (
      <div className="rounded-xl border border-emerald-800/40 bg-emerald-950/10 p-6 text-center">
        <div className="text-2xl">✅</div>
        <div className="mt-2 text-sm font-semibold text-emerald-300">Fully hedged</div>
        <div className="mt-1 text-xs text-gray-500">Both legs hold equal shares ({Math.round(h.target_shares)}). Nothing to fix.</div>
      </div>
    );

  const polyShares = Math.round(exit.legs.find((l) => l.platform === "polymarket")?.shares ?? 0);
  const pfShares = Math.round(exit.legs.find((l) => l.platform === "predictfun")?.shares ?? 0);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-amber-700/40 bg-amber-950/20 p-4">
        <div className="text-sm font-semibold text-amber-300">⚠ Unhedged Position</div>
        <div className="mt-0.5 text-xs text-amber-200/80">
          There is a {h.imbalance_pct.toFixed(2)}% share imbalance ({polyShares} Polymarket vs {pfShares} Predict.fun).
        </div>
      </div>

      <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">↗ Route options</div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {h.routes.map((r) => <RouteCard key={r.action} r={r} />)}
      </div>

      <div className="flex flex-wrap gap-2 pt-1">
        <SummaryCell label="Imbalance Shares" value={h.imbalance_shares.toFixed(1)} />
        <SummaryCell label="Imbalance %" value={`${h.imbalance_pct.toFixed(2)}%`} />
        <SummaryCell label="Target Shares" value={h.target_shares.toFixed(1)} />
        <SummaryCell label="Overweight" value={platName(h.overweight_platform)} strong />
        <SummaryCell label="Total Paid (Both Sides)" value={money(h.total_paid)} />
      </div>
    </div>
  );
}
