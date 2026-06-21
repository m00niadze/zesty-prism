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

    # Closing positions (one leg fully sold, remainder still open) aren't in
    # "pairs", so their profit was being dropped from the totals. Count each
    # one's FULL live P&L (sold proceeds + current value of the open leg − paid)
    # so Net PNL reflects the whole position, not just open arb pairs.
    for closing in summary.get("closing", []):
        unrealized += closing.get("exit_now_pnl") or 0.0

    async with db.execute(
        "SELECT COALESCE(SUM(realized_pnl), 0), COALESCE(SUM(fees_paid), 0) FROM pnl_records"
    ) as cur:
        row = await cur.fetchone()
        realized = row[0]
        fees = row[1]

    # Completed (both-legs-sold) arbitrages aren't written to pnl_records, so add
    # their realized profit here — this is what populates Realized PNL on the page.
    realized += sum((c.get("profit") or 0.0) for c in summary.get("closed", []))

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


@router.get("/closed")
async def get_closed_arbs(request: Request):
    """Completed arbitrages — both legs fully sold. Each carries its realized
    profit (proceeds − paid) and the leg ids, so the PNL page can list and
    delete them (handy for clearing out fake/test positions)."""
    tracker = request.app.state.portfolio_tracker
    summary = await tracker.build_summary()
    return {"items": summary.get("closed", [])}
