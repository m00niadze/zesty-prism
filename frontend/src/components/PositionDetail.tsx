import { useEffect, useState } from "react";
import { PairExit, fetchPairExit, markSold } from "../api/client";
import DetailsTab from "./exit/DetailsTab";
import StrategyTab from "./exit/StrategyTab";
import OrderBookTab from "./exit/OrderBookTab";
import HedgeTab from "./exit/HedgeTab";

type Tab = "details" | "strategy" | "hedge" | "orderbook";
const money = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;

interface Props {
  matchedMarketId: number;
  pfLegId: number;
  pfShares: number;
  onClose: () => void;
  onChanged: () => void;
}

export default function PositionDetail({ matchedMarketId, pfLegId, pfShares, onClose, onChanged }: Props) {
  const [tab, setTab] = useState<Tab>("strategy");
  const [exit, setExit] = useState<PairExit | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [marking, setMarking] = useState(false);
  const [soldShares, setSoldShares] = useState(String(Math.round(pfShares)));
  const [proceeds, setProceeds] = useState("");

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

  const submitSold = async () => {
    const sh = Number(soldShares), n = Number(proceeds);
    if (isNaN(sh) || isNaN(n)) return;
    await markSold(pfLegId, sh, n);
    setMarking(false);
    setProceeds("");
    onChanged();
    onClose();
  };

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
              {marking ? (
                <span className="inline-flex flex-wrap items-center gap-1">
                  <span className="text-gray-500">PF sold</span>
                  <input autoFocus value={soldShares} onChange={(e) => setSoldShares(e.target.value)} placeholder="shares"
                    className="w-14 rounded bg-gray-800 px-1.5 py-0.5 text-white" />
                  <span className="text-gray-500">sh for $</span>
                  <input value={proceeds} onChange={(e) => setProceeds(e.target.value)} placeholder="proceeds"
                    className="w-16 rounded bg-gray-800 px-1.5 py-0.5 text-white" />
                  <button onClick={submitSold} className="text-emerald-400">✓</button>
                  <button onClick={() => setMarking(false)} className="text-gray-500">✕</button>
                </span>
              ) : (
                <button onClick={() => setMarking(true)} className="rounded bg-amber-900/50 px-2 py-0.5 text-amber-300 hover:bg-amber-800">Mark PF leg sold</button>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1">
          {(["details", "strategy", ...(exit?.hedge && !exit.hedge.hedged ? ["hedge"] : []), "orderbook"] as Tab[]).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`rounded px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                tab === t ? "bg-gray-800 text-white" : "text-gray-400 hover:text-white"
              }`}>
              {t === "orderbook" ? "Order Book" : t}
              {t === "hedge" && (
                <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-amber-400 align-middle" />
              )}
            </button>
          ))}
          <button onClick={onClose} className="ml-2 rounded p-1.5 text-gray-400 hover:bg-gray-800 hover:text-white" title="Close">✕</button>
        </div>
      </div>
      <div className="p-4">
        {err && <div className="rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">{err}</div>}
        {!exit && !err && <div className="py-10 text-center text-gray-500">Loading order books…</div>}
        {exit && tab === "details" && <DetailsTab exit={exit} />}
        {exit && tab === "strategy" && <StrategyTab exit={exit} />}
        {exit && tab === "hedge" && <HedgeTab exit={exit} />}
        {exit && tab === "orderbook" && <OrderBookTab exit={exit} />}
      </div>
    </div>
  );
}
