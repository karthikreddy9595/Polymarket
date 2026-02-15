"""Configuration management using pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Find the .env file - check current dir, parent dir, and grandparent dir
def find_env_file() -> Path:
    """Find the .env file in common locations."""
    current = Path.cwd()
    candidates = [
        current / ".env",
        current.parent / ".env",
        current.parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",  # polymarket_bot/.env
    ]
    for path in candidates:
        if path.exists():
            return path
    return Path(".env")  # fallback

ENV_FILE = find_env_file()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Polymarket Credentials
    private_key: str = Field(default="", description="Wallet private key")
    polymarket_api_key: str = Field(default="", description="Polymarket API key")
    polymarket_api_secret: str = Field(default="", description="Polymarket API secret")
    polymarket_api_passphrase: str = Field(default="", description="Polymarket API passphrase")
    funder_address: str = Field(default="", description="Proxy wallet address (funder) - find on Polymarket account page")
    signature_type: int = Field(default=1, description="Signature type: 0=EOA, 1=Poly Proxy, 2=Gnosis Safe")

    # Environment
    use_testnet: bool = Field(default=True, description="Use testnet instead of mainnet")
    chain_id: int = Field(default=80002, description="Chain ID: 80002 for testnet, 137 for mainnet")

    # Trading Parameters
    order_size: float = Field(default=100.0, description="Shares per trade")
    buy_price: float = Field(default=0.8, description="Limit buy price (legacy)")
    sell_price: float = Field(default=0.5, description="Sell price after buy fills (legacy)")
    max_loss: float = Field(default=0.3, description="Square off threshold (legacy)")
    price_target: float = Field(default=0.98, description="Sell when price hits this (legacy)")
    time_threshold: int = Field(default=3, description="Minutes before close to start trading")
    max_positions_per_market: int = Field(default=3, description="Maximum positions (buy-sell cycles) per market")

    # Strategy Parameters (configurable entry/exit levels)
    trigger_price: float = Field(default=0.75, description="Entry trigger - buy when price >= this")
    entry_min: float = Field(default=0.78, description="Minimum price for entry signal range (legacy)")
    entry_max: float = Field(default=0.80, description="Maximum price for entry signal range (legacy)")
    stoploss: float = Field(default=0.60, description="Stoploss price - limit sell placed here")
    target: float = Field(default=0.99, description="Target price - limit sell placed here")
    order_cancel_threshold: float = Field(default=0.167, description="Cancel unfilled orders when time to close < this (minutes). Default 10 seconds = 0.167 min")
    reentry_max_price: float = Field(default=0.9, description="Maximum price for re-entry after position cleared - skip if price > this")

    # Fees
    taker_fee_rate: float = Field(default=0.001, description="Taker fee rate (0.001 = 0.10% or 10 basis points)")
    min_taker_fee: float = Field(default=0.001, description="Minimum taker fee in dollars")

    # Paper Trading
    paper_trading: bool = Field(default=True, description="Enable paper trading mode (simulated trades)")
    paper_balance: float = Field(default=1000.0, description="Starting paper trading balance")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/trades.db",
        description="Database connection URL"
    )

    # API
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)")

    # Polling intervals (seconds)
    market_scan_interval: int = Field(default=10, description="Market scanning interval")
    position_check_interval: int = Field(default=2, description="Position monitoring interval")

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    @property
    def polymarket_host(self) -> str:
        """Get the Polymarket API host based on environment."""
        if self.use_testnet:
            return "https://clob.polymarket.com"  # Testnet uses same host
        return "https://clob.polymarket.com"

    @property
    def gamma_host(self) -> str:
        """Get the Gamma API host for market discovery."""
        return "https://gamma-api.polymarket.com"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Loading settings from: {ENV_FILE} (exists: {ENV_FILE.exists()})")
    settings = Settings()
    logger.info(f"Private key loaded: {'Yes' if settings.private_key else 'No'} (length: {len(settings.private_key)})")
    return settings
