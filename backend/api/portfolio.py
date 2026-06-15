import json

from fastapi import APIRouter, Request, Query, BackgroundTasks, HTTPException

from database import get_setting, set_setting
from models.schemas import (
    ManualPositionIn,
    PfMarketOut,
    PortfolioSummaryOut,
    WalletIn,
)

router = APIRouter(prefix="/portfolio")


@router.get("/summary", response_model=PortfolioSummaryOut)
async def get_summary(request: Request):
    tracker = request.app.state.portfolio_tracker
    return await tracker.build_summary()


@router.post("/refresh")
async def refresh(request: Request, background_tasks: BackgroundTasks):
    tracker = request.app.state.portfolio_tracker
    background_tasks.add_task(tracker.sync_all_wallets)
    return {"status": "refreshing"}


@router.post("/manual")
async def add_manual(body: ManualPositionIn, request: Request):
    tracker = request.app.state.portfolio_tracker
    if body.shares <= 0 or body.total_cost < 0:
        raise HTTPException(status_code=400, detail="shares must be > 0 and cost >= 0")
    await tracker.add_manual_pf_position(
        body.market_id, body.title, body.side, body.shares, body.total_cost
    )
    return {"status": "added"}


@router.delete("/positions/{position_id}")
async def delete_position(position_id: int, request: Request):
    tracker = request.app.state.portfolio_tracker
    await tracker.delete_position(position_id)
    return {"status": "deleted"}


@router.get("/pf-markets", response_model=list[PfMarketOut])
async def pf_markets(request: Request, q: str = Query("", min_length=0), limit: int = Query(30, le=100)):
    db = request.app.state.db
    like = f"%{q.strip()}%"
    async with db.execute(
        "SELECT id, title, category_slug FROM pf_markets WHERE title LIKE ? ORDER BY title LIMIT ?",
        (like, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [PfMarketOut(id=r["id"], title=r["title"], category_slug=r["category_slug"]) for r in rows]


@router.get("/wallets")
async def list_wallets(request: Request):
    db = request.app.state.db
    raw = await get_setting(db, "wallet_addresses", "[]")
    try:
        wallets = json.loads(raw or "[]")
    except Exception:
        wallets = []
    return {"wallets": wallets}


@router.post("/wallets")
async def add_wallet(body: WalletIn, request: Request, background_tasks: BackgroundTasks):
    db = request.app.state.db
    addr = body.address.strip()
    if not addr:
        raise HTTPException(status_code=400, detail="empty address")
    raw = await get_setting(db, "wallet_addresses", "[]")
    try:
        wallets = json.loads(raw or "[]")
    except Exception:
        wallets = []
    if addr not in wallets:
        wallets.append(addr)
        await set_setting(db, "wallet_addresses", json.dumps(wallets))
        background_tasks.add_task(request.app.state.portfolio_tracker.sync_wallet, addr)
    return {"wallets": wallets}


@router.delete("/wallets/{address}")
async def remove_wallet(address: str, request: Request):
    db = request.app.state.db
    raw = await get_setting(db, "wallet_addresses", "[]")
    try:
        wallets = json.loads(raw or "[]")
    except Exception:
        wallets = []
    wallets = [w for w in wallets if w != address]
    await set_setting(db, "wallet_addresses", json.dumps(wallets))
    # drop that wallet's auto positions
    await db.execute("DELETE FROM positions WHERE wallet_address=? AND source='auto'", (address,))
    await db.commit()
    return {"wallets": wallets}
