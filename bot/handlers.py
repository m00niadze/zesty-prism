import json
import logging
import os

import aiosqlite
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database import get_all_settings, get_setting, set_setting
from formatters import (
    fmt_arb_list,
    fmt_fees,
    fmt_pnl,
    fmt_portfolio,
    fmt_settings,
)

logger = logging.getLogger(__name__)

DB_PATH = "/data/zesty.db"
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "")


async def _db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Live Arb", callback_data="arb"),
            InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
        ],
        [
            InlineKeyboardButton("💼 Portfolio", callback_data="portfolio"),
            InlineKeyboardButton("📈 P&L", callback_data="pnl"),
            InlineKeyboardButton("💸 Fees", callback_data="fees"),
        ],
    ])


def _back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]])


def _opt(label: str, value: float, current: str, prefix: str) -> InlineKeyboardButton:
    """A preset button, check-marked when it matches the current setting."""
    try:
        active = abs(float(current) - value) < 1e-9
    except (TypeError, ValueError):
        active = False
    text = f"✅ {label}" if active else label
    return InlineKeyboardButton(text, callback_data=f"{prefix}{value}")


def _settings_keyboard(s: dict) -> InlineKeyboardMarkup:
    notify_label = "🔔 Alerts ON" if s.get("tg_notify_enabled", "1") == "1" else "🔕 Alerts OFF"
    cur_pct = s.get("min_arb_pct", "3.0")
    cur_usd = s.get("min_profit_usd", "5.0")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("─── Min arb % ───", callback_data="noop")],
        [
            _opt("1%", 1.0, cur_pct, "set_min_pct_"),
            _opt("2%", 2.0, cur_pct, "set_min_pct_"),
            _opt("3%", 3.0, cur_pct, "set_min_pct_"),
            _opt("5%", 5.0, cur_pct, "set_min_pct_"),
        ],
        [InlineKeyboardButton("─── Min profit USD ───", callback_data="noop")],
        [
            _opt("$1",  1.0,  cur_usd, "set_min_usd_"),
            _opt("$5",  5.0,  cur_usd, "set_min_usd_"),
            _opt("$10", 10.0, cur_usd, "set_min_usd_"),
            _opt("$25", 25.0, cur_usd, "set_min_usd_"),
        ],
        [InlineKeyboardButton(notify_label, callback_data="toggle_notify")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu")],
    ])


async def _fetch_arb(db: aiosqlite.Connection) -> str:
    min_pct = float(await get_setting(db, "min_arb_pct", "3.0") or 3.0)
    min_usd = float(await get_setting(db, "min_profit_usd", "5.0") or 5.0)
    async with db.execute(
        """SELECT a.*, m.poly_title, m.pf_title, m.poly_category,
                  m.poly_slug, m.pf_category_slug
           FROM arb_opportunities a
           JOIN matched_markets m ON a.matched_market_id = m.id
           WHERE a.is_live = 1 AND a.net_pct_top >= ? AND a.max_profit_usd >= ?
           ORDER BY a.max_profit_usd DESC
           LIMIT 10""",
        (min_pct, min_usd),
    ) as cur:
        rows = await cur.fetchall()
    return fmt_arb_list([dict(r) for r in rows], min_pct, min_usd, SITE_BASE_URL)


async def _fetch_portfolio(db: aiosqlite.Connection) -> str:
    raw = await get_setting(db, "wallet_addresses", "[]")
    wallets = json.loads(raw or "[]")
    if not wallets:
        return "No wallets configured.\nUse /add_wallet 0xYourAddress to add one."
    wallet = wallets[0]
    async with db.execute(
        "SELECT * FROM positions WHERE wallet_address = ? AND status='open'", (wallet,)
    ) as cur:
        rows = await cur.fetchall()
    return fmt_portfolio([dict(r) for r in rows], wallet)


async def _fetch_pnl(db: aiosqlite.Connection) -> str:
    async with db.execute(
        "SELECT COALESCE(SUM(unrealized_pnl),0) FROM positions WHERE status='open'"
    ) as cur:
        unrealized = (await cur.fetchone())[0]
    async with db.execute(
        "SELECT COALESCE(SUM(realized_pnl),0), COALESCE(SUM(fees_paid),0) FROM pnl_records"
    ) as cur:
        row = await cur.fetchone()
        realized, fees = row[0], row[1]
    return fmt_pnl(unrealized, realized, fees, unrealized + realized - fees)


async def _fetch_fees(db: aiosqlite.Connection) -> str:
    async with db.execute(
        "SELECT COALESCE(SUM(poly_fee_usd),0), COALESCE(SUM(pf_fee_usd),0) FROM arb_opportunities"
    ) as cur:
        row = await cur.fetchone()
        poly, pf = row[0], row[1]
    return fmt_fees(poly, pf, poly + pf)


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 <b>Zesty Prism</b> is live. Tap a button:",
        parse_mode="HTML",
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Main menu:",
        reply_markup=_main_menu_keyboard(),
    )


async def cmd_arb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = await _db()
    try:
        msg = await _fetch_arb(db)
    finally:
        await db.close()
    await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True,
                                    reply_markup=_back_button())


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = await _db()
    try:
        msg = await _fetch_portfolio(db)
    finally:
        await db.close()
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=_back_button())


