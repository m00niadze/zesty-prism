from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "sqlite+aiosqlite:////data/zesty.db"
    DATABASE_PATH: str = "/data/zesty.db"

    PREDICTFUN_API_KEY: str = ""
    POLYMARKET_GAMMA_URL: str = "https://gamma-api.polymarket.com"
    POLYMARKET_CLOB_URL: str = "https://clob.polymarket.com"
    POLYMARKET_DATA_URL: str = "https://data-api.polymarket.com"
    PREDICTFUN_REST_URL: str = "https://api.predict.fun"
    PREDICTFUN_WS_URL: str = "wss://ws.predict.fun/ws"

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    INTERNAL_ALERT_SECRET: str = "changeme"
    BOT_INTERNAL_URL: str = "http://bot:8001/internal/alert"

    WALLET_ADDRESSES: str = ""

    MIN_MATCH_SCORE: float = 82.0
    MIN_ARB_PCT: float = 1.0
    MIN_PROFIT_USD: float = 10.0
    # Minimum executable book depth (Max profitable size in $) before an arb is
    # worth alerting on — thin few-dollar crosses vanish before you can trade.
    MIN_WAGER_USD: float = 30.0
    NOTIONAL_USD: float = 100.0

    # Taker fees. Polymarket: per-market category rate (crypto 7%, sports 3%,
    # politics/finance/tech 4%, economics/culture/other 5%, geopolitics 0) applied
    # via the documented formula fee = rate * shares * p * (1-p); the rate is
    # derived from each market's tags in market_matcher and stored per market.
    # Predict.fun: flat % of cost from its API feeRateBps, falling back to this.
    PF_FALLBACK_FEE_BPS: float = 200.0

    POLL_INTERVAL_POLY_SECONDS: int = 3
    # Re-discover/re-match all markets often so brand-new markets (and their arb
    # windows) are caught fast. The full PF fetch is sequential (one stream), so
    # frequent runs add little rate-limit load — mostly just time.
    MARKET_SYNC_INTERVAL_SECONDS: int = 120
    PORTFOLIO_SYNC_INTERVAL_SECONDS: int = 120
    OPPORTUNITY_EXPIRY_SECONDS: int = 10
    PRICE_STALENESS_SECONDS: int = 30
    TAKER_REFRESH_SECONDS: int = 3
    # If a Predict.fun order book hasn't changed in this long, the "arb" is a
    # dead/illiquid cross (a stale resting order nobody takes), not something you
    # can actually trade — don't keep it live or alert on it.
    BOOK_MAX_AGE_SECONDS: int = 90

    @property
    def wallet_list(self) -> list[str]:
        if not self.WALLET_ADDRESSES:
            return []
        return [w.strip() for w in self.WALLET_ADDRESSES.split(",") if w.strip()]


settings = Settings()
