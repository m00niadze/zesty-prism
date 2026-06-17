import asyncio
import logging
import os

import aiohttp
import aiohttp.web
import aiosqlite
from telegram.ext import Application

from database import get_setting
from formatters import fmt_arb_alert

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DATABASE_PATH", "/data/zesty.db")


class ArbNotifier:
    def __init__(self, settings, app: Application):
        self._settings = settings
        self._app = app
        self._server: aiohttp.web.AppRunner | None = None

    async def start_internal_server(self) -> None:
        from aiohttp import web

        web_app = web.Application()
        web_app.router.add_post("/internal/alert", self._handle_alert)
        self._runner = web.AppRunner(web_app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", 8001)
        await site.start()
        logger.info("Bot internal alert server listening on :8001")

    async def _handle_alert(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        secret = request.headers.get("X-Internal-Secret", "")
        if secret != self._settings.INTERNAL_ALERT_SECRET:
            return aiohttp.web.Response(status=403, text="Forbidden")

        try:
            opp = await request.json()
        except Exception:
            return aiohttp.web.Response(status=400, text="Bad JSON")

        asyncio.create_task(self._send_alert(opp))
        return aiohttp.web.Response(status=200, text="ok")

    async def _send_alert(self, opp: dict) -> None:
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        try:
            notify_enabled = await get_setting(db, "tg_notify_enabled", "1")
            if notify_enabled != "1":
                return

            mid = opp.get("matched_market_id")
            async with db.execute(
                "SELECT poly_title, pf_title, poly_slug, pf_market_id, pf_category_slug FROM matched_markets WHERE id=?",
                (mid,),
            ) as cur:
                row = await cur.fetchone()

            if not row:
                return

            msg = fmt_arb_alert(
                opp,
                poly_title=row["poly_title"],
                pf_title=row["pf_title"],
                poly_slug=row["poly_slug"],
                pf_slug=row["pf_category_slug"] or row["pf_market_id"],
                opp_id=opp.get("db_id"),
                site_url=os.getenv("SITE_BASE_URL", ""),
            )
            await self._app.bot.send_message(
                chat_id=self._settings.TELEGRAM_CHAT_ID,
                text=msg,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error("Failed to send Telegram alert: %s", e)
        finally:
            await db.close()

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