async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = await _db()
    try:
        msg = await _fetch_pnl(db)
    finally:
        await db.close()
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=_back_button())


async def cmd_fees(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = await _db()
    try:
        msg = await _fetch_fees(db)
    finally:
        await db.close()
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=_back_button())


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = await _db()
    try:
        s = await get_all_settings(db)
    finally:
        await db.close()
    await update.message.reply_text(
        fmt_settings(s), parse_mode="HTML", reply_markup=_settings_keyboard(s)
    )


async def cmd_set_min_pct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /set_min_pct 0.5")
        return
    try:
        val = float(context.args[0])
        db = await _db()
        await set_setting(db, "min_arb_pct", str(val))
        await db.close()
        await update.message.reply_text(f"Min arb threshold set to {val}%", reply_markup=_back_button())
    except ValueError:
        await update.message.reply_text("Invalid value. Example: /set_min_pct 0.5")


async def cmd_set_min_usd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /set_min_usd 2.0")
        return
    try:
        val = float(context.args[0])
        db = await _db()
        await set_setting(db, "min_profit_usd", str(val))
        await db.close()
        await update.message.reply_text(f"Min profit set to ${val}", reply_markup=_back_button())
    except ValueError:
        await update.message.reply_text("Invalid value. Example: /set_min_usd 2.0")


async def cmd_set_notional(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /set_notional 100")
        return
    try:
        val = float(context.args[0])
        db = await _db()
        await set_setting(db, "notional_usd", str(val))
        await db.close()
        await update.message.reply_text(f"Notional size set to ${val}", reply_markup=_back_button())
    except ValueError:
        await update.message.reply_text("Invalid value. Example: /set_notional 100")


async def cmd_add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /add_wallet 0xYourAddress")
        return
    wallet = context.args[0].strip()
    db = await _db()
    try:
        raw = await get_setting(db, "wallet_addresses", "[]")
        wallets: list[str] = json.loads(raw or "[]")
        if wallet not in wallets:
            wallets.append(wallet)
            await set_setting(db, "wallet_addresses", json.dumps(wallets))
        await update.message.reply_text(f"Wallet added: <code>{wallet}</code>", parse_mode="HTML")
    finally:
        await db.close()


async def cmd_remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /remove_wallet 0xYourAddress")
        return
    wallet = context.args[0].strip()
    db = await _db()
    try:
        raw = await get_setting(db, "wallet_addresses", "[]")
        wallets: list[str] = json.loads(raw or "[]")
        if wallet in wallets:
            wallets.remove(wallet)
            await set_setting(db, "wallet_addresses", json.dumps(wallets))
        await update.message.reply_text(f"Wallet removed: <code>{wallet}</code>", parse_mode="HTML")
    finally:
        await db.close()


async def cmd_notify_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = await _db()
    try:
        cur_val = await get_setting(db, "tg_notify_enabled", "1")
        new = "0" if cur_val == "1" else "1"
        await set_setting(db, "tg_notify_enabled", new)
        label = "enabled 🔔" if new == "1" else "disabled 🔕"
        await update.message.reply_text(f"Notifications {label}", reply_markup=_back_button())
    finally:
        await db.close()


# ── Inline keyboard callback handler ─────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop":
        return

    if data == "menu":
        await query.edit_message_text("Main menu:", reply_markup=_main_menu_keyboard())
        return

    db = await _db()
    try:
        if data == "arb":
            msg = await _fetch_arb(db)
            await query.edit_message_text(msg, parse_mode="HTML",
                                          disable_web_page_preview=True,
                                          reply_markup=_back_button())

        elif data == "portfolio":
            msg = await _fetch_portfolio(db)
            await query.edit_message_text(msg, parse_mode="HTML", reply_markup=_back_button())

        elif data == "pnl":
            msg = await _fetch_pnl(db)
            await query.edit_message_text(msg, parse_mode="HTML", reply_markup=_back_button())

        elif data == "fees":
            msg = await _fetch_fees(db)
            await query.edit_message_text(msg, parse_mode="HTML", reply_markup=_back_button())

        elif data == "settings":
            s = await get_all_settings(db)
            await query.edit_message_text(fmt_settings(s), parse_mode="HTML",
                                          reply_markup=_settings_keyboard(s))

        elif data.startswith("set_min_pct_"):
            val = data.split("_")[-1]
            await set_setting(db, "min_arb_pct", val)
            s = await get_all_settings(db)
            await query.edit_message_text(fmt_settings(s), parse_mode="HTML",
                                          reply_markup=_settings_keyboard(s))

        elif data.startswith("set_min_usd_"):
            val = data.split("_")[-1]
            await set_setting(db, "min_profit_usd", val)
            s = await get_all_settings(db)
            await query.edit_message_text(fmt_settings(s), parse_mode="HTML",
                                          reply_markup=_settings_keyboard(s))

        elif data == "toggle_notify":
            cur_val = await get_setting(db, "tg_notify_enabled", "1")
            await set_setting(db, "tg_notify_enabled", "0" if cur_val == "1" else "1")
            s = await get_all_settings(db)
            await query.edit_message_text(fmt_settings(s), parse_mode="HTML",
                                          reply_markup=_settings_keyboard(s))

    finally:
        await db.close()
