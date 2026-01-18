"""
Centralized configuration for the Funding Rate Bot.

All constants, thresholds, and settings are defined here.
Values can be overridden via environment variables.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path


def _env_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


def _env_int(key: str, default: int) -> int:
    """Get integer from environment variable."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    """Get float from environment variable."""
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_list(key: str, default: Optional[List[str]] = None) -> List[str]:
    """Get comma-separated list from environment variable."""
    val = os.getenv(key, "")
    if not val:
        return default or []
    return [item.strip() for item in val.split(",") if item.strip()]


@dataclass
class TelegramConfig:
    """Telegram bot configuration."""
    bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    admin_ids: List[int] = field(default_factory=lambda: [
        int(id_) for id_ in _env_list("TELEGRAM_ADMIN_IDS") if id_.isdigit()
    ])


@dataclass
class DatabaseConfig:
    """Database configuration."""
    path: str = field(default_factory=lambda: os.getenv(
        "DATABASE_PATH", 
        str(Path(__file__).parent.parent / "data" / "funding_bot.db")
    ))
    

@dataclass
class FundingConfig:
    """Funding rate related configuration."""
    # Standard funding interval in hours (most exchanges use 8h)
    default_interval_hours: int = field(default_factory=lambda: _env_int("FUNDING_INTERVAL_HOURS", 8))
    
    # Cache settings
    cache_enabled: bool = field(default_factory=lambda: _env_bool("FUNDING_CACHE_ENABLED", True))
    cache_ttl_seconds: int = field(default_factory=lambda: _env_int("FUNDING_CACHE_TTL", 60))  # 1 minute
    background_refresh_interval: int = field(default_factory=lambda: _env_int("FUNDING_REFRESH_INTERVAL", 120))  # 2 minutes
    
    # Request settings
    fetch_timeout: float = field(default_factory=lambda: _env_float("FUNDING_FETCH_TIMEOUT", 30.0))
    
    # Annualization factor for APR calculation
    # Funding is typically paid 3 times per day (8h intervals)
    payments_per_day: int = field(default_factory=lambda: _env_int("FUNDING_PAYMENTS_PER_DAY", 3))
    
    @property
    def annualization_factor(self) -> float:
        """Factor to convert funding rate to APR."""
        return self.payments_per_day * 365


@dataclass
class ArbitrageConfig:
    """Arbitrage analyzer configuration."""
    # Default minimum funding spread to consider (0.01 = 0.01%)
    min_funding_spread: float = field(default_factory=lambda: _env_float("ARB_MIN_FUNDING_SPREAD", 0.01))
    
    # Default minimum 24h volume in USD
    min_volume_24h: float = field(default_factory=lambda: _env_float("ARB_MIN_VOLUME_24H", 100_000))
    
    # Maximum price spread between exchanges (1.0 = 1%)
    max_price_spread: float = field(default_factory=lambda: _env_float("ARB_MAX_PRICE_SPREAD", 1.0))
    
    # Default number of top opportunities to show
    default_limit: int = field(default_factory=lambda: _env_int("ARB_DEFAULT_LIMIT", 10))


@dataclass  
class TradingConfig:
    """Trading configuration and limits."""
    # Default trade amount in USDT
    default_trade_amount: float = field(default_factory=lambda: _env_float("TRADE_DEFAULT_AMOUNT", 100.0))
    
    # Maximum trade amount in USDT
    max_trade_amount: float = field(default_factory=lambda: _env_float("TRADE_MAX_AMOUNT", 10_000.0))
    
    # Maximum leverage allowed
    max_leverage: int = field(default_factory=lambda: _env_int("TRADE_MAX_LEVERAGE", 20))
    
    # Default leverage if not specified
    default_leverage: int = field(default_factory=lambda: _env_int("TRADE_DEFAULT_LEVERAGE", 5))
    
    # Maximum position size as percentage of account
    max_position_percent: float = field(default_factory=lambda: _env_float("TRADE_MAX_POSITION_PERCENT", 50.0))


@dataclass
class NetworkConfig:
    """Blockchain network configuration."""
    # Arbitrum RPC URL
    arbitrum_rpc_url: str = field(default_factory=lambda: os.getenv(
        "ARBITRUM_RPC_URL", 
        "https://arb1.arbitrum.io/rpc"
    ))
    
    # USDC contracts on Arbitrum
    usdc_contract: str = field(default_factory=lambda: os.getenv(
        "USDC_CONTRACT",
        "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
    ))
    usdc_e_contract: str = field(default_factory=lambda: os.getenv(
        "USDC_E_CONTRACT", 
        "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"
    ))


@dataclass
class WithdrawalConfig:
    """Withdrawal tracking configuration."""
    check_interval: int = field(default_factory=lambda: _env_int("WITHDRAWAL_CHECK_INTERVAL", 15))  # seconds
    max_tracking_time: int = field(default_factory=lambda: _env_int("WITHDRAWAL_MAX_TRACKING_TIME", 900))  # 15 minutes
    required_confirmations: int = field(default_factory=lambda: _env_int("WITHDRAWAL_REQUIRED_CONFIRMATIONS", 1))


@dataclass
class ExchangeConfig:
    """Exchange-specific configuration."""
    # Exchanges to enable (empty = all)
    enabled_exchanges: List[str] = field(default_factory=lambda: _env_list("ENABLED_EXCHANGES"))
    
    # Exchanges to disable
    disabled_exchanges: List[str] = field(default_factory=lambda: _env_list("DISABLED_EXCHANGES"))
    
    # Use instance caching for exchanges
    use_cache: bool = field(default_factory=lambda: _env_bool("EXCHANGE_USE_CACHE", True))
    
    # Auto-close sessions after fetch
    auto_close_sessions: bool = field(default_factory=lambda: _env_bool("EXCHANGE_AUTO_CLOSE", True))


@dataclass
class Config:
    """Main configuration class."""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    funding: FundingConfig = field(default_factory=FundingConfig)
    arbitrage: ArbitrageConfig = field(default_factory=ArbitrageConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    withdrawal: WithdrawalConfig = field(default_factory=WithdrawalConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    
    # Debug mode
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", False))
    
    # Log level
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload configuration from environment."""
    global _config
    _config = Config()
    return _config

