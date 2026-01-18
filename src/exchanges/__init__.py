"""Exchange connectors for funding rate data and trading."""

from .base import BaseExchange
from .registry import ExchangeRegistry, get_exchange, get_all_exchanges
from .hyperliquid_auth import (
    create_agent_key,
    register_agent_with_hyperliquid,
    create_and_register_agent_key,
    HyperliquidAgentKey,
)
from .hyperliquid_trading import (
    HyperliquidTradingClient,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderResult,
    Position,
    AccountState,
    create_hyperliquid_client_for_user,
)
from .arbitrum_bridge import (
    get_usdc_balance,
    get_eth_balance,
    deposit_usdc_to_hyperliquid,
    MIN_DEPOSIT_USDC,
    HYPERLIQUID_BRIDGE_ADDRESS,
)

__all__ = [
    # Base
    "BaseExchange",
    "ExchangeRegistry",
    "get_exchange",
    "get_all_exchanges",
    # HyperLiquid Auth
    "create_agent_key",
    "register_agent_with_hyperliquid",
    "create_and_register_agent_key",
    "HyperliquidAgentKey",
    # HyperLiquid Trading
    "HyperliquidTradingClient",
    "OrderSide",
    "OrderType",
    "TimeInForce",
    "OrderResult",
    "Position",
    "AccountState",
    "create_hyperliquid_client_for_user",
    # Arbitrum Bridge
    "get_usdc_balance",
    "get_eth_balance",
    "deposit_usdc_to_hyperliquid",
    "MIN_DEPOSIT_USDC",
    "HYPERLIQUID_BRIDGE_ADDRESS",
]

