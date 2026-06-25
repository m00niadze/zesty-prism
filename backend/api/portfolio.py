import json

from fastapi import APIRouter, Request, Query, BackgroundTasks, HTTPException

from database import get_setting, set_setting
from models.schemas import (
    ManualPositionIn,
    MarkSoldIn,
    PairExitOut,
    PfMarketOut,
    PortfolioSummaryOut,
    SaleIn,
    WalletIn,
)

router = APIRouter(prefix="/portfolio")


@router.get("/summary", response_model=PortfolioSummaryOut)
async def get_summary(request: Request):
    tracker = request.app.state.portfolio_tracker
    return await tracker.build_summary()


@router.get("/pairs/{matched_market_id}/exit", response_model=PairExitOut)
async def get_pair_exit(matched_market_id: int, request: Request):
    tracker = request.app.state.portfolio_tracker
    data = await tracker.build_pair_exit(matched_market_id)
    if data is None:
        raise HTTPException(status_code=404, detail="no open arbitrage pair for this market")
    return data


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


@router.post("/positions/{position_id}/sold")
async def mark_sold(position_id: int, body: MarkSoldIn, request: Request):
    """Mark a leg as sold (maker fill) with the proceeds received → moves the
    pair to the Closing Arbitrage section."""
    tracker = request.app.state.portfolio_tracker
    await tracker.mark_sold(position_id, body.sold_shares, body.proceeds)
    return {"status": "sold"}


@router.post("/positions/{position_id}/reopen")
async def reopen(position_id: int, request: Request):
    tracker = request.app.state.portfolio_tracker
    await tracker.reopen_position(position_id)
    return {"status": "open"}


@router.get("/positions/{position_id}/sales")
async def list_sales(position_id: int, request: Request):
    tracker = request.app.state.portfolio_tracker
    return {"items": await tracker.list_sales(position_id)}


@router.post("/positions/{position_id}/sales")
async def add_sale(position_id: int, body: SaleIn, request: Request):
    """Log a single partial sell of a leg (shares + cash received). proceeds may be
    null for a 'pending' sale awaiting the cash figure."""
    tracker = request.app.state.portfolio_tracker
    if body.shares <= 0:
        raise HTTPException(status_code=400, detail="shares must be > 0")
    await tracker.add_sale(position_id, body.shares, body.proceeds)
    return {"status": "added"}


@router.patch("/sales/{sale_id}")
async def update_sale(sale_id: int, body: SaleIn, request: Request):
    """Edit a logged sale — used to fill in a pending sale's cash, or fix a typo."""
    tracker = request.app.state.portfolio_tracker
    if body.shares <= 0:
        raise HTTPException(status_code=400, detail="shares must be > 0")
    await tracker.update_sale(sale_id, body.shares, body.proceeds)
    return {"status": "updated"}


@router.delete("/sales/{sale_id}")
async def delete_sale(sale_id: int, request: Request):
    tracker = request.app.state.portfolio_tracker
    await tracker.delete_sale(sale_id)
    return {"status": "deleted"}


@router.get("/pf-markets", response_model=list[PfMarketOut])
async def pf_markets(request: Request, q: str = Query("", min_length=0), limit: int = Query(30, le=100)):
    db = request.app.state.db

    # PF markets where the user already holds a Polymarket position (side,
    # shares, cost), so they can size the opposite leg to hedge into an arb.
    holding: dict[str, dict] = {}
    async with db.execute(
        """SELECT m.pf_market_id, p.side, p.size, p.cost_usd FROM positions p
           JOIN matched_markets m ON p.market_id = m.poly_condition_id
           WHERE p.platform='polymarket' AND p.status='open'"""
    ) as cur:
        for r in await cur.fetchall():
            holding[str(r["pf_market_id"])] = {
                "side": r["side"], "shares": r["size"], "cost": r["cost_usd"],
            }

    q = q.strip()
    if not q:
        # Default list = markets where you hold a Poly position (completable arbs).
        if not holding:
            return []
        ph = ",".join("?" * len(holding))
        async with db.execute(
            f"SELECT id, title, category_slug FROM pf_markets WHERE id IN ({ph}) ORDER BY title",
            list(holding.keys()),
        ) as cur:
            rows = await cur.fetchall()
    else:
        async with db.execute(
            "SELECT id, title, category_slug FROM pf_markets WHERE title LIKE ? ORDER BY title LIMIT ?",
            (f"%{q}%", limit),
        ) as cur:
            rows = await cur.fetchall()

    out = []
    for r in rows:
        h = holding.get(str(r["id"])) or {}
        out.append(PfMarketOut(
            id=r["id"], title=r["title"], category_slug=r["category_slug"],
            holding_poly_side=h.get("side"),
            holding_poly_shares=h.get("shares"),
            holding_poly_cost=h.get("cost"),
        ))
    return out


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
