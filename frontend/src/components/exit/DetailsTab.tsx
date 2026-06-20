import { DetailLeg, PairExit, StatItem } from "../../api/client";

const money = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
const cents = (p: number) => `${(p * 100).toFixed(0)}c`;
const pnlClass = (n: number) => (n >= 0 ? "text-emerald-400" : "text-red-400");
const sign = (n: number) => (n >= 0 ? "+" : "");

function fmtUsd(n: number | null): string {
  if (n == null) return "—";
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function LegRow({ leg, combined }: { leg: DetailLeg; combined?: boolean }) {
  const platform = leg.platform === "polymarket" ? "Polymarket" : leg.platform === "predictfun" ? "Predict.fun" : "Combined arbitrage pair";
  const sideClass = leg.side === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300";
  return (
    <tr className={`border-t border-gray-800/40 ${combined ? "bg-emerald-950/20" : ""}`}>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <span className={`text-sm ${combined ? "font-semibold text-emerald-300" : "text-white"}`}>{platform}</span>
          {!combined && <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${sideClass}`}>{leg.side}</span>}
          {!combined && <span className="text-xs text-gray-500">{Math.round(leg.shares)} sh</span>}
        </div>
        {!combined && <div className="max-w-xs truncate text-xs text-gray-600" title={leg.title}>{leg.title}</div>}
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">
        {leg.avg_price != null ? cents(leg.avg_price) : "—"} <span className="text-gray-600">→ {cents(leg.best_bid)}</span>
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">{money(leg.paid)}</td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">{money(leg.at_ask)}<div className="text-[10px] text-gray-600">@ {cents(leg.best_ask)}</div></td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">{money(leg.at_bid)}<div className="text-[10px] text-gray-600">@ {cents(leg.best_bid)}</div></td>
      <td className={`px-4 py-3 text-right font-mono ${pnlClass(leg.ask_pnl)}`}>{money(leg.ask_pnl)}<div className="text-[10px]">({sign(leg.ask_pnl / (leg.paid || 1) * 100)}{(leg.ask_pnl / (leg.paid || 1) * 100).toFixed(2)}%)</div></td>
      <td className={`px-4 py-3 text-right font-mono ${pnlClass(leg.bid_pnl)}`}>{money(leg.bid_pnl)}<div className="text-[10px]">({sign(leg.bid_pnl / (leg.paid || 1) * 100)}{(leg.bid_pnl / (leg.paid || 1) * 100).toFixed(2)}%)</div></td>
    </tr>
  );
}

function StatBar({ label, poly, pf, fmt }: { label: string; poly: StatItem | null; pf: StatItem | null; fmt: (n: number | null) => string }) {
  const cell = (s: StatItem | null, color: string, name: string) => {
    if (!s || s.value == null) return <div className="flex-1"><span className="text-gray-600">— {name}</span></div>;
    const pct = s.rank && s.total ? Math.max(2, 100 - (s.rank / s.total) * 100) : 0;
    return (
      <div className="flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-sm text-white">{fmt(s.value)}</span>
          <span className={`text-xs ${color}`}>{name}</span>
        </div>
        <div className="mt-1 h-1 rounded bg-gray-800"><div className={`h-1 rounded ${color === "text-blue-400" ? "bg-blue-500" : "bg-purple-500"}`} style={{ width: `${pct}%` }} /></div>
        {s.rank && <div className="mt-0.5 text-[10px] text-gray-500">#{s.rank}/{s.total} · {s.label}</div>}
      </div>
    );
  };
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-2 text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
      <div className="flex gap-6">
        {cell(poly, "text-blue-400", "Polymarket")}
        {cell(pf, "text-purple-400", "Predict.fun")}
      </div>
    </div>
  );
}

export default function DetailsTab({ exit }: { exit: PairExit }) {
  const s = exit.stats;
  const spreadFmt = (n: number | null) => (n == null ? "—" : `${(n * 100).toFixed(1)}c`);
  return (
    <div className="space-y-6">
      <div className="overflow-x-auto rounded-xl border border-gray-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-900 text-left text-gray-400">
              <th className="px-4 py-2 font-medium">Market</th>
              <th className="px-4 py-2 text-right font-medium">Bought → Now(bid)</th>
              <th className="px-4 py-2 text-right font-medium">Paid</th>
              <th className="px-4 py-2 text-right font-medium">@ best ask</th>
              <th className="px-4 py-2 text-right font-medium">@ best bid</th>
              <th className="px-4 py-2 text-right font-medium">Ask P&L</th>
              <th className="px-4 py-2 text-right font-medium">Bid P&L</th>
            </tr>
          </thead>
          <tbody>
            {exit.legs.map((l) => <LegRow key={l.platform} leg={l} />)}
            <LegRow leg={exit.combined} combined />
          </tbody>
        </table>
      </div>

      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Stats</div>
        <div className="grid grid-cols-1 gap-3">
          <StatBar label="Volume" poly={s.poly_volume} pf={null} fmt={fmtUsd} />
          <StatBar label="Book Liquidity" poly={s.poly_liquidity} pf={s.pf_liquidity} fmt={fmtUsd} />
          <StatBar label="Bid / Ask Spread" poly={s.poly_spread} pf={s.pf_spread} fmt={spreadFmt} />
        </div>
      </div>
    </div>
  );
}
