import aiosqlite

DB_PATH = "/data/zesty.db"


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
