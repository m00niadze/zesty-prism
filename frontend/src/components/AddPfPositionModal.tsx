import { useEffect, useState } from "react";
import { PfMarket, addManualPosition, searchPfMarkets } from "../api/client";

interface Props {
  onClose: () => void;
  onAdded: () => void;
}

export default function AddPfPositionModal({ onClose, onAdded }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PfMarket[]>([]);
  const [picked, setPicked] = useState<PfMarket | null>(null);
  const [side, setSide] = useState<"YES" | "NO">("YES");

  // When you pick a market where you hold a Poly side, default to the OPPOSITE
  // side here and pre-fill shares to match (that completes the hedge / arb).
  const pick = (m: PfMarket) => {
    setPicked(m);
    if (m.holding_poly_side) {
      setSide(m.holding_poly_side === "YES" ? "NO" : "YES");
      if (m.holding_poly_shares) setShares(String(Math.round(m.holding_poly_shares)));
    }
  };
  const [shares, setShares] = useState("");
  const [cost, setCost] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (picked) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const res = await searchPfMarkets(query);
        if (!cancelled) setResults(res.data);
      } catch { /* ignore */ }
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [query, picked]);

  const submit = async () => {
    if (!picked || !shares || Number(shares) <= 0) {
      setErr("Pick a market and enter shares.");
      return;
    }
    setSaving(true);
    try {
      await addManualPosition({
        market_id: picked.id,
        title: picked.title,
        side,
        shares: Number(shares),
        total_cost: Number(cost) || 0,
      });
      onAdded();
      onClose();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl border border-gray-800 bg-gray-950 p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Add Predict.fun position</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">✕</button>
        </div>

        {!picked ? (
          <>
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search Predict.fun markets…"
              className="w-full rounded-lg bg-gray-800 px-3 py-2 text-sm text-white focus:outline-none"
            />
            <div className="mt-2 max-h-64 overflow-y-auto">
              {results.map((m) => (
                <button
                  key={m.id}
                  onClick={() => pick(m)}
                  className="block w-full rounded px-3 py-2 text-left hover:bg-gray-800"
                >
                  <div className="truncate text-sm text-gray-300">{m.title}</div>
                  {m.holding_poly_side && (
                    <div className="mt-0.5 text-xs">
                      <span className="text-gray-500">Holding </span>
                      <span className={m.holding_poly_side === "YES" ? "text-emerald-400" : "text-red-400"}>
                        POLY {m.holding_poly_side}
                      </span>
                      <span className="text-gray-600"> → buy PF {m.holding_poly_side === "YES" ? "NO" : "YES"} to hedge</span>
                    </div>
                  )}
                </button>
              ))}
              {query && results.length === 0 && (
                <div className="px-3 py-2 text-sm text-gray-600">No markets found.</div>
              )}
            </div>
          </>
        ) : (
          <div className="space-y-3">
            <div className="rounded-lg bg-gray-800 px-3 py-2 text-sm text-white">
              {picked.title}
              <button onClick={() => setPicked(null)} className="ml-2 text-xs text-blue-400 hover:underline">change</button>
            </div>
            {picked.holding_poly_side && (
              <div className="rounded-lg border border-gray-800 bg-gray-900/60 px-3 py-2 text-xs">
                <div className="mb-1 text-gray-500">Your Polymarket position on this market</div>
                <div className="flex items-center gap-3">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                    picked.holding_poly_side === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300"
                  }`}>{picked.holding_poly_side}</span>
                  <span className="text-gray-300">{Math.round(picked.holding_poly_shares || 0).toLocaleString()} shares</span>
                  <span className="text-gray-500">·</span>
                  <span className="text-gray-300">${(picked.holding_poly_cost || 0).toFixed(2)} cost</span>
                </div>
                <div className="mt-1 text-gray-600">Buy PF {picked.holding_poly_side === "YES" ? "NO" : "YES"} (shares pre-filled to match) to hedge.</div>
              </div>
            )}
            <div className="flex gap-2">
              {(["YES", "NO"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setSide(s)}
                  className={`flex-1 rounded-lg py-2 text-sm font-semibold ${
                    side === s
                      ? s === "YES" ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300"
                      : "bg-gray-800 text-gray-400"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <label className="flex-1 text-xs text-gray-400">
                Shares
                <input type="number" value={shares} onChange={(e) => setShares(e.target.value)}
                  className="mt-1 w-full rounded-lg bg-gray-800 px-3 py-2 text-sm text-white focus:outline-none" />
              </label>
              <label className="flex-1 text-xs text-gray-400">
                Total cost ($)
                <input type="number" value={cost} onChange={(e) => setCost(e.target.value)}
                  className="mt-1 w-full rounded-lg bg-gray-800 px-3 py-2 text-sm text-white focus:outline-none" />
              </label>
            </div>
            {err && <div className="text-xs text-red-400">{err}</div>}
            <button
              onClick={submit}
              disabled={saving}
              className="w-full rounded-lg bg-blue-700 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
            >
              {saving ? "Adding…" : "Add position"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
