"""
HyperLiquid Trading Client.

This module provides a trading client for HyperLiquid DEX.
It handles order placement, position management, and account queries.

Uses the official hyperliquid-python-sdk for reliable order signing.
"""

import time
import json
import logging
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from enum import Enum

import aiohttp
from eth_account import Account

# Import official HyperLiquid SDK
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants

# Logger
logger = logging.getLogger(__name__)


# HyperLiquid API endpoints
HYPERLIQUID_MAINNET_API = "https://api.hyperliquid.xyz"
HYPERLIQUID_TESTNET_API = "https://api.hyperliquid-testnet.xyz"


class OrderSide(Enum):
    """Order side."""
    BUY = "B"
    SELL = "A"  # Ask


class OrderType(Enum):
    """Order type."""
    LIMIT = "Limit"
    MARKET = "Market"
    STOP_LIMIT = "Stop Limit"
    STOP_MARKET = "Stop Market"
    TAKE_PROFIT_LIMIT = "Take Profit Limit"
    TAKE_PROFIT_MARKET = "Take Profit Market"


class TimeInForce(Enum):
    """Time in force options."""
    GTC = "Gtc"  # Good Till Cancel
    IOC = "Ioc"  # Immediate Or Cancel
    ALO = "Alo"  # Add Liquidity Only (Post-Only)


@dataclass
class OrderResult:
    """Result of an order operation."""
    success: bool
    order_id: Optional[str] = None
    status: Optional[str] = None
    filled_size: float = 0.0
    average_price: Optional[float] = None
    error: Optional[str] = None
    raw_response: Optional[Dict] = None


@dataclass
class Position:
    """Represents a trading position."""
    symbol: str
    size: float  # Positive = long, negative = short
    entry_price: float
    mark_price: float
    liquidation_price: Optional[float]
    unrealized_pnl: float
    margin_used: float
    leverage: int


@dataclass
class AccountState:
    """Account state information."""
    account_value: float
    margin_used: float
    available_balance: float
    positions: List[Position]
    withdrawable: float


