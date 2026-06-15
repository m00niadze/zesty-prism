import { useEffect, useState } from "react";
import { fetchSettings, updateSetting } from "../api/client";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState<string | null>(null);
  const [newWallet, setNewWallet] = useState("");

  useEffect(() => {
    fetchSettings().then((r) => {
      setSettings(r.data.settings);
      setLoading(false);
    });
  }, []);

  const save = async (key: string, value: string) => {
    await updateSetting(key, value);
    setSettings((s) => ({ ...s, [key]: value }));
    setSaved(key);
    setTimeout(() => setSaved(null), 2000);
  };

  const addWallet = async () => {
    if (!newWallet.trim()) return;
    const raw = settings.wallet_addresses || "[]";
    const wallets: string[] = JSON.parse(raw);
    if (!wallets.includes(newWallet.trim())) {
      wallets.push(newWallet.trim());
      await save("wallet_addresses", JSON.stringify(wallets));
    }
    setNewWallet("");
  };

  const removeWallet = async (w: string) => {
    const raw = settings.wallet_addresses || "[]";
    const wallets: string[] = JSON.parse(raw).filter((x: string) => x !== w);
    await save("wallet_addresses", JSON.stringify(wallets));
  };

  if (loading) return <div className="text-center py-16 text-gray-500">Loading settings...</div>;

  const wallets: string[] = JSON.parse(settings.wallet_addresses || "[]");

  return (
    <div className="space-y-8 max-w-lg">
      <h1 className="text-2xl font-bold text-white">Settings</h1>

      <section className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-5">
        <h2 className="font-semibold text-white">Alert Thresholds</h2>

        <Field
          label="Min arb threshold (%)"
          value={settings.min_arb_pct || "0.5"}
          onSave={(v) => save("min_arb_pct", v)}
          saved={saved === "min_arb_pct"}
          type="number"
          step="0.1"
        />
        <Field
          label="Min profit (USD)"
          value={settings.min_profit_usd || "2.0"}
          onSave={(v) => save("min_profit_usd", v)}
          saved={saved === "min_profit_usd"}
          type="number"
          step="0.5"
        />
        <Field
          label="Notional size (USD)"
          value={settings.notional_usd || "100.0"}
          onSave={(v) => save("notional_usd", v)}
          saved={saved === "notional_usd"}
          type="number"
          step="10"
        />

        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-300">Telegram notifications</span>
          <button
            onClick={() =>
              save("tg_notify_enabled", settings.tg_notify_enabled === "1" ? "0" : "1")
            }
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              settings.tg_notify_enabled === "1"
                ? "bg-emerald-800 text-emerald-200 hover:bg-emerald-700"
                : "bg-gray-700 text-gray-400 hover:bg-gray-600"
            }`}
          >
            {settings.tg_notify_enabled === "1" ? "ON 🔔" : "OFF 🔕"}
          </button>
        </div>
      </section>

      <section className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4">
        <h2 className="font-semibold text-white">Wallet Addresses</h2>
        <p className="text-xs text-gray-500">
          Public addresses only — used to track your portfolio (read-only).
        </p>

        {wallets.length === 0 && (
          <p className="text-sm text-gray-500">No wallets added yet.</p>
        )}

        {wallets.map((w) => (
          <div key={w} className="flex items-center justify-between bg-gray-800 rounded-lg px-3 py-2">
            <span className="font-mono text-sm text-gray-300 truncate">{w}</span>
            <button
              onClick={() => removeWallet(w)}
              className="ml-3 text-xs text-red-400 hover:text-red-300 shrink-0"
            >
              Remove
            </button>
          </div>
        ))}

        <div className="flex gap-2">
          <input
            type="text"
            placeholder="0xYourAddress"
            value={newWallet}
            onChange={(e) => setNewWallet(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addWallet()}
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand"
          />
          <button
            onClick={addWallet}
            className="px-4 py-2 bg-brand hover:bg-brand-dark text-white rounded-lg text-sm font-medium transition-colors"
          >
            Add
          </button>
        </div>
      </section>
    </div>
  );
}

function Field({
  label,
  value,
  onSave,
  saved,
  type = "text",
  step,
}: {
  label: string;
  value: string;
  onSave: (v: string) => void;
  saved: boolean;
  type?: string;
  step?: string;
}) {
  const [val, setVal] = useState(value);
  useEffect(() => setVal(value), [value]);

  return (
    <div className="flex items-center justify-between gap-4">
      <label className="text-sm text-gray-300 w-48">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type={type}
          step={step}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          className="w-28 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white font-mono focus:outline-none focus:border-brand"
        />
        <button
          onClick={() => onSave(val)}
          className="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg transition-colors"
        >
          {saved ? "Saved ✓" : "Save"}
        </button>
      </div>
    </div>
  );
}
