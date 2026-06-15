import { useEffect, useMemo, useRef, useState } from "react";
import { useCalculator } from "../hooks/useCalculator";
import {
  Ladder,
  TakerResult,
  computeAtShares,
  computeAtWager,
  computeMax,
  solveWagerForRoi,
} from "../lib/arbMath";

interface Props {
  opportunityId: number;
  titleFallback?: string;
  onClose: () => void;
}

const money = (n: number) => `$${n.toFixed(2)}`;
const ROI_STEP = 0.1;

export default function CalculatorDrawer({ opportunityId, titleFallback, onClose }: Props) {
  const { data, loading, error } = useCalculator(opportunityId);
  const [wager, setWager] = useState(0);
  const initFor = useRef<number | null>(null);
  const title = data?.poly.title ?? titleFallback ?? "Loading…";

  // Esc to close
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const polyFeeRate = data ? data.poly.fee_bps / 10000 : 0;
  const pfFeeRate = data ? data.pf.fee_bps / 10000 : 0;
  const polyLadder: Ladder = data ? data.poly.ladder : [];
  const pfLadder: Ladder = data ? data.pf.ladder : [];

  const max = useMemo<TakerResult>(
    () => computeMax(polyLadder, pfLadder, polyFeeRate, pfFeeRate),
    [polyLadder, pfLadder, polyFeeRate, pfFeeRate]
  );

  // Default wager to Max when a new opportunity's data arrives; clamp on refresh.
  useEffect(() => {
    if (!data) return;
    if (initFor.current !== opportunityId) {
      initFor.current = opportunityId;
      setWager(max.wager);
    } else {
      setWager((w) => Math.min(w, max.wager));
    }
  }, [data, opportunityId, max.wager]);

  const res = useMemo<TakerResult>(
    () => computeAtWager(polyLadder, pfLadder, polyFeeRate, pfFeeRate, wager),
    [polyLadder, pfLadder, polyFeeRate, pfFeeRate, wager]
  );

  const profitable = max.shares > 0 && max.profit > 0;

  const setRoiBy = (delta: number) => {
    const target = Math.max(0, res.netPct + delta);
    setWager(solveWagerForRoi(polyLadder, pfLadder, polyFeeRate, pfFeeRate, target, max.wager));
  };

  const setShares = (s: number) => {
    const clamped = Math.min(Math.max(0, s), max.shares);
    setWager(computeAtShares(polyLadder, pfLadder, polyFeeRate, pfFeeRate, clamped).wager);
  };

  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-gray-800 bg-gray-950 shadow-2xl">
      <div className="flex items-start justify-between gap-3 border-b border-gray-800 p-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500">Arb Calculator</div>
          <h2 className="mt-0.5 text-sm font-semibold text-white">{title}</h2>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-gray-400 hover:bg-gray-800 hover:text-white"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      {loading && !data && <div className="p-8 text-center text-gray-500">Loading order books…</div>}
      {error && <div className="m-4 rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">{error}</div>}

      {data && !profitable && (
        <div className="m-4 rounded-lg border border-yellow-800 bg-yellow-950/40 px-4 py-3 text-sm text-yellow-300">
          Not profitable at any size right now — the order book has moved. This row will drop off shortly.
        </div>
      )}

      {data && profitable && (
        <div className="space-y-5 p-4">
          {/* Wager controls */}
          <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
            <div className="mb-2 flex items-center justify-between text-xs">
              <span className="text-gray-400">
                Wager Amount <span className="text-gray-600">(Max {money(max.wager)})</span>
              </span>
              <span className="text-gray-400">Target ROI</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex flex-1 items-center rounded-lg bg-gray-800 px-3 py-2">
                <span className="text-gray-500">$</span>
                <input
                  type="number"
                  value={Number.isFinite(wager) ? Number(wager.toFixed(2)) : 0}
                  min={0}
                  max={max.wager}
                  onChange={(e) => setWager(Math.min(Math.max(0, Number(e.target.value)), max.wager))}
                  className="w-full bg-transparent pl-2 text-lg font-semibold text-white focus:outline-none"
                />
              </div>
              <div className="flex items-center gap-1 rounded-lg bg-gray-800 px-2 py-1">
                <button onClick={() => setRoiBy(-ROI_STEP)} className="px-2 text-lg text-gray-300 hover:text-white">−</button>
                <span className="w-14 text-center text-sm font-semibold text-blue-400">{res.netPct.toFixed(2)}%</span>
                <button onClick={() => setRoiBy(ROI_STEP)} className="px-2 text-lg text-gray-300 hover:text-white">+</button>
              </div>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <div className="flex flex-1 items-center justify-between rounded-lg bg-gray-800 px-3 py-2">
                <span className="text-xs text-gray-500">Shares</span>
                <input
                  type="number"
                  value={Math.round(res.shares)}
                  min={0}
                  max={Math.floor(max.shares)}
                  onChange={(e) => setShares(Number(e.target.value))}
                  className="w-24 bg-transparent text-right text-sm font-semibold text-white focus:outline-none"
                />
              </div>
              <span className="text-xs text-gray-600">/ max {Math.floor(max.shares).toLocaleString()}</span>
            </div>
            <div className="mt-2 flex gap-2">
              {[0.25, 0.5, 0.75, 0.9].map((p) => (
                <button
                  key={p}
                  onClick={() => setWager(max.wager * p)}
                  className="flex-1 rounded-md bg-gray-800 py-1 text-xs text-gray-300 hover:bg-gray-700"
                >
                  {p * 100}%
                </button>
              ))}
              <button
                onClick={() => setWager(max.wager)}
                className="flex-1 rounded-md bg-blue-900/60 py-1 text-xs font-medium text-blue-300 hover:bg-blue-800"
              >
                Max
              </button>
            </div>
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-3">
            <SummaryCard label="Expected Profit" value={money(res.profit)} accent="text-emerald-400" />
            <SummaryCard label="ROI" value={`${res.netPct.toFixed(2)}%`} accent="text-blue-400" />
            <SummaryCard label="Cost Basis" value={money(res.wager)} accent="text-white" />
          </div>

          {/* Legs */}
          <div className="grid grid-cols-2 gap-3">
            <LegCard
              platform="Polymarket"
              url={data.poly.url}
              side={data.poly.side}
              feePctLabel={`${(res.polyCost > 0 ? (res.polyFee / res.polyCost) * 100 : 0).toFixed(2)}%`}
              avg={res.polyAvg}
              ceiling={res.polyCeiling}
              fee={res.polyFee}
              cost={res.polyCost}
              shares={res.shares}
            />
            <LegCard
              platform="Predict.fun"
              url={data.pf.url}
              side={data.pf.side}
              feePctLabel={`${(res.pfCost > 0 ? (res.pfFee / res.pfCost) * 100 : 0).toFixed(2)}%`}
              avg={res.pfAvg}
              ceiling={res.pfCeiling}
              fee={res.pfFee}
              cost={res.pfCost}
              shares={res.shares}
            />
          </div>

          {/* Payout */}
          <div className="flex items-center justify-between rounded-xl border border-gray-800 bg-gray-900 px-4 py-3">
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500">Payout (at resolution)</div>
              <div className="text-xs text-gray-500">{Math.round(res.shares)} shares × $1</div>
            </div>
            <div className="text-xl font-bold text-white">{money(res.payout)}</div>
          </div>
          <p className="text-center text-xs text-gray-600">
            Taker / market-buy prices, walking the live order book. Total capital out: {money(res.wager + res.fees)}.
          </p>
        </div>
      )}
    </aside>
  );
}

