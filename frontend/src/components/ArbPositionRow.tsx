import { useEffect, useState } from "react";
import { ArbPair, PairExit, deletePosition, fetchPairExit } from "../api/client";

interface Props {
  pair: ArbPair;
  selected: boolean;
  onSelect: () => void;
  onRemoved: () => void;
}

const money = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
const pnlClass = (n: number) => (n >= 0 ? "text-emerald-400" : "text-red-400");

export default function ArbPositionRow({ pair, selected, onSelect, onRemoved }: Props) {
  const [exit, setExit] = useState<PairExit | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPairExit(pair.matched_market_id).then((r) => !cancelled && setExit(r.data)).catch(() => {});
    return () => { cancelled = true; };
  }, [pair.matched_market_id]);

  const remove = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Remove this arbitrage from your portfolio? (Deletes both legs.)")) return;
    await Promise.all([deletePosition(pair.poly.id), deletePosition(pair.pf.id)]);
    onRemoved();
  };

  const ev = exit?.est_ev ?? pair.ev;
  const paid = exit?.paid ?? pair.combined_cost;
  const boughtAt = exit?.bought_at;
  const nowBid = exit?.now_bid;
  const askPnl = exit?.ask_pnl;
  const bidPnl = exit?.bid_pnl;
  const roiAsk = paid ? ((askPnl ?? 0) / paid) * 100 : 0;
  const roiBid = paid ? ((bidPnl ?? 0) / paid) * 100 : 0;

  return (
    <tr
      onClick={onSelect}
      className={`cursor-pointer border-t transition-colors ${
        selected ? "bg-blue-950/50 border-blue-700/50" : "border-gray-800/40 hover:bg-gray-800/40"
      }`}
    >
      <td className="px-4 py-3">
        <div className={`font-mono font-bold ${pnlClass(ev)}`}>{money(ev)}</div>
        <div className="text-[10px] uppercase tracking-wide text-gray-600">Est EV</div>
      </td>
      <td className="px-4 py-3 max-w-sm">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium text-white" title={pair.title}>{pair.title}</span>
          {!pair.hedged && (
            <span
              title={pair.hedge_action ?? "Your two legs aren't equal size — part of the position is unhedged."}
              className="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400 ring-1 ring-amber-500/30"
            >
              ⚠ Not Hedged
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-xs">
        <div><span className="text-blue-400">Poly</span> <span className="text-gray-300">{Math.round(pair.poly.shares)}</span></div>
        <div><span className="text-purple-400">PF</span> <span className="text-gray-300">{Math.round(pair.pf.shares)}</span></div>
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">{boughtAt != null ? `${boughtAt.toFixed(0)}c` : "…"}</td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">{nowBid != null ? `${nowBid.toFixed(0)}c` : "…"}</td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">{money(paid)}</td>
      <td className="px-4 py-3 text-right font-mono">
        {askPnl != null ? (
          <div className={pnlClass(askPnl)}>{money(askPnl)}<div className="text-[10px]">({roiAsk >= 0 ? "+" : ""}{roiAsk.toFixed(2)}%)</div></div>
        ) : "…"}
      </td>
      <td className="px-4 py-3 text-right font-mono">
        {bidPnl != null ? (
          <div className={pnlClass(bidPnl)}>{money(bidPnl)}<div className="text-[10px]">({roiBid >= 0 ? "+" : ""}{roiBid.toFixed(2)}%)</div></div>
        ) : "…"}
      </td>
      <td className="px-2 py-3 text-right">
        <button onClick={remove} title="Remove" className="text-gray-600 hover:text-red-400">✕</button>
      </td>
    </tr>
  );
}
