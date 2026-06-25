from datetime import datetime, timezone


def _age_str(detected_at: str | None) -> str:
    """'live 42s' / 'live 3m' from an ISO detected_at, '' if unknown."""
    if not detected_at:
        return ""
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(detected_at)).total_seconds()
    except Exception:
        return ""
    if age < 0:
        return ""
    return f"live {int(age)}s" if age < 90 else f"live {int(age // 60)}m"


def fmt_arb_alert(
    opp: dict, poly_title: str, pf_title: str, poly_slug: str, pf_slug: str,
    opp_id: int | None = None, site_url: str = "",
) -> str:
    strategy_label = (
        "YES on Polymarket / NO on Predict.fun"
        if opp["strategy"] == "YES_POLY_NO_PF"
        else "NO on Polymarket / YES on Predict.fun"
    )
    poly_url = f"https://polymarket.com/event/{poly_slug}" if poly_slug else "https://polymarket.com"
    pf_url = f"https://predict.fun/market/{pf_slug}" if pf_slug else "https://predict.fun"

    calc_line = ""
    if site_url and opp_id is not None:
        calc_line = f'📊 <a href="{site_url.rstrip("/")}/?opp={opp_id}">Open in calculator</a>\n'

    edge = opp.get("net_pct_top", opp["net_profit_pct"])
    max_profit = opp.get("max_profit_usd", opp["net_profit_usd"])
    max_wager = opp.get("max_wager_usd", opp["notional_usd"])
    tag = "⚡ <b>BIG ARB</b>" if max_profit >= 50 else "🚨 <b>ARB ALERT</b>"
    when = ""
    da = opp.get("detected_at")
    if da:
        try:
            when = datetime.fromisoformat(da).strftime("%H:%M:%S UTC")
        except Exception:
            when = ""

    return (
        f"{tag}\n\n"
        f"<b>{poly_title}</b>\n\n"
        f"<b>Strategy:</b> {strategy_label}\n"
        f"  Polymarket {opp['poly_side']}:  <code>${opp['poly_price']:.4f}</code>\n"
        f"  Predict.fun {opp['pf_side']}:  <code>${opp['pf_price']:.4f}</code>\n\n"
        f"<b>Edge:</b> <code>{edge:.2f}%</code>   ·   "
        f"<b>Max profit:</b> <code>${max_profit:.2f}</code>\n"
        f"<b>Size (depth):</b> up to <code>${max_wager:.0f}</code>\n"
        + (f"<i>⏱ detected {when} — arbs move fast, act now</i>\n" if when else "")
        + f"\n{calc_line}"
        + f'<a href="{poly_url}">Polymarket</a>  |  <a href="{pf_url}">Predict.fun</a>'
    )


def fmt_exit_alert(o: dict, site_url: str = "") -> str:
    """Take-profit alert for an OPEN hedged pair that can be closed in profit."""
    poly = o["poly"]
    pf = o["pf"]
    best = o["best"]
    mkt = o.get("market_only", best)
    title = o.get("title", "Unknown")
    paid = o.get("paid", 0.0)

    def _route_line(name: str, leg_pos: dict, strat_leg: dict) -> str:
        kind = "Limit" if strat_leg.get("kind") == "limit" else "Market"
        sh = strat_leg.get("shares") or leg_pos.get("shares") or 0
        px = strat_leg.get("avg_price", 0.0)
        return f"  {name} {leg_pos['side']}: {kind} sell {sh:g} @ <code>${px:.4f}</code>"

    lines = [
        "💰 <b>EXIT ALERT</b> — take profit",
        "",
        f"<b>{title}</b>",
        "",
        "<b>Your pair:</b>",
        f"  Polymarket {poly['side']}: {poly['shares']:g} sh @ <code>${poly['avg_price']:.4f}</code>",
        f"  Predict.fun {pf['side']}: {pf['shares']:g} sh @ <code>${pf['avg_price']:.4f}</code>",
        f"  Paid <code>${paid:.2f}</code>  ·  sellable now <code>{o.get('now_sell_pct', 0.0):.1f}¢</code>"
        f" (in at <code>{o.get('bought_pct', 0.0):.1f}¢</code>)",
        "",
        f"<b>Best exit:</b> {best['name']}",
        f"  → close for <code>${best.get('total_value', 0.0):.2f}</code>  ·  "
        f"profit <code>${best.get('net', 0.0):.2f}</code> (<code>{best.get('roi', 0.0):.2f}%</code>)",
        _route_line("Polymarket", poly, best["poly"]),
        _route_line("Predict.fun", pf, best["pf"]),
    ]
    # If the best route rests a limit order (not guaranteed to fill), also show the
    # guaranteed-now floor: dumping both legs at market.
    if best.get("name") != mkt.get("name"):
        lines.append(
            f"<i>Floor — both at market now: ${mkt.get('net', 0.0):.2f} "
            f"({mkt.get('roi', 0.0):.2f}%)</i>"
        )
    lines.append("")
    poly_url = o.get("poly_url") or "https://polymarket.com"
    pf_url = o.get("pf_url") or "https://predict.fun"
    if site_url:
        lines.append(f'📊 <a href="{site_url.rstrip("/")}/portfolio">Open positions dashboard</a>')
    lines.append(f'<a href="{poly_url}">Polymarket</a>  |  <a href="{pf_url}">Predict.fun</a>')
    return "\n".join(lines)


