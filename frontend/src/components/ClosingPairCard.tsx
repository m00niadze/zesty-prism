import { ClosingLeg, ClosingPair, deletePosition, reopenPosition } from "../api/client";
import SalesPanel from "./SalesPanel";

const money = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
const plat = (p: string) => (p === "polymarket" ? "Polymarket" : "Predict.fun");
const sideClass = (s: string) => (s === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300");

function LegBlock({ leg, onChanged }: { leg: ClosingLeg; onChanged: () => void }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-gray-500">{plat(leg.platform)}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${sideClass(leg.side)}`}>{leg.side}</span>
        <span className="text-gray-600">{Math.round(leg.total_shares)} sh total</span>
        {leg.open_shares > 0.5 && (
          <span className="text-gray-400">· open {Math.round(leg.open_shares)} sh → <span className="font-mono">{money(leg.open_value)}</span></span>
        )}
      </div>
      <SalesPanel legId={leg.id} label={`${plat(leg.platform)} ${leg.side}`} sales={leg.sales} onChanged={onChanged} />
    </div>
  );
}

export default function ClosingPairCard({ closing, onChanged }: { closing: ClosingPair; onChanged: () => void }) {
  const pnl = closing.exit_now_pnl;
  const pendingCash = closing.legs.some((l) => l.sales.some((s) => s.proceeds === null));

  const done = async () => {
    if (!confirm("Remove this closing position? (Deletes both legs.)")) return;
    await Promise.all(closing.legs.map((l) => deletePosition(l.id)));
    onChanged();
  };
  const undo = async () => {
    await Promise.all(closing.legs.filter((l) => l.sold_shares > 0).map((l) => reopenPosition(l.id)));
    onChanged();
  };

  return (
    <div className="rounded-xl border border-gray-700 bg-gray-900/40 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-white" title={closing.title}>{closing.title}</span>
            <span className="shrink-0 rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300 ring-1 ring-emerald-500/30">
              ✓ Closed · settling
            </span>
          </div>
          <div className="text-[10px] uppercase tracking-wide text-gray-500">One leg sold · remainder still open</div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`font-mono text-lg font-bold ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>{money(pnl)}</div>
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Full P&L (live)</div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {closing.legs.map((l) => <LegBlock key={l.id} leg={l} onChanged={onChanged} />)}
      </div>

      {pendingCash && <div className="mt-2 text-[10px] text-amber-500/80">A sale is missing its cash amount — hit “💵 Enter amount” so it counts toward your realized P&amp;L.</div>}

      <div className="mt-3 flex items-center justify-between border-t border-gray-800 pt-2 text-xs text-gray-500">
        <span>Paid <span className="font-mono text-gray-300">{money(closing.paid)}</span> · realized <span className="font-mono text-gray-300">{money(closing.realized)}</span> + remaining <span className="font-mono text-gray-300">{money(closing.open_value)}</span></span>
        <div className="flex gap-2">
          <button onClick={undo} className="rounded bg-gray-800 px-2 py-1 text-gray-400 hover:bg-gray-700">Undo sold</button>
          <button onClick={done} className="rounded bg-gray-800 px-2 py-1 text-gray-300 hover:bg-gray-700">Remove</button>
        </div>
      </div>
    </div>
  );
}
