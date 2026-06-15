from fastapi import APIRouter, Request

from models.schemas import FeesSummaryOut

router = APIRouter(prefix="/fees")


@router.get("/summary", response_model=FeesSummaryOut)
async def get_fees_summary(request: Request):
    db = request.app.state.db

    # Fees reflect ONLY actual fees paid on real trades (fee_events table).
    # The theoretical per-opportunity fee estimates in arb_opportunities are
    # NOT real spending — summing them across every detected opportunity
    # produced a huge phantom number even with no wallets connected.
    async with db.execute(
        """SELECT platform, COALESCE(SUM(fee_amount), 0) as total
           FROM fee_events GROUP BY platform"""
    ) as cur:
        rows = await cur.fetchall()

    by_platform = {r["platform"]: r["total"] for r in rows}

    poly = by_platform.get("polymarket", 0.0)
    pf = by_platform.get("predictfun", 0.0)

    return FeesSummaryOut(
        polymarket_fees=poly,
        predictfun_fees=pf,
        total_fees=poly + pf,
    )
