import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import OpportunityTable from "../components/OpportunityTable";
import CalculatorDrawer from "../components/CalculatorDrawer";
import { ArbOpportunity } from "../api/client";
import { useArb } from "../hooks/useArb";

export default function ArbPage() {
  const [liveOnly, setLiveOnly] = useState(true);
  const [minPct, setMinPct] = useState(0);
  const [searchParams, setSearchParams] = useSearchParams();
  const { data, total, loading, error, refetch } = useArb(liveOnly, minPct);

  const oppParam = searchParams.get("opp");
  const selectedId = oppParam ? Number(oppParam) : null;
  const selectedOpp = data.find((o) => o.id === selectedId) ?? null;

  const select = (o: ArbOpportunity | null) => {
    const next = new URLSearchParams(searchParams);
    if (o) next.set("opp", String(o.id));
    else next.delete("opp");
    setSearchParams(next);
  };

  const liveCount = data.filter((o) => o.is_live).length;
  const bestPct = data.length > 0 ? Math.max(...data.map((o) => o.net_profit_pct)) : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Arbitrage Opportunities</h1>
          <p className="text-gray-400 text-sm mt-1">
            {liveCount} live · best {bestPct.toFixed(2)}% · updates every 3s
          </p>
        </div>
        <button
          onClick={refetch}
          className="px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        <Card label="Live Opportunities" value={String(liveCount)} color="text-emerald-400" />
        <Card label="Best Net Profit" value={`${bestPct.toFixed(2)}%`} color="text-yellow-400" />
        <Card label="Total Found" value={String(total)} color="text-blue-400" />
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 flex-wrap">
        <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={liveOnly}
            onChange={(e) => setLiveOnly(e.target.checked)}
            className="accent-brand"
          />
          Live only
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-400">
          Min %
          <input
            type="number"
            value={minPct}
            onChange={(e) => setMinPct(Number(e.target.value))}
            step="0.1"
            min="0"
            className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-sm focus:outline-none focus:border-brand"
          />
        </label>
      </div>

      {error && (
        <div className="bg-red-950 border border-red-800 rounded-lg px-4 py-3 text-red-300 text-sm">
          API error: {error}
        </div>
      )}

      {loading && data.length === 0 ? (
        <div className="text-center py-16 text-gray-500">Loading...</div>
      ) : (
        <OpportunityTable
          opportunities={data}
          selectedId={selectedId}
          onSelect={select}
        />
      )}

      {selectedId != null && (
        <CalculatorDrawer
          opportunityId={selectedId}
          titleFallback={selectedOpp?.poly_title}
          onClose={() => select(null)}
        />
      )}
    </div>
  );
}

function Card({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <p className="text-gray-400 text-xs uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
    </div>
  );
}
