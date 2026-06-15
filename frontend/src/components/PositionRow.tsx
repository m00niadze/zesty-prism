import { Position } from "../api/client";

interface Props {
  position: Position;
}

export default function PositionRow({ position: p }: Props) {
  const pnl = p.unrealized_pnl;
  const pnlColor = pnl === null ? "text-gray-400" : pnl >= 0 ? "text-emerald-400" : "text-red-400";
  const pnlStr = pnl === null ? "—" : `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`;

  return (
    <div className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-gray-800/50 transition-colors">
      <div className="flex items-center gap-3 min-w-0">
        <span
          className={`text-xs font-bold px-2 py-0.5 rounded ${
            p.side === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300"
          }`}
        >
          {p.side}
        </span>
        <span className="text-gray-200 truncate text-sm">{p.market_title}</span>
      </div>
      <div className="flex items-center gap-6 text-sm shrink-0">
        <span className="text-gray-400 font-mono">{p.size.toFixed(2)} sh</span>
        <span className="text-gray-500 font-mono">
          @ ${(p.avg_entry_price ?? 0).toFixed(4)}
        </span>
        <span className="text-gray-400 font-mono">
          now ${(p.current_price ?? 0).toFixed(4)}
        </span>
        <span className={`font-mono font-semibold w-20 text-right ${pnlColor}`}>{pnlStr}</span>
      </div>
    </div>
  );
}
