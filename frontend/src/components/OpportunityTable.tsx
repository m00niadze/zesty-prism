import { useState } from "react";
import { ArbOpportunity } from "../api/client";

interface Props {
  opportunities: ArbOpportunity[];
  selectedId?: number | null;
  onSelect?: (o: ArbOpportunity) => void;
}

type SortKey = "net_profit_pct" | "max_profit_usd" | "max_wager_usd";

function profitColor(pct: number) {
  if (pct >= 2) return "text-emerald-400";
  if (pct >= 0.5) return "text-yellow-400";
  return "text-gray-400";
}

function rowBg(pct: number, selected: boolean) {
  if (selected) return "bg-blue-950/60 border-blue-700/50";
  if (pct >= 2) return "bg-emerald-950/40 border-emerald-800/30";
  if (pct >= 0.5) return "bg-yellow-950/30 border-yellow-800/30";
  return "border-gray-800/30";
}

export default function OpportunityTable({ opportunities, selectedId, onSelect }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("max_profit_usd");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  if (opportunities.length === 0) {
    return (
      <div className="text-center py-16 text-gray-500">
        No taker-profitable arbitrage right now. Scanning continuously…
      </div>
    );
  }

  const sorted = [...opportunities].sort((a, b) => {
    const diff = a[sortKey] - b[sortKey];
    return sortDir === "desc" ? -diff : diff;
  });

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const arrow = (key: SortKey) => (sortKey === key ? (sortDir === "desc" ? " ↓" : " ↑") : "");
  const sortableTh = (key: SortKey, label: string) => (
    <th
      className={`px-4 py-3 font-medium text-right cursor-pointer select-none hover:text-white transition-colors ${
        sortKey === key ? "text-blue-400" : ""
      }`}
      onClick={() => onSort(key)}
    >
      {label}
      <span className="text-blue-400">{arrow(key)}</span>
    </th>
  );

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-900 text-gray-400 text-left">
            <th className="px-4 py-3 font-medium">Market</th>
            <th className="px-4 py-3 font-medium">Strategy</th>
            <th className="px-4 py-3 font-medium text-right">PM Avg</th>
            <th className="px-4 py-3 font-medium text-right">PF Avg</th>
            {sortableTh("net_profit_pct", "ROI (at size)")}
            {sortableTh("max_profit_usd", "Max Profit")}
            {sortableTh("max_wager_usd", "Max Size")}
          </tr>
        </thead>
        <tbody>
          {sorted.map((o) => (
            <tr
              key={o.id}
              onClick={() => onSelect?.(o)}
              className={`cursor-pointer border-t ${rowBg(o.net_profit_pct, o.id === selectedId)} hover:bg-gray-800/60 transition-colors`}
            >
              <td className="px-4 py-3 max-w-xs">
                <div className="truncate font-medium text-white" title={o.poly_title}>
                  {o.poly_title}
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  <a
                    href={`https://polymarket.com/event/${o.poly_slug}`}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center rounded bg-blue-900/50 px-2 py-0.5 text-xs font-medium text-blue-300 hover:bg-blue-800 transition-colors"
                  >
                    Polymarket ↗
                  </a>
                  <a
                    href={`https://predict.fun/market/${o.pf_slug}`}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center rounded bg-purple-900/50 px-2 py-0.5 text-xs font-medium text-purple-300 hover:bg-purple-800 transition-colors"
                  >
                    Predict.fun ↗
                  </a>
                </div>
              </td>
              <td className="px-4 py-3">
                <span className="inline-flex items-center gap-1">
                  <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
                    o.poly_side === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300"
                  }`}>
                    {o.poly_side}
                  </span>
                  <span className="text-gray-600 text-xs">PM</span>
                  <span className="text-gray-600">/</span>
                  <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
                    o.pf_side === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300"
                  }`}>
                    {o.pf_side}
                  </span>
                  <span className="text-gray-600 text-xs">PF</span>
                </span>
              </td>
              <td className="px-4 py-3 text-right font-mono text-gray-300">
                ${o.poly_price.toFixed(4)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-gray-300">
                ${o.pf_price.toFixed(4)}
              </td>
              <td className={`px-4 py-3 text-right font-mono font-bold ${profitColor(o.net_profit_pct)}`}>
                {o.net_profit_pct.toFixed(2)}%
                <div className="text-[10px] font-normal text-gray-500">up to {o.net_pct_top.toFixed(2)}%</div>
              </td>
              <td className="px-4 py-3 text-right font-mono font-bold text-emerald-400">
                ${o.max_profit_usd.toFixed(2)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-gray-300">
                ${o.max_wager_usd.toFixed(0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
