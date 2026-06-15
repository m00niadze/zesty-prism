from fastapi import APIRouter, Request, Query, HTTPException

from config import settings
from models.schemas import (
    ArbListOut,
    ArbOpportunityOut,
    CalculatorLegOut,
    CalculatorOut,
)
from services.arb_taker import YES_POLY_NO_PF
from database import utcnow

router = APIRouter(prefix="/arb")


@router.get("/opportunities", response_model=ArbListOut)
async def get_opportunities(
    request: Request,
    live_only: bool = Query(True),
    min_pct: float = Query(0.0),
    limit: int = Query(1000, le=5000),
    offset: int = Query(0),
):
    db = request.app.state.db
    conditions = []
    params: list = []
    if live_only:
        conditions.append("a.is_live = 1")
    if min_pct > 0:
        conditions.append("a.net_profit_pct >= ?")
        params.append(min_pct)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_sql = f"""
        SELECT COUNT(*) FROM arb_opportunities a {where}
    """
    async with db.execute(count_sql, params) as cur:
        total = (await cur.fetchone())[0]

    sql = f"""
        SELECT a.*, m.poly_title, m.pf_title, m.poly_category, m.poly_slug, m.pf_category_slug
        FROM arb_opportunities a
        JOIN matched_markets m ON a.matched_market_id = m.id
        {where}
        ORDER BY a.net_profit_pct DESC
        LIMIT ? OFFSET ?
    """
    async with db.execute(sql, params + [limit, offset]) as cur:
        rows = await cur.fetchall()

    items = [_row_to_opp(r) for r in rows]
    return ArbListOut(total=total, items=items)


@router.get("/history", response_model=ArbListOut)
async def get_history(
    request: Request,
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    db = request.app.state.db
    async with db.execute("SELECT COUNT(*) FROM arb_opportunities WHERE is_live = 0") as cur:
        total = (await cur.fetchone())[0]

    sql = """
        SELECT a.*, m.poly_title, m.pf_title, m.poly_category, m.poly_slug, m.pf_category_slug
        FROM arb_opportunities a
        JOIN matched_markets m ON a.matched_market_id = m.id
        WHERE a.is_live = 0
        ORDER BY a.detected_at DESC
        LIMIT ? OFFSET ?
    """
    async with db.execute(sql, [limit, offset]) as cur:
        rows = await cur.fetchall()

    items = [_row_to_opp(r) for r in rows]
    return ArbListOut(total=total, items=items)


def _row_to_opp(r) -> ArbOpportunityOut:
    return ArbOpportunityOut(
        id=r["id"],
        matched_market_id=r["matched_market_id"],
        poly_title=r["poly_title"],
        pf_title=r["pf_title"],
        poly_category=r["poly_category"],
        poly_slug=r["poly_slug"],
        pf_slug=r["pf_category_slug"],
        strategy=r["strategy"],
        poly_side=r["poly_side"],
        pf_side=r["pf_side"],
        poly_price=r["poly_price"],
        pf_price=r["pf_price"],
        combined_cost=r["combined_cost"],
        gross_profit_pct=r["gross_profit_pct"],
        poly_fee_usd=r["poly_fee_usd"],
        pf_fee_usd=r["pf_fee_usd"],
        total_fee_usd=r["total_fee_usd"],
        net_profit_pct=r["net_profit_pct"],
        net_profit_usd=r["net_profit_usd"],
        notional_usd=r["notional_usd"],
        max_wager_usd=r["max_wager_usd"],
        max_profit_usd=r["max_profit_usd"],
        net_pct_top=r["net_pct_top"],
        detected_at=r["detected_at"],
        is_live=bool(r["is_live"]),
    )


@router.get("/opportunities/{opp_id}/calculator", response_model=CalculatorOut)
async def get_calculator(opp_id: int, request: Request):
    """Return the live ascending ask ladders for both legs of an arb, plus fee
    rates and links, so the frontend can compute taker economics reactively."""
    db = request.app.state.db
    poly_client = request.app.state.poly_client
    pf_client = request.app.state.pf_client

    async with db.execute(
        """SELECT a.matched_market_id, a.strategy, a.poly_side, a.pf_side,
                  m.poly_title, m.pf_title, m.poly_slug, m.pf_category_slug,
                  m.poly_yes_token_id, m.poly_no_token_id, m.pf_market_id,
                  m.poly_fee_rate
           FROM arb_opportunities a
           JOIN matched_markets m ON a.matched_market_id = m.id
           WHERE a.id = ?""",
        (opp_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="opportunity not found")

    # PF fee rate for this market (basis points), with fallback.
    async with db.execute(
        "SELECT pf_taker_fee_rate FROM market_prices WHERE matched_market_id="
        "(SELECT matched_market_id FROM arb_opportunities WHERE id=?)",
        (opp_id,),
    ) as cur:
        pr = await cur.fetchone()
    pf_bps = (pr["pf_taker_fee_rate"] * 10000.0) if (pr and pr["pf_taker_fee_rate"]) else settings.PF_FALLBACK_FEE_BPS

    is_a = row["strategy"] == YES_POLY_NO_PF
    poly_token = row["poly_yes_token_id"] if is_a else row["poly_no_token_id"]
    poly_ladder = await poly_client.get_order_book(poly_token)
    ob = await pf_client.get_order_book(row["pf_market_id"])
    pf_ladder = (
        pf_client.no_asks_from_bids(ob["yes_bids"]) if is_a else ob["yes_asks"]
    )

    poly_leg = CalculatorLegOut(
        platform="polymarket",
        side=row["poly_side"],
        title=row["poly_title"],
        url=f"https://polymarket.com/event/{row['poly_slug']}",
        fee_bps=(row["poly_fee_rate"] or 0.0) * 10000.0,
        fee_mode="poly_formula",
        ladder=poly_ladder,
    )
    pf_leg = CalculatorLegOut(
        platform="predictfun",
        side=row["pf_side"],
        title=row["pf_title"],
        url=f"https://predict.fun/market/{row['pf_category_slug']}",
        fee_bps=pf_bps,
        fee_mode="pf_tent",
        ladder=pf_ladder,
    )
    return CalculatorOut(
        opportunity_id=opp_id,
        matched_market_id=row["matched_market_id"],
        strategy=row["strategy"],
        poly=poly_leg,
        pf=pf_leg,
        fetched_at=utcnow(),
    )
