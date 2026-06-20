import { ArbPair, PositionLeg, deletePosition } from "../api/client";

const money = (n: number | null) => (n == null ? "—" : `$${n.toFixed(2)}`);

function Leg({ leg, label, color }: { leg: PositionLeg; label: string; color: string }) {
  const sideClass = leg.side === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300";
  const pnlClass = (leg.pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400";
  return (
    <div className="flex-1 rounded-lg border border-gray-800 bg-gray-900/60 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className={`text-xs font-semibold ${color}`}>{label}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${sideClass}`}>{leg.side}</span>
      </div>
      <div className="space-y-1 text-xs">
        <Row label="Shares" value={Math.round(leg.shares).toLocaleString()} />
        <Row label="Avg price" value={leg.avg_price != null ? `$${leg.avg_price.toFixed(4)}` : "—"} />
        <Row label="Cost" value={money(leg.cost)} />
        <Row label="Value" value={money(leg.current_value)} />
        <Row label="PnL" value={leg.pnl != null ? money(leg.pnl) : "—"} valueClass={leg.pnl != null ? pnlClass : ""} />
      </div>
    </div>
  );
}

function Row({ label, value, valueClass = "text-gray-200" }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-500">{label}</span>
      <span className={`font-mono ${valueClass}`}>{value}</span>
    </div>
  );
}

export default function ArbPairCard({ pair, onRemoved }: { pair: ArbPair; onRemoved?: () => void }) {
  const remove = async () => {
    if (!confirm("Remove this arbitrage from your portfolio? (Deletes both legs.)")) return;
    await Promise.all([deletePosition(pair.poly.id), deletePosition(pair.pf.id)]);
    onRemoved?.();
  };
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <h3 className="truncate text-sm font-semibold text-white" title={pair.title}>{pair.title}</h3>
        <div className="flex shrink-0 items-center gap-3">
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wide text-gray-500">Open EV</div>
            <div className={`font-mono font-bold ${pair.ev >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {money(pair.ev)}
            </div>
          </div>
          <button onClick={remove} title="Remove arbitrage"
            className="rounded p-1 text-gray-600 hover:bg-gray-800 hover:text-red-400">✕</button>
        </div>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Leg leg={pair.poly} label="Polymarket" color="text-blue-400" />
        <Leg leg={pair.pf} label="Predict.fun" color="text-purple-400" />
      </div>
      <div className="mt-3 flex justify-between border-t border-gray-800 pt-2 text-xs text-gray-400">
        <span>Combined cost <span className="font-mono text-gray-200">{money(pair.combined_cost)}</span></span>
        <span>Payout <span className="font-mono text-gray-200">{money(pair.max_payoff)}</span></span>
      </div>
    </div>
  );
}
