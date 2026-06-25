import { useState } from "react";
import { Sale, addSale, updateSale, deleteSale } from "../api/client";

const round = (n: number) => Math.round(n);
const money = (n: number) => `${n < 0 ? "-" : ""}$${Math.abs(n).toFixed(2)}`;
const centsOf = (cash: number, shares: number) =>
  shares > 0 ? `≈${Math.round((cash / shares) * 100)}¢` : "";

// One inline form for both "add a sale" and "edit / fill a sale". Input is the
// TOTAL cash received for the lot; the implied per-share price is shown as a hint.
function SaleForm({
  initShares,
  initCash,
  lockShares,
  saveLabel,
  onSave,
  onCancel,
}: {
  initShares: string;
  initCash: string;
  lockShares?: boolean;
  saveLabel: string;
  onSave: (shares: number, cash: number) => Promise<void>;
  onCancel: () => void;
}) {
  const [sh, setSh] = useState(initShares);
  const [cash, setCash] = useState(initCash);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const shares = Number(sh);
  const c = Number(cash);
  const valid = shares > 0 && cash.trim() !== "" && !isNaN(c) && c >= 0;

  const save = async () => {
    if (!valid || busy) return;
    setBusy(true);
    setErr("");
    try {
      await onSave(shares, c);
    } catch (e) {
      setErr("Save failed — try again.");
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-gray-500">sold</span>
      <input
        value={sh}
        onChange={(e) => setSh(e.target.value)}
        disabled={lockShares || busy}
        inputMode="decimal"
        className="w-16 rounded bg-gray-800 px-1.5 py-1 text-white disabled:opacity-50"
      />
      <span className="text-gray-500">sh for&nbsp;$</span>
      <input
        value={cash}
        onChange={(e) => setCash(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && save()}
        disabled={busy}
        autoFocus
        inputMode="decimal"
        placeholder="cash"
        className="w-20 rounded bg-gray-800 px-1.5 py-1 text-white"
      />
      {valid && <span className="text-gray-600">{centsOf(c, shares)}</span>}
      <button
        onClick={save}
        disabled={!valid || busy}
        className="rounded bg-emerald-600 px-3 py-1 font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Saving…" : saveLabel}
      </button>
      <button onClick={onCancel} disabled={busy} className="px-1.5 text-gray-500 hover:text-gray-300">
        cancel
      </button>
      {err && <span className="text-red-400">{err}</span>}
    </div>
  );
}

export default function SalesPanel({
  legId,
  label,
  sales,
  onChanged,
}: {
  legId: number;
  label: string;
  sales: Sale[];
  onChanged: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);

  const pending = sales.filter((s) => s.proceeds === null);
  const filled = sales.filter((s) => s.proceeds !== null);

  return (
    <div className="mt-2 rounded-lg border border-gray-800 bg-gray-900/50 p-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label} · sales</span>
        {!adding && (
          <button
            onClick={() => setAdding(true)}
            className="rounded bg-gray-800 px-2 py-0.5 text-[11px] text-blue-300 hover:bg-gray-700"
          >
            + Record a sale
          </button>
        )}
      </div>

      {/* Auto-detected sells awaiting a cash amount — prominent, can't miss it. */}
      {pending.map((s) => (
        <div key={s.id} className="mb-1 rounded-md border border-amber-500/40 bg-amber-500/10 p-2">
          {editId === s.id ? (
            <SaleForm
              initShares={String(round(s.shares))}
              initCash=""
              lockShares
              saveLabel="Save"
              onSave={async (sh, c) => {
                await updateSale(s.id, sh, c);
                setEditId(null);
                onChanged();
              }}
              onCancel={() => setEditId(null)}
            />
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-amber-200">⚠ {round(s.shares)} sh sold — how much $ did you get?</span>
              <button
                onClick={() => setEditId(s.id)}
                className="rounded bg-amber-500 px-2.5 py-1 text-xs font-semibold text-black hover:bg-amber-400"
              >
                💵 Enter amount
              </button>
            </div>
          )}
        </div>
      ))}

      {/* Recorded lots. */}
      {filled.map((s) =>
        editId === s.id ? (
          <div key={s.id} className="mb-0.5">
            <SaleForm
              initShares={String(round(s.shares))}
              initCash={(s.proceeds ?? 0).toFixed(2)}
              saveLabel="Save"
              onSave={async (sh, c) => {
                await updateSale(s.id, sh, c);
                setEditId(null);
                onChanged();
              }}
              onCancel={() => setEditId(null)}
            />
          </div>
        ) : (
          <div key={s.id} className="mb-0.5 flex items-center gap-2 text-xs">
            <span className="text-emerald-300">
              {round(s.shares)} sh → <span className="font-mono">{money(s.proceeds ?? 0)}</span>{" "}
              <span className="text-gray-500">{centsOf(s.proceeds ?? 0, s.shares)}</span>
            </span>
            {s.source === "auto" && <span className="text-[10px] text-gray-600">auto</span>}
            <button onClick={() => setEditId(s.id)} className="text-blue-400 hover:underline">
              edit
            </button>
            <button
              onClick={async () => {
                await deleteSale(s.id);
                onChanged();
              }}
              className="text-gray-600 hover:text-red-400"
              title="Remove this sale"
            >
              ✕
            </button>
          </div>
        )
      )}

      {adding && (
        <div className="mt-1">
          <SaleForm
            initShares=""
            initCash=""
            saveLabel="Add"
            onSave={async (sh, c) => {
              await addSale(legId, sh, c);
              setAdding(false);
              onChanged();
            }}
            onCancel={() => setAdding(false)}
          />
        </div>
      )}

      {sales.length === 0 && !adding && (
        <div className="text-[11px] text-gray-600">No sales logged yet.</div>
      )}
    </div>
  );
}
