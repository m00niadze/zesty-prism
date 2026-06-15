# Zesty Prism

Real-time arbitrage detection across prediction markets — **Polymarket** and
**Predict.fun**. It finds markets that exist on both venues, walks the live order
books to compute genuine *taker* (market-buy) profit after fees, and surfaces the
opportunities on a web dashboard and via Telegram alerts.

## Features

- **Real-time detection** — Predict.fun order books stream over WebSocket;
  opportunities appear within a few seconds.
- **Honest, fee-aware profit** — every opportunity is computed by walking real
  order-book depth, after each platform's actual taker fees. No fake spreads.
- **Calculator** — click any opportunity to size a trade: wager / shares / target
  ROI, per-leg avg & ceiling prices, fees, payout.
- **Portfolio** — connect Polymarket wallets (read-only) and add Predict.fun
  positions manually; positions group into arbitrage pairs.
- **Telegram bot** — live opportunities, adjustable filters (min %, min profit),
  push alerts with deep links into the dashboard.

## Stack

- **Backend** — Python 3.11, FastAPI, aiosqlite, aiohttp
- **Frontend** — React 18, Vite, TypeScript, Tailwind
- **Bot** — python-telegram-bot
- **Deploy** — Docker Compose

## Running

```bash
cp .env.example .env   # fill in your keys / token / wallet addresses
docker compose up -d
```

The dashboard is served on port 80; the API and bot run as internal services.

## Note on the source

A few core detection modules (the taker/fee math, the cross-platform matching,
and the Predict.fun WebSocket integration) are **not included** in this public
repository. The app structure, API, UI, and infrastructure are all here, but the
proprietary pricing/matching logic is kept private.