class HyperliquidTradingClient:
    """
    Trading client for HyperLiquid DEX.
    
    Handles order placement, cancellation, and position management.
    Uses the official hyperliquid-python-sdk for reliable order signing.
    """
    
    def __init__(
        self,
        main_wallet_address: str,
        agent_private_key: str,
        is_mainnet: bool = True,
    ):
        """
        Initialize the trading client.
        
        Args:
            main_wallet_address: Address of the main wallet (used for account context)
            agent_private_key: Private key of the agent (API) wallet
            is_mainnet: Whether to use mainnet or testnet
        """
        self.main_wallet_address = main_wallet_address
        self.is_mainnet = is_mainnet
        
        # Ensure private key has 0x prefix
        if not agent_private_key.startswith("0x"):
            agent_private_key = "0x" + agent_private_key
        
        self._agent_account = Account.from_key(agent_private_key)
        self._agent_address = self._agent_account.address
        
        self.api_url = HYPERLIQUID_MAINNET_API if is_mainnet else HYPERLIQUID_TESTNET_API
        
        # Initialize official SDK Exchange client
        # The agent wallet is used for signing, account_address is the main wallet
        self._exchange = Exchange(
            wallet=self._agent_account,
            base_url=self.api_url,
            account_address=main_wallet_address,
        )
        
        # Info client for market data
        self._info = Info(self.api_url, skip_ws=True)
        
        # Cache for asset info (symbol -> coin index mapping)
        self._asset_info_cache: Dict[str, Dict] = {}
        self._asset_info_loaded: bool = False
        
        logger.info(f"[HyperLiquid Trading] Initialized client")
        logger.info(f"[HyperLiquid Trading] Main wallet: {self.main_wallet_address[:10]}...")
        logger.info(f"[HyperLiquid Trading] Agent wallet: {self._agent_address[:10]}...")
        logger.info(f"[HyperLiquid Trading] Network: {'Mainnet' if is_mainnet else 'Testnet'}")
    
    def _get_nonce(self) -> int:
        """Get current timestamp in milliseconds as nonce."""
        return int(time.time() * 1000)
    
    async def _load_asset_info(self) -> None:
        """Load asset information from HyperLiquid API."""
        if self._asset_info_loaded:
            return
        
        logger.info("[HyperLiquid Trading] Loading asset info...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/info",
                    json={"type": "meta"},
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        universe = data.get("universe", [])
                        
                        for idx, asset in enumerate(universe):
                            coin_name = asset.get("name", "")
                            self._asset_info_cache[coin_name] = {
                                "index": idx,
                                "sz_decimals": asset.get("szDecimals", 0),
                                "max_leverage": asset.get("maxLeverage", 50),
                            }
                        
                        self._asset_info_loaded = True
                        logger.info(f"[HyperLiquid Trading] Loaded {len(self._asset_info_cache)} assets")
                    else:
                        logger.error(f"[HyperLiquid Trading] Failed to load asset info: {resp.status}")
                        
        except Exception as e:
            logger.error(f"[HyperLiquid Trading] Error loading asset info: {e}")
    
    def _get_asset_index(self, symbol: str) -> Optional[int]:
        """Get asset index for a symbol (e.g., 'BTC' -> 0)."""
        # Normalize symbol
        symbol = symbol.upper().replace("/USD", "").replace(":USD", "").replace("USDT", "").replace("PERP", "")
        return self._asset_info_cache.get(symbol, {}).get("index")
    
    def _get_sz_decimals(self, symbol: str) -> int:
        """Get size decimals for a symbol."""
        symbol = symbol.upper().replace("/USD", "").replace(":USD", "").replace("USDT", "").replace("PERP", "")
        return self._asset_info_cache.get(symbol, {}).get("sz_decimals", 0)
    
    def _round_size(self, size: float, symbol: str) -> float:
        """Round size to appropriate decimals for the asset."""
        sz_decimals = self._get_sz_decimals(symbol)
        return round(size, sz_decimals)
    
    def _round_price(self, price: float) -> str:
        """Round price to 5 significant figures (HyperLiquid requirement)."""
        # HyperLiquid requires prices with at most 5 significant figures
        if price == 0:
            return "0"
        
        # Find the order of magnitude
        from math import log10, floor
        magnitude = floor(log10(abs(price)))
        
        # Round to 5 significant figures
        factor = 10 ** (magnitude - 4)
        rounded = round(price / factor) * factor
        
        # Format without unnecessary decimals
        if magnitude >= 4:
            return str(int(rounded))
        else:
            decimals = max(0, 4 - magnitude)
            return f"{rounded:.{decimals}f}".rstrip("0").rstrip(".")
    
    async def get_account_state(self) -> Optional[AccountState]:
        """
        Get current account state including positions and balances.
        
        Returns:
            AccountState or None if failed
        """
        logger.info(f"[HyperLiquid Trading] Getting account state for {self.main_wallet_address[:10]}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/info",
                    json={
                        "type": "clearinghouseState",
                        "user": self.main_wallet_address,
                    },
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"[HyperLiquid Trading] Failed to get account state: {resp.status}")
                        return None
                    
                    data = await resp.json()
                    
                    # Parse positions
                    positions = []
                    for pos_data in data.get("assetPositions", []):
                        pos = pos_data.get("position", {})
                        if float(pos.get("szi", 0)) != 0:
                            positions.append(Position(
                                symbol=pos.get("coin", ""),
                                size=float(pos.get("szi", 0)),
                                entry_price=float(pos.get("entryPx", 0)),
                                mark_price=float(pos.get("markPx", 0)),
                                liquidation_price=float(pos.get("liquidationPx")) if pos.get("liquidationPx") else None,
                                unrealized_pnl=float(pos.get("unrealizedPnl", 0)),
                                margin_used=float(pos.get("marginUsed", 0)),
                                leverage=int(pos.get("leverage", {}).get("value", 1)),
                            ))
                    
                    # Parse margin summary
                    margin = data.get("marginSummary", {})
                    
                    account_state = AccountState(
                        account_value=float(margin.get("accountValue", 0)),
                        margin_used=float(margin.get("totalMarginUsed", 0)),
                        available_balance=float(margin.get("availableBalance", 0)),
                        positions=positions,
                        withdrawable=float(data.get("withdrawable", 0)),
                    )
                    
                    logger.info(f"[HyperLiquid Trading] Account value: ${account_state.account_value:,.2f}")
                    logger.info(f"[HyperLiquid Trading] Available: ${account_state.available_balance:,.2f}")
                    logger.info(f"[HyperLiquid Trading] Open positions: {len(positions)}")
                    
                    return account_state
                    
        except Exception as e:
            logger.exception(f"[HyperLiquid Trading] Error getting account state")
            return None
    
    async def get_open_orders(self) -> List[Dict]:
        """
        Get all open orders.
        
        Returns:
            List of open order dictionaries
        """
        logger.info(f"[HyperLiquid Trading] Getting open orders...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/info",
                    json={
                        "type": "openOrders",
                        "user": self.main_wallet_address,
                    },
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status == 200:
                        orders = await resp.json()
                        logger.info(f"[HyperLiquid Trading] Found {len(orders)} open orders")
                        return orders
                    else:
                        logger.error(f"[HyperLiquid Trading] Failed to get orders: {resp.status}")
                        return []
                        
        except Exception as e:
            logger.exception(f"[HyperLiquid Trading] Error getting open orders")
            return []
    
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.LIMIT,
        time_in_force: TimeInForce = TimeInForce.GTC,
        reduce_only: bool = False,
        slippage: float = 0.05,  # 5% slippage for market orders (SDK default)
    ) -> OrderResult:
        """
        Place an order on HyperLiquid using official SDK.
        
        Args:
            symbol: Trading symbol (e.g., "BTC", "ETH")
            side: BUY or SELL
            size: Order size in base currency
            price: Limit price (required for limit orders, optional for market)
            order_type: Order type (LIMIT, MARKET, etc.)
            time_in_force: Time in force (GTC, IOC, ALO)
            reduce_only: Whether this order can only reduce position
            slippage: Slippage tolerance for market orders (default 5%)
            
        Returns:
            OrderResult with order details or error
        """
        # Normalize symbol
        symbol_clean = symbol.upper().replace("/USD", "").replace(":USD", "").replace("USDT", "").replace("PERP", "")
        
        logger.info(f"[HyperLiquid Trading] === Placing Order via SDK ===")
        logger.info(f"[HyperLiquid Trading] Symbol: {symbol_clean}")
        logger.info(f"[HyperLiquid Trading] Side: {side.name}")
        logger.info(f"[HyperLiquid Trading] Size: {size}")
        logger.info(f"[HyperLiquid Trading] Price: {price}")
        logger.info(f"[HyperLiquid Trading] Type: {order_type.value}")
        logger.info(f"[HyperLiquid Trading] TIF: {time_in_force.value}")
        logger.info(f"[HyperLiquid Trading] Reduce only: {reduce_only}")
        
        is_buy = side == OrderSide.BUY
        
        try:
            # Use SDK for order placement (run in thread as SDK is synchronous)
            if order_type == OrderType.MARKET or price is None:
                # Market order using SDK's market_open
                logger.info(f"[HyperLiquid Trading] Placing market order with slippage {slippage*100}%")
                response = await asyncio.to_thread(
                    self._exchange.market_open,
                    symbol_clean,
                    is_buy,
                    size,
                    None,  # px - SDK will get mid price
                    slippage,
                )
            else:
                # Limit order
                sdk_order_type = {"limit": {"tif": time_in_force.value}}
                logger.info(f"[HyperLiquid Trading] Placing limit order at {price}")
                response = await asyncio.to_thread(
                    self._exchange.order,
                    symbol_clean,
                    is_buy,
                    size,
                    price,
                    sdk_order_type,
                    reduce_only,
                )
            
            logger.info(f"[HyperLiquid Trading] SDK Response: {response}")
            
            # Parse SDK response
            if response.get("status") == "ok":
                response_data = response.get("response", {})
                if isinstance(response_data, dict):
                    statuses = response_data.get("data", {}).get("statuses", [])
                    if statuses:
                        status = statuses[0]
                        if "filled" in status:
                            filled = status["filled"]
                            logger.info(f"[HyperLiquid Trading] Order filled! OID: {filled.get('oid')}")
                            return OrderResult(
                                success=True,
                                order_id=str(filled.get("oid", "")),
                                status="filled",
                                filled_size=float(filled.get("totalSz", 0)),
                                average_price=float(filled.get("avgPx", 0)),
                                raw_response=response,
                            )
                        elif "resting" in status:
                            resting = status["resting"]
                            logger.info(f"[HyperLiquid Trading] Order resting! OID: {resting.get('oid')}")
                            return OrderResult(
                                success=True,
                                order_id=str(resting.get("oid", "")),
                                status="resting",
                                raw_response=response,
                            )
                        elif "error" in status:
                            error_msg = status["error"]
                            logger.error(f"[HyperLiquid Trading] Order error: {error_msg}")
                            return OrderResult(
                                success=False,
                                error=error_msg,
                                raw_response=response,
                            )
                
                return OrderResult(
                    success=True,
                    status="submitted",
                    raw_response=response,
                )
            else:
                error = response.get("response", str(response))
                logger.error(f"[HyperLiquid Trading] Order failed: {error}")
                return OrderResult(
                    success=False,
                    error=str(error),
                    raw_response=response,
                )
                
        except Exception as e:
            logger.exception(f"[HyperLiquid Trading] Exception placing order")
            return OrderResult(
                success=False,
                error=str(e),
            )
    
    async def _get_mark_price(self, symbol: str) -> Optional[float]:
        """Get current mark price for a symbol using SDK."""
        symbol_clean = symbol.upper().replace("/USD", "").replace(":USD", "").replace("USDT", "").replace("PERP", "")
        
        try:
            # Use SDK's Info client to get mid price (run in thread as SDK is synchronous)
            all_mids = await asyncio.to_thread(self._info.all_mids)
            
            if symbol_clean in all_mids:
                price = float(all_mids[symbol_clean])
                logger.info(f"[HyperLiquid Trading] Got mid price for {symbol_clean}: ${price:,.2f}")
                return price
            else:
                logger.error(f"[HyperLiquid Trading] Symbol {symbol_clean} not found in mids")
                return None
                            
        except Exception as e:
            logger.error(f"[HyperLiquid Trading] Error getting mark price: {e}")
        
        return None
    
    async def cancel_order(self, symbol: str, order_id: int) -> OrderResult:
        """
        Cancel an open order using official SDK.
        
        Args:
            symbol: Trading symbol
            order_id: Order ID to cancel
            
        Returns:
            OrderResult indicating success or failure
        """
        symbol_clean = symbol.upper().replace("/USD", "").replace(":USD", "").replace("USDT", "").replace("PERP", "")
        
        logger.info(f"[HyperLiquid Trading] Cancelling order {order_id} for {symbol_clean}")
        
        try:
            # Use SDK for cancel (run in thread as SDK is synchronous)
            response = await asyncio.to_thread(
                self._exchange.cancel,
                symbol_clean,
                order_id,
            )
            
            logger.info(f"[HyperLiquid Trading] Cancel response: {response}")
            
            if response.get("status") == "ok":
                return OrderResult(
                    success=True,
                    order_id=str(order_id),
                    status="cancelled",
                    raw_response=response,
                )
            else:
                error = response.get("response", str(response))
                return OrderResult(
                    success=False,
                    error=str(error),
                    raw_response=response,
                )
        
        except Exception as e:
            logger.exception(f"[HyperLiquid Trading] Exception cancelling order")
            return OrderResult(
                success=False,
                error=str(e),
            )
    
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> List[OrderResult]:
        """
        Cancel all open orders, optionally for a specific symbol.
        
        Args:
            symbol: Optional symbol to cancel orders for
            
        Returns:
            List of OrderResult for each cancellation
        """
        logger.info(f"[HyperLiquid Trading] Cancelling all orders{f' for {symbol}' if symbol else ''}")
        
        # Get all open orders
        open_orders = await self.get_open_orders()
        
        if not open_orders:
            logger.info("[HyperLiquid Trading] No open orders to cancel")
            return []
        
        results = []
        for order in open_orders:
            order_symbol = order.get("coin", "")
            order_id = order.get("oid")
            
            if symbol and order_symbol.upper() != symbol.upper():
                continue
            
            if order_id:
                result = await self.cancel_order(order_symbol, order_id)
                results.append(result)
        
        logger.info(f"[HyperLiquid Trading] Cancelled {len(results)} orders")
        return results
    
    async def set_leverage(self, symbol: str, leverage: int, is_cross: bool = True) -> bool:
        """
        Set leverage for a symbol using official SDK.
        
        Args:
            symbol: Trading symbol
            leverage: Leverage value (e.g., 10 for 10x)
            is_cross: True for cross margin, False for isolated
            
        Returns:
            True if successful
        """
        symbol_clean = symbol.upper().replace("/USD", "").replace(":USD", "").replace("USDT", "").replace("PERP", "")
        
        logger.info(f"[HyperLiquid Trading] Setting leverage for {symbol_clean} to {leverage}x ({'cross' if is_cross else 'isolated'})")
        
        try:
            # Use SDK for leverage update
            response = await asyncio.to_thread(
                self._exchange.update_leverage,
                leverage,
                symbol_clean,
                is_cross,
            )
            
            logger.info(f"[HyperLiquid Trading] Leverage response: {response}")
            
            if response.get("status") == "ok":
                logger.info(f"[HyperLiquid Trading] Leverage set successfully")
                return True
            else:
                logger.error(f"[HyperLiquid Trading] Failed to set leverage: {response}")
                return False
                
        except Exception as e:
            logger.exception(f"[HyperLiquid Trading] Exception setting leverage")
            return False
    
    async def withdraw_from_bridge(
        self,
        amount_usd: float,
        destination_address: Optional[str] = None,
        main_wallet_private_key: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Withdraw USDC from HyperLiquid to Arbitrum bridge.
        
        Note: Withdrawals MUST be signed by the main wallet, not an agent.
        If main_wallet_private_key is provided, it will be used for signing.
        
        Args:
            amount_usd: Amount in USD to withdraw (will be reduced by ~1 USDC fee)
            destination_address: Optional destination address (defaults to main wallet)
            main_wallet_private_key: Main wallet private key for signing withdrawal
            
        Returns:
            Tuple of (success, error_message or None, raw_response or None)
        """
        dest = destination_address or self.main_wallet_address
        
        logger.info(f"[HyperLiquid Trading] Withdrawing ${amount_usd} to {dest[:10]}...")
        
        try:
            # For withdrawal, we need to create a separate Exchange instance with main wallet
            # because agents don't have permission to withdraw
            if main_wallet_private_key:
                # Ensure private key has 0x prefix
                if not main_wallet_private_key.startswith("0x"):
                    main_wallet_private_key = "0x" + main_wallet_private_key
                
                main_account = Account.from_key(main_wallet_private_key)
                
                # Create Exchange instance with main wallet (not agent)
                withdraw_exchange = Exchange(
                    wallet=main_account,
                    base_url=self.api_url,
                    account_address=self.main_wallet_address,
                )
                
                logger.info(f"[HyperLiquid Trading] Using main wallet for withdrawal")
                
                # Use main wallet Exchange for withdrawal
                response = await asyncio.to_thread(
                    withdraw_exchange.withdraw_from_bridge,
                    amount_usd,
                    dest,
                )
            else:
                # Fallback to agent (will likely fail)
                logger.warning(
                    "[HyperLiquid Trading] No main wallet key provided - "
                    "withdrawal may fail as agents cannot withdraw"
                )
                response = await asyncio.to_thread(
                    self._exchange.withdraw_from_bridge,
                    amount_usd,
                    dest,
                )
            
            logger.info(f"[HyperLiquid Trading] Withdraw response: {response}")
            
            if response.get("status") == "ok":
                logger.info(f"[HyperLiquid Trading] Withdrawal initiated successfully")
                return True, None, response
            else:
                error = response.get("response", str(response))
                logger.error(f"[HyperLiquid Trading] Withdrawal failed: {error}")
                return False, str(error), response
                
        except Exception as e:
            logger.exception(f"[HyperLiquid Trading] Exception during withdrawal")
            return False, str(e), None
    
async def create_hyperliquid_client_for_user(
    db,
    user_id: int,
    is_mainnet: bool = True,
) -> Optional[HyperliquidTradingClient]:
    """
    Create a HyperLiquid trading client for a user.
    
    This helper function retrieves the necessary credentials from the database
    and creates a configured trading client.
    
    Args:
        db: Database instance
        user_id: User ID
        is_mainnet: Whether to use mainnet or testnet
        
    Returns:
        HyperliquidTradingClient or None if credentials not found
    """
    from src.database import WalletType
    
    logger.info(f"[HyperLiquid] Creating trading client for user {user_id}")
    
    # Get user's EVM wallet
    wallet = await db.get_user_wallet(user_id, WalletType.EVM)
    if not wallet:
        logger.error(f"[HyperLiquid] No EVM wallet found for user {user_id}")
        return None
    
    # Get HyperLiquid API key
    chain = "Mainnet" if is_mainnet else "Testnet"
    api_key = await db.get_hyperliquid_api_key(user_id, chain)
    
    if not api_key or not api_key.is_valid:
        logger.error(f"[HyperLiquid] No valid API key found for user {user_id}")
        return None
    
    # Get agent private key
    agent_private_key = await db.get_hyperliquid_api_key_private_key(api_key.id)
    if not agent_private_key:
        logger.error(f"[HyperLiquid] Failed to decrypt agent private key for user {user_id}")
        return None
    
    # Create client
    client = HyperliquidTradingClient(
        main_wallet_address=wallet.address,
        agent_private_key=agent_private_key,
        is_mainnet=is_mainnet,
    )
    
    logger.info(f"[HyperLiquid] Trading client created for user {user_id}")
    return client

