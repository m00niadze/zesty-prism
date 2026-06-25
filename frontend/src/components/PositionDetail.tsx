import { useEffect, useState } from "react";
import { PairExit, PositionLeg, fetchPairExit } from "../api/client";
import DetailsTab from "./exit/DetailsTab";
import StrategyTab from "./exit/StrategyTab";
import OrderBookTab from "./exit/OrderBookTab";
import HedgeTab from "./exit/HedgeTab";
import SalesPanel from "./SalesPanel";

type Tab = "details" | "strategy" | "sales" | "hedge" | "orderbook";
const money = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
const plat = (p: string) => (p === "polymarket" ? "Polymarket" : "Predict.fun");

interface Props {
  matchedMarketId: number;
  polyLeg: PositionLeg;
  pfLeg: PositionLeg;
  onClose: () => void;
  onChanged: () => void;
}

export default function PositionDetail({ matchedMarketId, polyLeg, pfLeg, onClose, onChanged }: Props) {
  const pending =
    polyLeg.sales.filter((s) => s.proceeds === null).length +
    pfLeg.sales.filter((s) => s.proceeds === null).length;
  // If a sale is waiting for its cash amount, open straight to the Sales tab.
  const [tab, setTab] = useState<Tab>(pending > 0 ? "sales" : "strategy");
  const [exit, setExit] = useState<PairExit | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => fetchPairExit(matchedMarketId)
      .then((r) => !cancelled && (setExit(r.data), setErr(null)))
      .catch((e) => !cancelled && setErr(e?.response?.status === 404 ? "Position no longer open." : e.message));
    load();
    const t = setInterval(load, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, [matchedMarketId]);

  const best = exit ? exit.strategies[exit.best_index] : null;
  const tabs: Tab[] = ["details", "strategy", "sales", ...(exit?.hedge && !exit.hedge.hedged ? ["hedge" as Tab] : []), "orderbook"];

  return (
    <div className="mt-4 rounded-xl border border-gray-700 bg-gray-950">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 p-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">{exit?.title ?? "Loading…"}</span>
            {exit?.hedge && !exit.hedge.hedged && (
              <span className="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400 ring-1 ring-amber-500/30">⚠ Not Hedged</span>
            )}
          </div>
          {exit && (
            <div className="mt-1 flex flex-wrap items-center gap-3 text-xs">
              <a href={exit.poly_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">Polymarket ↗</a>
              <a href={exit.pf_url} target="_blank" rel="noreferrer" className="text-purple-400 hover:underline">Predict.fun ↗</a>
              {best && <span className="text-gray-400">Best exit: <span className={best.net >= 0 ? "text-emerald-400" : "text-red-400"}>{money(best.net)}</span> ({best.name})</span>}
              <button onClick={() => setTab("sales")} className="rounded bg-emerald-900/50 px-2 py-0.5 text-emerald-300 hover:bg-emerald-800">💵 Record a sale</button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1">
          {tabs.map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`rounded px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                tab === t ? "bg-gray-800 text-white" : "text-gray-400 hover:text-white"
              }`}>
              {t === "orderbook" ? "Order Book" : t}
              {t === "hedge" && (
                <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-400 align-middle" />
              )}
              {t === "sales" && pending > 0 && (
                <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-400 align-middle" />
              )}
            </button>
          ))}
          <button onClick={onClose} className="ml-2 rounded p-1.5 text-gray-400 hover:bg-gray-800 hover:text-white" title="Close">✕</button>
        </div>
      </div>
      <div className="p-4">
        {tab === "sales" ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[polyLeg, pfLeg].map((leg) => (
              <div key={leg.id}>
                <div className="mb-1 text-xs text-gray-400">
                  {plat(leg.platform)} <span className="font-semibold text-gray-200">{leg.side}</span>
                  {" · "}holding {Math.round(leg.shares)} sh
                </div>
                <SalesPanel legId={leg.id} label={`${plat(leg.platform)} ${leg.side}`} sales={leg.sales} onChanged={onChanged} />
              </div>
            ))}
          </div>
        ) : err ? (
          <div className="rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">{err}</div>
        ) : !exit ? (
          <div className="py-10 text-center text-gray-500">Loading order books…</div>
        ) : tab === "details" ? (
          <DetailsTab exit={exit} />
        ) : tab === "strategy" ? (
          <StrategyTab exit={exit} />
        ) : tab === "hedge" ? (
          <HedgeTab exit={exit} />
        ) : (
          <OrderBookTab exit={exit} />
        )}
      </div>
    </div>
  );
}
