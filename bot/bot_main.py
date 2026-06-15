import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import BotCommand, MenuButtonCommands
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

import handlers
from notifier import ArbNotifier

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class BotSettings:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    INTERNAL_ALERT_SECRET: str = os.getenv("INTERNAL_ALERT_SECRET", "changeme")


async def _error_handler(update, context) -> None:
    logger.error("Update %s caused error: %s", update, context.error, exc_info=context.error)


async def main() -> None:
    settings = BotSettings()
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",         handlers.cmd_start))
    app.add_handler(CommandHandler("menu",          handlers.cmd_menu))
    app.add_handler(CommandHandler("arb",           handlers.cmd_arb))
    app.add_handler(CommandHandler("portfolio",     handlers.cmd_portfolio))
    app.add_handler(CommandHandler("pnl",           handlers.cmd_pnl))
    app.add_handler(CommandHandler("fees",          handlers.cmd_fees))
    app.add_handler(CommandHandler("settings",      handlers.cmd_settings))
    app.add_handler(CommandHandler("set_min_pct",   handlers.cmd_set_min_pct))
    app.add_handler(CommandHandler("set_min_usd",   handlers.cmd_set_min_usd))
    app.add_handler(CommandHandler("set_notional",  handlers.cmd_set_notional))
    app.add_handler(CommandHandler("add_wallet",    handlers.cmd_add_wallet))
    app.add_handler(CommandHandler("remove_wallet", handlers.cmd_remove_wallet))
    app.add_handler(CommandHandler("notify",        handlers.cmd_notify_toggle))

    # Inline keyboard buttons
    app.add_handler(CallbackQueryHandler(handlers.callback_handler))

    # Log any handler exceptions instead of silently swallowing them
    app.add_error_handler(_error_handler)

    notifier = ArbNotifier(settings, app)
    await notifier.start_internal_server()

    logger.info("Zesty Prism bot starting...")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        # Register commands so the blue menu button shows them
        await app.bot.set_my_commands([
            BotCommand("menu",        "Open main menu"),
            BotCommand("arb",         "Live arb opportunities"),
            BotCommand("settings",    "View & change settings"),
            BotCommand("notify",      "Toggle push alerts on/off"),
            BotCommand("portfolio",   "Open positions"),
            BotCommand("pnl",         "Profit & loss summary"),
            BotCommand("fees",        "Fees paid by platform"),
        ])
        await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())

        try:
            await app.bot.send_message(
                chat_id=settings.TELEGRAM_CHAT_ID,
                text="🟢 <b>Zesty Prism</b> is online. Tap the menu button or /menu to get started.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("Could not send startup message: %s", e)

        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

        await app.updater.stop()
        await app.stop()
        await notifier.stop()


if __name__ == "__main__":
    asyncio.run(main())
