import aiosqlite
import json
from datetime import datetime, timezone

DB_PATH = "/data/zesty.db"

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS matched_markets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    poly_condition_id   TEXT    NOT NULL,
    poly_slug           TEXT    NOT NULL,
    poly_yes_token_id   TEXT    NOT NULL,
    poly_no_token_id    TEXT    NOT NULL,
    poly_title          TEXT    NOT NULL,
    poly_category       TEXT    NOT NULL DEFAULT '',
    poly_fee_rate       REAL    NOT NULL DEFAULT 0.0,
    pf_market_id        TEXT    NOT NULL,
    pf_category_slug    TEXT    NOT NULL DEFAULT '',
    pf_title            TEXT    NOT NULL,
    match_score         REAL    NOT NULL,
    match_method        TEXT    NOT NULL DEFAULT 'fuzzy_title',
    is_active           INTEGER NOT NULL DEFAULT 1,
    matched_at          TEXT    NOT NULL,
    last_checked_at     TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mm_pair
    ON matched_markets (poly_condition_id, pf_market_id);

CREATE TABLE IF NOT EXISTS market_prices (
    matched_market_id   INTEGER PRIMARY KEY REFERENCES matched_markets(id),
    poly_yes_price      REAL,
    poly_no_price       REAL,
    pf_yes_price        REAL,
    pf_no_price         REAL,
    pf_taker_fee_rate   REAL    NOT NULL DEFAULT 0.0,
    poly_fetched_at     TEXT,
    pf_fetched_at       TEXT
);

CREATE TABLE IF NOT EXISTS arb_opportunities (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    matched_market_id   INTEGER NOT NULL REFERENCES matched_markets(id),
    strategy            TEXT    NOT NULL,
    poly_side           TEXT    NOT NULL,
    pf_side             TEXT    NOT NULL,
    poly_price          REAL    NOT NULL,
    pf_price            REAL    NOT NULL,
    combined_cost       REAL    NOT NULL,
    gross_profit_pct    REAL    NOT NULL,
    poly_fee_usd        REAL    NOT NULL DEFAULT 0.0,
    pf_fee_usd          REAL    NOT NULL DEFAULT 0.0,
    total_fee_usd       REAL    NOT NULL DEFAULT 0.0,
    net_profit_pct      REAL    NOT NULL,
    net_profit_usd      REAL    NOT NULL,
    notional_usd        REAL    NOT NULL DEFAULT 100.0,
    max_wager_usd       REAL    NOT NULL DEFAULT 0.0,
    max_profit_usd      REAL    NOT NULL DEFAULT 0.0,
    net_pct_top         REAL    NOT NULL DEFAULT 0.0,
    detected_at         TEXT    NOT NULL,
    is_live             INTEGER NOT NULL DEFAULT 1,
    closed_at           TEXT
);

CREATE INDEX IF NOT EXISTS idx_arb_detected ON arb_opportunities (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_arb_live     ON arb_opportunities (is_live, net_profit_pct DESC);
CREATE INDEX IF NOT EXISTS idx_arb_market   ON arb_opportunities (matched_market_id, strategy, is_live);

CREATE TABLE IF NOT EXISTS positions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address      TEXT    NOT NULL,
    platform            TEXT    NOT NULL,
    market_id           TEXT    NOT NULL,
    market_title        TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    size                REAL    NOT NULL,
    avg_entry_price     REAL,
    current_price       REAL,
    unrealized_pnl      REAL,
    cost_usd            REAL,
    source              TEXT    NOT NULL DEFAULT 'auto',
    sold_proceeds       REAL,
    sold_at             TEXT,
    sold_shares         REAL    NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'open',
    entry_at            TEXT,
    closed_at           TEXT,
    fetched_at          TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pos_wallet ON positions (wallet_address, status);

CREATE TABLE IF NOT EXISTS pf_markets (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    category_slug   TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_stats (
    matched_market_id   INTEGER PRIMARY KEY REFERENCES matched_markets(id),
    poly_volume         REAL,
    poly_liquidity      REAL,
    poly_spread         REAL,
    pf_liquidity        REAL,
    pf_spread           REAL,
    updated_at          TEXT
);

CREATE TABLE IF NOT EXISTS pnl_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id         INTEGER REFERENCES positions(id),
    wallet_address      TEXT    NOT NULL,
    platform            TEXT    NOT NULL,
    market_title        TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    size                REAL    NOT NULL,
    entry_price         REAL    NOT NULL,
    exit_price          REAL    NOT NULL,
    realized_pnl        REAL    NOT NULL,
    fees_paid           REAL    NOT NULL DEFAULT 0.0,
    closed_at           TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS fee_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    platform            TEXT    NOT NULL,
    market_id           TEXT    NOT NULL,
    fee_type            TEXT    NOT NULL DEFAULT 'taker',
    fee_amount          REAL    NOT NULL,
    recorded_at         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
"""

_DEFAULT_SETTINGS = {
    "min_arb_pct": "0.5",
    "min_profit_usd": "2.0",
    "notional_usd": "100.0",
    "wallet_addresses": "[]",
    "tg_notify_enabled": "1",
}


async def open_db(path: str = DB_PATH) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    return db


# Columns added after the initial release — applied to pre-existing DBs.
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "arb_opportunities": [
        ("max_wager_usd", "REAL NOT NULL DEFAULT 0.0"),
        ("max_profit_usd", "REAL NOT NULL DEFAULT 0.0"),
        ("net_pct_top", "REAL NOT NULL DEFAULT 0.0"),
    ],
    "positions": [
        ("cost_usd", "REAL"),
        ("source", "TEXT NOT NULL DEFAULT 'auto'"),
        ("sold_proceeds", "REAL"),
        ("sold_at", "TEXT"),
        ("sold_shares", "REAL NOT NULL DEFAULT 0"),
    ],
}


async def _migrate(db: aiosqlite.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        async with db.execute(f"PRAGMA table_info({table})") as cur:
            existing = {r["name"] for r in await cur.fetchall()}
        for name, decl in columns:
            if name not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    await db.commit()

    # Collapse any duplicate positions, then enforce one row per
    # (wallet, platform, market_id, side) so wallet syncs can upsert.
    await db.execute(
        """DELETE FROM positions WHERE id NOT IN (
               SELECT MAX(id) FROM positions
               GROUP BY wallet_address, platform, market_id, side
           )"""
    )
    await db.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_pos_unique
           ON positions (wallet_address, platform, market_id, side)"""
    )
    await db.commit()


async def init_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(_SCHEMA)
    await _migrate(db)
    for key, value in _DEFAULT_SETTINGS.items():
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    await db.commit()


async def get_setting(db: aiosqlite.Connection, key: str, default: str | None = None) -> str | None:
    async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row["value"] if row else default


async def set_setting(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


async def get_all_settings(db: aiosqlite.Connection) -> dict[str, str]:
    async with db.execute("SELECT key, value FROM settings") as cur:
        rows = await cur.fetchall()
    return {r["key"]: r["value"] for r in rows}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def wallet_list_from_db(raw: str) -> list[str]:
    try:
        return json.loads(raw)
    except Exception:
        return []