def fmt_arb_list(opps: list[dict], min_pct: float = 3.0, min_usd: float = 5.0, site_url: str = "") -> str:
    if not opps:
        return (
            f"No live arbitrage matching your filters right now.\n"
            f"(min <code>{min_pct:.1f}%</code> arb · min <code>${min_usd:.0f}</code> profit)"
        )
    lines = [f"<b>LIVE ARB ({len(opps)})</b>  ·  min {min_pct:.1f}% · min ${min_usd:.0f}"]
    for i, o in enumerate(opps[:10], 1):
        title = o.get("poly_title", "Unknown")[:60]
        poly_side = o.get("poly_side", "?")
        pf_side = o.get("pf_side", "?")
        poly_slug = o.get("poly_slug", "")
        pf_slug = o.get("pf_category_slug", "")
        poly_url = f"https://polymarket.com/event/{poly_slug}" if poly_slug else "https://polymarket.com"
        pf_url = f"https://predict.fun/market/{pf_slug}" if pf_slug else "https://predict.fun"
        calc = (
            f"   📊 <a href=\"{site_url.rstrip('/')}/?opp={o['id']}\">Open in calculator</a>\n"
            if site_url else ""
        )
        age = _age_str(o.get("detected_at"))
        age_suffix = f"  ·  {age}" if age else ""
        lines.append(
            f"\n{i}. <b>{title}</b>\n"
            f"   Buy <b>{poly_side}</b> on Polymarket  @ <code>${o['poly_price']:.4f}</code>\n"
            f"   Buy <b>{pf_side}</b> on Predict.fun @ <code>${o['pf_price']:.4f}</code>\n"
            f"   Arb: <code>{o.get('net_pct_top', 0):.2f}%</code>  ·  "
            f"max profit <code>${o.get('max_profit_usd', 0):.2f}</code> "
            f"on <code>${o.get('max_wager_usd', 0):.0f}</code>{age_suffix}\n"
            f"{calc}"
            f"   <a href=\"{poly_url}\">Polymarket</a>  |  <a href=\"{pf_url}\">Predict.fun</a>"
        )
    return "\n".join(lines)


def fmt_portfolio(positions: list[dict], wallet: str) -> str:
    if not positions:
        return f"No open positions found for <code>{wallet[:10]}...</code>"
    by_platform: dict[str, list] = {}
    for p in positions:
        by_platform.setdefault(p["platform"], []).append(p)

    lines = [f"<b>PORTFOLIO</b>\n<code>{wallet[:14]}...</code>\n"]
    total_pnl = 0.0
    for platform, pos in by_platform.items():
        platform_label = "Polymarket" if platform == "polymarket" else "Predict.fun"
        lines.append(f"\n<b>{platform_label}</b>")
        for p in pos:
            pnl = p.get("unrealized_pnl")
            pnl_str = f"  PNL: <code>{'+'if pnl>=0 else ''}{pnl:.2f}</code>" if pnl is not None else ""
            lines.append(
                f"  {p['side']} <i>{p['market_title'][:40]}</i>\n"
                f"  {p['size']:.2f} sh @ <code>${p.get('avg_entry_price') or 0:.4f}</code>"
                f"  now <code>${p.get('current_price') or 0:.4f}</code>{pnl_str}"
            )
            if pnl is not None:
                total_pnl += pnl

    sign = "+" if total_pnl >= 0 else ""
    lines.append(f"\n<b>Unrealized PNL: <code>{sign}${total_pnl:.2f}</code></b>")
    return "\n".join(lines)


def fmt_pnl(unrealized: float, realized: float, fees: float, net: float) -> str:
    def s(v: float) -> str:
        return f"{'+'if v>=0 else ''}${v:.2f}"
    return (
        f"<b>PNL SUMMARY</b>\n\n"
        f"Open positions:    <code>{s(unrealized)}</code> unrealized\n"
        f"Closed positions:  <code>{s(realized)}</code> realized\n"
        f"Total fees paid:   <code>${fees:.2f}</code>\n\n"
        f"<b>Net all-time:  <code>{s(net)}</code></b>"
    )


def fmt_fees(poly: float, pf: float, total: float) -> str:
    return (
        f"<b>FEES TRACKER</b>\n\n"
        f"Polymarket:    <code>${poly:.2f}</code>\n"
        f"Predict.fun:   <code>${pf:.2f}</code>\n"
        f"<b>Total:         <code>${total:.2f}</code></b>"
    )


def fmt_settings(s: dict) -> str:
    notify = "ON 🔔" if s.get("tg_notify_enabled", "1") == "1" else "OFF 🔕"
    wallets = s.get("wallet_addresses", "[]")
    return (
        f"<b>SETTINGS</b>\n\n"
        f"Min arb %:        <code>{s.get('min_arb_pct', '3.0')}%</code>\n"
        f"Min profit (USD): <code>${s.get('min_profit_usd', '5.0')}</code>\n"
        f"Min depth (USD):  <code>${s.get('min_wager_usd', '30')}</code>\n"
        f"Min exit profit:  <code>{s.get('min_exit_profit_pct', '1.0')}%</code>\n"
        f"Notifications:    {notify}\n"
        f"Wallets:          <code>{wallets}</code>\n\n"
        f"Tap the buttons below to change, or use /set_min_pct, /set_min_usd, /add_wallet, /remove_wallet."
    )
