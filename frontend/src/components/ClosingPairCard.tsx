import { useState } from "react";
import { ClosingLeg, ClosingPair, deletePosition, markSold, reopenPosition } from "../api/client";

const money = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
const plat = (p: string) => (p === "polymarket" ? "Polymarket" : "Predict.fun");
const sideClass = (s: string) => (s === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300");

function LegRow({ leg, onChanged }: { leg: ClosingLeg; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [sh, setSh] = useState(String(Math.round(leg.sold_shares)));
  const [pr, setPr] = useState(String(leg.sold_proceeds.toFixed(2)));

  const save = async () => {
    const shares = Number(sh), proceeds = Number(pr);
    if (!isNaN(shares) && !isNaN(proceeds)) await markSold(leg.id, shares, proceeds);
    setEditing(false);
    onChanged();
  };

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 text-xs">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-gray-500">{plat(leg.platform)}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${sideClass(leg.side)}`}>{leg.side}</span>
        <span className="text-gray-600">{Math.round(leg.total_shares)} sh total</span>
      </div>
      {editing ? (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-gray-500">sold</span>
          <input value={sh} onChange={(e) => setSh(e.target.value)} className="w-14 rounded bg-gray-800 px-1.5 py-0.5 text-white" /> sh for $
          <input value={pr} onChange={(e) => setPr(e.target.value)} className="w-16 rounded bg-gray-800 px-1.5 py-0.5 text-white" />
          <button onClick={save} className="text-emerald-400">✓</button>
          <button onClick={() => setEditing(false)} className="text-gray-500">✕</button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <span className="text-emerald-400">sold {Math.round(leg.sold_shares)} sh → <span className="font-mono">{money(leg.sold_proceeds)}</span></span>
          <span className="text-gray-400">open {Math.round(leg.open_shares)} sh → <span className="font-mono">{money(leg.open_value)}</span></span>
          <button onClick={() => setEditing(true)} className="text-[10px] text-blue-400 hover:underline">edit</button>
        </div>
      )}
    </div>
  );
}

export default function ClosingPairCard({ closing, onChanged }: { closing: ClosingPair; onChanged: () => void }) {
  const pnl = closing.exit_now_pnl;
  const auto = closing.legs.some((l) => l.platform === "polymarket" && l.sold_shares > 0);

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
    <div className="rounded-xl border border-amber-800/40 bg-amber-950/10 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-white" title={closing.title}>{closing.title}</span>
            {!closing.hedged && (
              <span
                title={closing.hedge_action ?? "Your open shares are unequal — you're exposed on the difference."}
                className="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400 ring-1 ring-amber-500/30"
              >
                ⚠ Not Hedged
              </span>
            )}
          </div>
          <div className="text-[10px] uppercase tracking-wide text-amber-500/80">Closing · partly sold</div>
          {!closing.hedged && closing.hedge_action && (
            <div className="mt-0.5 text-[11px] text-amber-400/80">
              {Math.round(closing.imbalance_shares)} shares unhedged · {closing.hedge_action}
            </div>
          )}
        </div>
        <div className="shrink-0 text-right">
          <div className={`font-mono text-lg font-bold ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>{money(pnl)}</div>
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Exit now P&L</div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {closing.legs.map((l) => <LegRow key={l.id} leg={l} onChanged={onChanged} />)}
      </div>

      {auto && <div className="mt-2 text-[10px] text-amber-500/70">Polymarket sale auto-estimated — hit “edit” to set your exact shares &amp; fill.</div>}

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