function SummaryCard({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-3 text-center">
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`mt-1 text-lg font-bold ${accent}`}>{value}</div>
    </div>
  );
}

function LegCard(props: {
  platform: string;
  url: string;
  side: string;
  feePctLabel: string;
  avg: number;
  ceiling: number;
  fee: number;
  cost: number;
  shares: number;
}) {
  const { platform, url, side, feePctLabel, avg, ceiling, fee, cost, shares } = props;
  const sideClass = side === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300";
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-3">
      <div className="mb-2 flex items-center justify-between">
        <a href={url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-white hover:text-blue-400">
          {platform} ↗
        </a>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${sideClass}`}>{side}</span>
      </div>
      <Row label="Shares" value={Math.round(shares).toLocaleString()} valueClass="text-white font-semibold" />
      <Row label="Avg buy price" value={`$${avg.toFixed(4)}`} />
      <Row label="Ceiling price" value={`$${ceiling.toFixed(4)}`} />
      <Row label={`Est. fee (${feePctLabel})`} value={`-$${fee.toFixed(2)}`} valueClass="text-orange-400" />
      <Row label="Total cost" value={`$${cost.toFixed(2)}`} />
      <Row label="Total incl. fees" value={`$${(cost + fee).toFixed(2)}`} valueClass="text-white font-semibold" border={false} />
    </div>
  );
}

function Row({ label, value, valueClass = "text-gray-200", border = true }: { label: string; value: string; valueClass?: string; border?: boolean }) {
  return (
    <div className={`flex items-center justify-between py-1.5 text-xs ${border ? "border-b border-gray-800/60" : ""}`}>
      <span className="text-gray-500">{label}</span>
      <span className={`font-mono ${valueClass}`}>{value}</span>
    </div>
  );
}
