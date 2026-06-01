"""Application configuration sourced from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global settings. Reads from .env, env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://kalshi:kalshi@localhost:5432/kalshi_ev"

    kalshi_api_base: str = "https://demo-api.kalshi.co/trade-api/v2"
    kalshi_key_id: str = ""
    kalshi_private_key: str = ""

    iproyal_proxy_url: str = ""

    # The Odds API — aggregator covering 7+ US sportsbooks
    odds_api_key: str = ""
    odds_api_base: str = "https://api.the-odds-api.com/v4"

    initial_bankroll_cents: int = 80_000
    scan_interval_seconds: int = 30
    log_level: str = "INFO"

    # Math constants (Section 7 of spec)
    min_ev_threshold: float = 0.01
    suspicious_ev_threshold: float = 0.15
    min_sharp_books: int = 2
    min_kalshi_depth_cents: int = 5000
    kelly_fraction: float = 0.25
    kelly_cap_pct: float = 0.05
    projection_weight_start: float = 0.20
    projection_weight_end: float = 0.40


settings = Settings()
