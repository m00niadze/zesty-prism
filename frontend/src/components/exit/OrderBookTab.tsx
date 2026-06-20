import { OrderBook, PairExit } from "../../api/client";

const cents = (p: number) => `${(p * 100).toFixed(1)}c`;

function BookSide({ book, color }: { book: OrderBook; color: string }) {
  const asks = [...book.asks].slice(0, 10).reverse(); // worst ask on top, best near spread
  const bids = book.bids.slice(0, 10);
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-3">
      <div className={`mb-2 text-sm font-semibold ${color}`}>{color === "text-blue-400" ? "Polymarket" : "Predict.fun"}</div>
      <div className="grid grid-cols-2 gap-1 text-xs">
        <div className="text-gray-500">Price</div><div className="text-right text-gray-500">Size</div>
      </div>
      <div className="space-y-0.5 text-xs">
        {asks.map((a, i) => (
          <div key={`a${i}`} className="grid grid-cols-2 gap-1">
            <div className="font-mono text-red-400">{cents(a[0])}</div>
            <div className="text-right font-mono text-gray-400">{Math.round(a[1]).toLocaleString()}</div>
          </div>
        ))}
        {asks.length === 0 && <div className="text-gray-600">no asks</div>}
        <div className="my-1 border-t border-gray-700" />
        {bids.map((b, i) => (
          <div key={`b${i}`} className="grid grid-cols-2 gap-1">
            <div className="font-mono text-emerald-400">{cents(b[0])}</div>
            <div className="text-right font-mono text-gray-400">{Math.round(b[1]).toLocaleString()}</div>
          </div>
        ))}
        {bids.length === 0 && <div className="text-gray-600">no bids</div>}
      </div>
    </div>
  );
}

export default function OrderBookTab({ exit }: { exit: PairExit }) {
  const polySide = exit.legs.find((l) => l.platform === "polymarket")?.side ?? "";
  const pfSide = exit.legs.find((l) => l.platform === "predictfun")?.side ?? "";
  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-500">Live books for the side you hold (<span className="text-red-400">asks</span> = buy / <span className="text-emerald-400">bids</span> = sell).</p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div><div className="mb-1 text-[10px] uppercase tracking-wide text-gray-600">Holding {polySide}</div><BookSide book={exit.poly_book} color="text-blue-400" /></div>
        <div><div className="mb-1 text-[10px] uppercase tracking-wide text-gray-600">Holding {pfSide}</div><BookSide book={exit.pf_book} color="text-purple-400" /></div>
      </div>
    </div>
  );
}
