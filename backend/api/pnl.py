from fastapi import APIRouter, Request, Query

from models.schemas import PnlSummaryOut

router = APIRouter(prefix="/pnl")


@router.get("/summary", response_model=PnlSummaryOut)
async def get_pnl_summary(request: Request):
    db = request.app.state.db
    tracker = request.app.state.portfolio_tracker

    # Unrealized PnL counts ONLY arbitrage positions (legs of a hedged pair) —
    # standalone positions are ignored.
    summary = await tracker.build_summary()
    unrealized = 0.0
    for pair in summary["pairs"]:
        for leg in (pair["poly"], pair["pf"]):
            if leg and leg.get("pnl") is not None:
                unrealized += leg["pnl"]

    async with db.execute(
        "SELECT COALESCE(SUM(realized_pnl), 0), COALESCE(SUM(fees_paid), 0) FROM pnl_records"
    ) as cur:
        row = await cur.fetchone()
        realized = row[0]
        fees = row[1]

    return PnlSummaryOut(
        unrealized_pnl=unrealized,
        realized_pnl=realized,
        total_fees_paid=fees,
        net_pnl=unrealized + realized - fees,
    )


@router.get("/positions")
async def get_pnl_positions(
    request: Request,
    status: str = Query("all"),
    wallet: str = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    db = request.app.state.db
    conditions = []
    params: list = []
    if status != "all":
        conditions.append("status = ?")
        params.append(status)
    if wallet:
        conditions.append("wallet_address = ?")
        params.append(wallet)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with db.execute(
        f"SELECT * FROM positions {where} ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ) as cur:
        rows = await cur.fetchall()

    return {"items": [dict(r) for r in rows]}
