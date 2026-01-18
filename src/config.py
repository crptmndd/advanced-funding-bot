"""
Configuration module for Funding Rate Arbitrage Bot.

Centralizes all configuration constants and provides easy access
to environment variables and default settings.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path


# =====================================================================
# Environment Variables
# =====================================================================

def _get_env(key: str, default: str = "") -> str:
    """Get environment variable with default."""
    return os.getenv(key, default)


def _get_env_int(key: str, default: int) -> int:
    """Get environment variable as integer."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_float(key: str, default: float) -> float:
    """Get environment variable as float."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_env_bool(key: str, default: bool) -> bool:
    """Get environment variable as boolean."""
    value = os.getenv(key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def _get_env_list(key: str, default: List[str] = None) -> List[str]:
    """Get environment variable as comma-separated list."""
    value = os.getenv(key)
    if value is None:
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


# =====================================================================
# Bot Configuration
# =====================================================================

@dataclass
class BotConfig:
    """Telegram bot configuration."""
    token: str = field(default_factory=lambda: _get_env("TELEGRAM_BOT_TOKEN", ""))
    admin_ids: List[int] = field(default_factory=lambda: [
        int(x) for x in _get_env_list("TELEGRAM_ADMIN_IDS") if x.isdigit()
    ])
    
    # Rate limiting
    rate_limit_requests: int = field(default_factory=lambda: _get_env_int("BOT_RATE_LIMIT_REQUESTS", 30))
    rate_limit_period: int = field(default_factory=lambda: _get_env_int("BOT_RATE_LIMIT_PERIOD", 60))


# =====================================================================
# Database Configuration
# =====================================================================

@dataclass
class DatabaseConfig:
    """Database configuration."""
    path: str = field(default_factory=lambda: _get_env(
        "DATABASE_PATH",
        str(Path(__file__).parent.parent / "data" / "funding_bot.db")
    ))
    
    # Auto-create HyperLiquid API key (requires deposit first)
    auto_create_hl_api_key: bool = field(default_factory=lambda: _get_env_bool(
        "AUTO_CREATE_HL_API_KEY", False
    ))


# =====================================================================
# Exchange Configuration
# =====================================================================

@dataclass
class ExchangeConfig:
    """Exchange-related configuration."""
    
    # Default funding interval in hours (most exchanges use 8h)
    default_funding_interval_hours: int = field(default_factory=lambda: _get_env_int(
        "DEFAULT_FUNDING_INTERVAL_HOURS", 8
    ))
    
    # API request timeout in seconds
    api_timeout: float = field(default_factory=lambda: _get_env_float(
        "EXCHANGE_API_TIMEOUT", 30.0
    ))
    
    # Default exchanges to fetch from (comma-separated)
    # If empty, fetches from all available exchanges
    default_exchanges: List[str] = field(default_factory=lambda: _get_env_list(
        "DEFAULT_EXCHANGES"
    ))
    
    # Exchanges to exclude from fetching
    excluded_exchanges: List[str] = field(default_factory=lambda: _get_env_list(
        "EXCLUDED_EXCHANGES"
    ))
    
    # Cache duration for funding rates in seconds
    funding_rate_cache_ttl: int = field(default_factory=lambda: _get_env_int(
        "FUNDING_RATE_CACHE_TTL", 300  # 5 minutes
    ))
    
    # Background fetch interval in seconds
    background_fetch_interval: int = field(default_factory=lambda: _get_env_int(
        "BACKGROUND_FETCH_INTERVAL", 180  # 3 minutes
    ))
    
    # Enable background fetching
    enable_background_fetch: bool = field(default_factory=lambda: _get_env_bool(
        "ENABLE_BACKGROUND_FETCH", True
    ))


# =====================================================================
# Trading Configuration (Default User Settings)
# =====================================================================

@dataclass
class TradingDefaults:
    """Default trading settings for new users."""
    
    # Default trade amount in USDT
    trade_amount_usdt: float = field(default_factory=lambda: _get_env_float(
        "DEFAULT_TRADE_AMOUNT_USDT", 100.0
    ))
    
    # Maximum trade amount in USDT
    max_trade_amount_usdt: float = field(default_factory=lambda: _get_env_float(
        "DEFAULT_MAX_TRADE_AMOUNT_USDT", 1000.0
    ))
    
    # Maximum leverage
    max_leverage: int = field(default_factory=lambda: _get_env_int(
        "DEFAULT_MAX_LEVERAGE", 10
    ))
    
    # Maximum position size as percent of account
    max_position_size_percent: float = field(default_factory=lambda: _get_env_float(
        "DEFAULT_MAX_POSITION_PERCENT", 50.0
    ))


# =====================================================================
# Arbitrage Configuration (Default Settings)
# =====================================================================

@dataclass
class ArbitrageDefaults:
    """Default arbitrage analyzer settings."""
    
    # Minimum funding rate spread to consider (as percentage, e.g., 0.01 = 0.01%)
    min_funding_spread: float = field(default_factory=lambda: _get_env_float(
        "DEFAULT_MIN_FUNDING_SPREAD", 0.01
    ))
    
    # Maximum price spread to consider safe (as percentage)
    max_price_spread: float = field(default_factory=lambda: _get_env_float(
        "DEFAULT_MAX_PRICE_SPREAD", 1.0
    ))
    
    # Minimum 24h volume in USD
    min_volume_24h: float = field(default_factory=lambda: _get_env_float(
        "DEFAULT_MIN_VOLUME_24H", 100000.0
    ))
    
    # Default number of opportunities to show
    default_limit: int = field(default_factory=lambda: _get_env_int(
        "DEFAULT_ARBITRAGE_LIMIT", 10
    ))
    
    # Notification threshold for spread (send alert if above this)
    notify_threshold_spread: float = field(default_factory=lambda: _get_env_float(
        "DEFAULT_NOTIFY_THRESHOLD_SPREAD", 0.05
    ))


# =====================================================================
# Network Configuration
# =====================================================================

@dataclass
class NetworkConfig:
    """Blockchain network configuration."""
    
    # Arbitrum RPC URL
    arbitrum_rpc_url: str = field(default_factory=lambda: _get_env(
        "ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc"
    ))
    
    # HyperLiquid API URLs
    hyperliquid_mainnet_url: str = field(default_factory=lambda: _get_env(
        "HYPERLIQUID_MAINNET_URL", "https://api.hyperliquid.xyz"
    ))
    hyperliquid_testnet_url: str = field(default_factory=lambda: _get_env(
        "HYPERLIQUID_TESTNET_URL", "https://api.hyperliquid-testnet.xyz"
    ))
    
    # USDC contract addresses on Arbitrum
    usdc_contract: str = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
    usdc_e_contract: str = "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"


# =====================================================================
# Withdrawal Tracking Configuration
# =====================================================================

@dataclass
class WithdrawalConfig:
    """Withdrawal tracking configuration."""
    
    # Maximum tracking time in seconds
    max_tracking_time: int = field(default_factory=lambda: _get_env_int(
        "WITHDRAWAL_MAX_TRACKING_TIME", 900  # 15 minutes
    ))
    
    # Check interval in seconds
    check_interval: int = field(default_factory=lambda: _get_env_int(
        "WITHDRAWAL_CHECK_INTERVAL", 15
    ))
    
    # Required confirmations
    required_confirmations: int = field(default_factory=lambda: _get_env_int(
        "WITHDRAWAL_REQUIRED_CONFIRMATIONS", 1
    ))


# =====================================================================
# Main Config Class
# =====================================================================

@dataclass
class Config:
    """Main configuration container."""
    bot: BotConfig = field(default_factory=BotConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingDefaults = field(default_factory=TradingDefaults)
    arbitrage: ArbitrageDefaults = field(default_factory=ArbitrageDefaults)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    withdrawal: WithdrawalConfig = field(default_factory=WithdrawalConfig)


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload configuration from environment."""
    global _config
    _config = Config()
    return _config


# =====================================================================
# Convenience accessors
# =====================================================================

# Shortcuts for commonly used configs
def get_bot_token() -> str:
    return get_config().bot.token


def get_database_path() -> str:
    return get_config().database.path


def get_funding_interval() -> int:
    return get_config().exchange.default_funding_interval_hours


def get_api_timeout() -> float:
    return get_config().exchange.api_timeout


def get_min_funding_spread() -> float:
    return get_config().arbitrage.min_funding_spread


def get_min_volume_24h() -> float:
    return get_config().arbitrage.min_volume_24h

