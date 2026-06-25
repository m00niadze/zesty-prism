import asyncio
import logging
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.arb import router as arb_router
from api.fees import router as fees_router
from api.portfolio import router as portfolio_router
from api.pnl import router as pnl_router
from api.settings import router as settings_router
from clients.polymarket import PolymarketClient
from clients.predictfun import PredictFunClient
from config import settings
from database import init_schema, open_db
from services.arb_scanner import ArbScanner
from services.market_matcher import MarketMatcher
from services.portfolio_tracker import PortfolioTracker
from services.price_cache import PriceCache
from services.scheduler import AppState, start_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Zesty Prism backend starting...")
    state = AppState()
    state.settings = settings

    state.db = await open_db(settings.DATABASE_PATH)
    await init_schema(state.db)
    logger.info("Schema initialised")

    state.http_session = aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0 (compatible; ZestyPrism/1.0)"}
    )
    state.poly_client = PolymarketClient(state.http_session, settings)
    state.pf_client = PredictFunClient(state.http_session, settings)
    from services.pf_websocket import PFWebSocketClient
    state.pf_ws = PFWebSocketClient(settings.PREDICTFUN_WS_URL)
    state.price_cache = PriceCache()
    state.alert_queue = asyncio.Queue()
    state.arb_scanner = ArbScanner(state.db, state.price_cache, settings, state.alert_queue)
    state.market_matcher = MarketMatcher(state.db, settings, state.price_cache)
    state.portfolio_tracker = PortfolioTracker(
        state.db, state.poly_client, state.pf_client, settings, state.price_cache
    )
    from services.exit_alerter import ExitAlerter
    state.exit_alerter = ExitAlerter(state.db, state.portfolio_tracker, state.alert_queue)

    app.state.db = state.db
    app.state.portfolio_tracker = state.portfolio_tracker
    app.state.price_cache = state.price_cache
    app.state.poly_client = state.poly_client
    app.state.pf_client = state.pf_client
    app.state.pf_ws = state.pf_ws

    await start_all(state)
    app.state._scheduler_state = state

    yield

    logger.info("Shutting down...")
    await state.shutdown()
    await state.db.close()


app = FastAPI(title="Zesty Prism", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(arb_router, prefix="/api")
app.include_router(portfolio_router, prefix="/api")
app.include_router(pnl_router, prefix="/api")
app.include_router(fees_router, prefix="/api")
app.include_router(settings_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/internal/alert")
async def receive_alert(request: Request):
    """Receive processed arb alerts from the backend itself (for internal testing)."""
    return {"ok": True}


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s: %s", request.url, exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})
