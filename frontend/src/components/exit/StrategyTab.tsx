import { ExitLeg, ExitStrategy, PairExit } from "../../api/client";

const money = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
const cents = (p: number) => `${(p * 100).toFixed(1)}c`;

function LegBlock({ leg, platform, side, color }: { leg: ExitLeg; platform: string; side: string; color: string }) {
  const isLimit = leg.kind === "limit";
  const sideClass = side === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300";
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className={`text-xs font-semibold ${color}`}>{platform}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${sideClass}`}>{side}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${isLimit ? "bg-blue-900 text-blue-300" : "bg-gray-700 text-gray-300"}`}>
          {isLimit ? "Limit" : "Market"}
        </span>
      </div>
      <div className="space-y-1 text-xs">
        <div className="flex justify-between"><span className="text-gray-500">{isLimit ? "Limit price" : "Sell avg"}</span><span className="font-mono text-gray-200">{cents(leg.avg_price)}</span></div>
        <div className="flex justify-between"><span className="text-gray-500">Shares</span><span className="font-mono text-gray-200">{Math.round(leg.shares).toLocaleString()}</span></div>
        {!isLimit && <div className="flex justify-between"><span className="text-gray-500">Fee</span><span className="font-mono text-orange-400">-${leg.fee.toFixed(2)}</span></div>}
        <div className="flex justify-between border-t border-gray-800 pt-1"><span className="text-gray-500">Value</span><span className="font-mono font-semibold text-white">{money(leg.value)}{isLimit && <span className="text-gray-600"> est</span>}</span></div>
      </div>
    </div>
  );
}

function StrategyCard({ s, best, polySide, pfSide }: { s: ExitStrategy; best: boolean; polySide: string; pfSide: string }) {
  const combined = s.poly.avg_price + s.pf.avg_price;
  return (
    <div className={`rounded-xl border p-4 ${best ? "border-emerald-700/60 bg-emerald-950/20" : "border-gray-800 bg-gray-900"}`}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="text-sm font-semibold text-white">
          {s.name}
          {best && <span className="ml-2 rounded bg-emerald-800 px-1.5 py-0.5 text-[10px] font-bold text-emerald-200">BEST</span>}
        </div>
        <div className="shrink-0 text-right">
          <div className={`font-mono font-bold ${s.net >= 0 ? "text-emerald-400" : "text-red-400"}`}>{money(s.net)}</div>
          <div className="text-[10px] text-gray-500">ROI {s.roi >= 0 ? "+" : ""}{s.roi.toFixed(2)}%</div>
        </div>
      </div>
      <div className="mb-3 rounded-lg bg-gray-800/60 px-3 py-2">
        <div className="text-[10px] uppercase tracking-wide text-gray-500">Combined sell price</div>
        <div className="font-mono text-sm text-white">{cents(combined)} <span className="text-gray-600 text-xs">= {money(s.total_value)}</span></div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <LegBlock leg={s.poly} platform="Polymarket" side={polySide} color="text-blue-400" />
        <LegBlock leg={s.pf} platform="Predict.fun" side={pfSide} color="text-purple-400" />
      </div>
    </div>
  );
}

export default function StrategyTab({ exit }: { exit: PairExit }) {
  const polySide = exit.legs.find((l) => l.platform === "polymarket")?.side ?? "";
  const pfSide = exit.legs.find((l) => l.platform === "predictfun")?.side ?? "";
  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">Exit the full position. Limit (maker) values are estimated (assume a fill at best ask); market (taker) values walk the live book. All values include fees.</p>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {exit.strategies.map((s, i) => (
          <StrategyCard key={s.name} s={s} best={i === exit.best_index} polySide={polySide} pfSide={pfSide} />
        ))}
      </div>
    </div>
  );
}
