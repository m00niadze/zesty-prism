import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Fragment, useEffect, useState } from "react";
import { usePnl } from "../hooks/usePnl";
import { ClosedArb, deletePosition, fetchClosedArbs } from "../api/client";

function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      <p className="text-gray-400 text-xs uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold font-mono mt-1 ${color}`}>{value}</p>
    </div>
  );
}

function fmt(v: number) {
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${v.toFixed(2)}`;
}

const plat = (p: string) => (p === "polymarket" ? "Polymarket" : "Predict.fun");

function ClosedBreakdown({ c }: { c: ClosedArb }) {
  return (
    <div className="space-y-1.5 px-1 py-2 text-xs">
      {(c.legs ?? []).map((leg, i) => {
        const lots = (leg.sales ?? []).filter((s) => s.proceeds !== null);
        return (
          <div key={i} className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-gray-400">{plat(leg.platform)} <span className="font-semibold text-gray-200">{leg.side}</span></span>
            <span className="font-mono text-emerald-300">→ ${leg.sold_proceeds.toFixed(2)}</span>
            <span className="text-gray-500">
              {lots.length === 0
                ? "(no itemized fills)"
                : lots
                    .map((s) => `${Math.round(s.shares)} @ ${Math.round(((s.proceeds ?? 0) / s.shares) * 100)}¢`)
                    .join(" · ")}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function PnlPage() {
  const { pnl, fees, loading } = usePnl();
  const [closed, setClosed] = useState<ClosedArb[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const loadClosed = () => fetchClosedArbs().then((r) => setClosed(r.data.items)).catch(() => {});
  useEffect(() => {
    loadClosed();
    const t = setInterval(loadClosed, 30000);
    return () => clearInterval(t);
  }, []);
  const removeClosed = async (c: ClosedArb) => {
    if (!confirm("Delete this closed arbitrage? Removes both legs from the database.")) return;
    await Promise.all(c.leg_ids.map((id) => deletePosition(id)));
    loadClosed();
  };

  if (loading) return <div className="text-center py-16 text-gray-500">Loading PNL...</div>;

  const netColor = pnl.net_pnl >= 0 ? "text-emerald-400" : "text-red-400";

  // Simple chart data built from summary (real chart would need pnl_records timeline from API)
  const chartData = [
    { name: "Unrealized", value: pnl.unrealized_pnl },
    { name: "Realized", value: pnl.realized_pnl },
    { name: "Fees", value: -fees.total_fees },
    { name: "Net", value: pnl.net_pnl },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">PNL</h1>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <SummaryCard
          label="Unrealized PNL"
          value={fmt(pnl.unrealized_pnl)}
          color={pnl.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400"}
        />
        <SummaryCard
          label="Realized PNL"
          value={fmt(pnl.realized_pnl)}
          color={pnl.realized_pnl >= 0 ? "text-emerald-400" : "text-red-400"}
        />
        <SummaryCard
          label="Total Fees Paid"
          value={`$${fees.total_fees.toFixed(2)}`}
          color="text-orange-400"
        />
        <SummaryCard label="Net PNL" value={fmt(pnl.net_pnl)} color={netColor} />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h2 className="text-sm font-medium text-gray-400 mb-4 uppercase tracking-wide">
          PNL Breakdown
        </h2>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="name" tick={{ fill: "#9ca3af", fontSize: 12 }} />
            <YAxis tick={{ fill: "#9ca3af", fontSize: 12 }} />
            <Tooltip
              contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151", borderRadius: 8 }}
              labelStyle={{ color: "#f9fafb" }}
              formatter={(v: number) => [`$${v.toFixed(2)}`, ""]}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#7c3aed"
              strokeWidth={2}
              dot={{ fill: "#7c3aed", r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h2 className="text-sm font-medium text-gray-400 mb-4 uppercase tracking-wide">Fees by Platform</h2>
        <div className="space-y-3">
          <FeeRow platform="Polymarket" fee={fees.polymarket_fees} />
          <FeeRow platform="Predict.fun" fee={fees.predictfun_fees} />
          <div className="border-t border-gray-800 pt-3">
            <FeeRow platform="Total" fee={fees.total_fees} bold />
          </div>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h2 className="text-sm font-medium text-gray-400 mb-4 uppercase tracking-wide">
          Closed Arbitrages ({closed.length})
        </h2>
        {closed.length === 0 ? (
          <p className="text-sm text-gray-600">
            No closed arbitrages yet. When both legs of a pair are fully sold, the completed trade lands here with its realized profit.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-400">
                  <th className="py-2 pr-4 font-medium">Market</th>
                  <th className="py-2 px-4 text-right font-medium">Paid</th>
                  <th className="py-2 px-4 text-right font-medium">Proceeds</th>
                  <th className="py-2 px-4 text-right font-medium">Profit</th>
                  <th className="py-2 pl-4"></th>
                </tr>
              </thead>
              <tbody>
                {closed.map((c) => (
                  <Fragment key={c.matched_market_id}>
                    <tr className="border-t border-gray-800/60">
                      <td className="py-2 pr-4 max-w-xs truncate text-white" title={c.title}>
                        <button
                          onClick={() => setOpenId(openId === c.matched_market_id ? null : c.matched_market_id)}
                          className="mr-1.5 text-gray-500 hover:text-gray-300"
                          title="Show the sale-by-sale breakdown"
                        >
                          {openId === c.matched_market_id ? "▾" : "▸"}
                        </button>
                        {c.title}
                      </td>
                      <td className="py-2 px-4 text-right font-mono text-gray-300">${c.paid.toFixed(2)}</td>
                      <td className="py-2 px-4 text-right font-mono text-gray-300">${c.proceeds.toFixed(2)}</td>
                      <td className={`py-2 px-4 text-right font-mono font-semibold ${c.profit >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmt(c.profit)}</td>
                      <td className="py-2 pl-4 text-right">
                        <button onClick={() => removeClosed(c)} className="text-gray-600 hover:text-red-400" title="Delete (removes both legs)">✕</button>
                      </td>
                    </tr>
                    {openId === c.matched_market_id && (
                      <tr className="bg-gray-950/40">
                        <td colSpan={5}><ClosedBreakdown c={c} /></td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function FeeRow({ platform, fee, bold }: { platform: string; fee: number; bold?: boolean }) {
  return (
    <div className={`flex justify-between items-center ${bold ? "font-semibold text-white" : "text-gray-400"}`}>
      <span className="text-sm">{platform}</span>
      <span className="font-mono text-sm">${fee.toFixed(2)}</span>
    </div>
  );
}
