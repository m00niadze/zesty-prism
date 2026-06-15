import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usePnl } from "../hooks/usePnl";

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

export default function PnlPage() {
  const { pnl, fees, loading } = usePnl();

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
