"""
HyperLiquid Service - High-level service for HyperLiquid operations.

This service provides a high-level interface for:
- Creating and managing HyperLiquid API keys
- Placing orders
- Managing positions
"""

import logging
from datetime import datetime
from typing import Optional, Tuple

from src.database import Database, WalletType, HyperliquidApiKey
from src.exchanges.hyperliquid_auth import (
    create_agent_key,
    register_agent_with_hyperliquid,
    HyperliquidAgentKey,
)
from src.exchanges.hyperliquid_trading import (
    HyperliquidTradingClient,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderResult,
    AccountState,
)

# Logger
logger = logging.getLogger(__name__)


class HyperliquidService:
    """
    High-level service for HyperLiquid operations.
    
    Provides a clean interface for bot commands and other services
    to interact with HyperLiquid.
    """
    
    def __init__(self, db: Database):
        """
        Initialize the service.
        
        Args:
            db: Database instance
        """
        self.db = db
        logger.info("[HyperLiquid Service] Initialized")
    
    async def create_api_key_for_user(
        self,
        user_id: int,
        validity_days: int = 180,
        is_mainnet: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        """
        Create a new HyperLiquid API key for a user.
        
        This will:
        1. Get the user's EVM wallet
        2. Generate a new agent wallet
        3. Sign the agent approval with the main wallet
        4. Register the agent with HyperLiquid
        5. Store the API key in the database
        
        Args:
            user_id: User ID
            validity_days: Number of days the key should be valid (max 180)
            is_mainnet: Whether to create for mainnet or testnet
            
        Returns:
            Tuple of (success, error_message or None)
        """
        chain = "Mainnet" if is_mainnet else "Testnet"
        
        logger.info(f"[HyperLiquid Service] Creating API key for user {user_id}")
        logger.info(f"[HyperLiquid Service] Chain: {chain}, Validity: {validity_days} days")
        
        try:
            # Get user's EVM wallet
            wallet = await self.db.get_user_wallet(user_id, WalletType.EVM)
            if not wallet:
                error = "No EVM wallet found. Please create a wallet first."
                logger.error(f"[HyperLiquid Service] {error}")
                return False, error
            
            logger.info(f"[HyperLiquid Service] Using wallet: {wallet.short_address}")
            
            # Get wallet private key
            private_key = await self.db.get_wallet_private_key(wallet.id)
            if not private_key:
                error = "Failed to retrieve wallet private key."
                logger.error(f"[HyperLiquid Service] {error}")
                return False, error
            
            # Check if user already has an active API key for this chain
            existing_key = await self.db.get_hyperliquid_api_key(user_id, chain)
            if existing_key and existing_key.is_valid:
                logger.info(f"[HyperLiquid Service] User already has valid API key, days left: {existing_key.days_until_expiry}")
                # Optionally deactivate old key and create new one
                # For now, we'll just return success
                return True, None
            
            # Create the agent key
            logger.info(f"[HyperLiquid Service] Creating agent key...")
            agent_key = create_agent_key(
                main_wallet_private_key=private_key,
                validity_days=validity_days,
                chain=chain,
            )
            
            # Register with HyperLiquid
            logger.info(f"[HyperLiquid Service] Registering agent with HyperLiquid...")
            success, error = await register_agent_with_hyperliquid(
                agent_key=agent_key,
                main_wallet_address=wallet.address,
            )
            
            if not success:
                logger.error(f"[HyperLiquid Service] Registration failed: {error}")
                return False, f"Failed to register API key: {error}"
            
            # Save to database
            logger.info(f"[HyperLiquid Service] Saving API key to database...")
            await self.db.save_hyperliquid_api_key(
                user_id=user_id,
                wallet_id=wallet.id,
                agent_address=agent_key.agent_address,
                agent_private_key=agent_key.agent_private_key,
                agent_name=agent_key.agent_name,
                chain=chain,
                valid_until=agent_key.valid_until,
                nonce=agent_key.nonce,
            )
            
            logger.info(f"[HyperLiquid Service] API key created successfully!")
            logger.info(f"[HyperLiquid Service] Agent: {agent_key.agent_address[:10]}...")
            logger.info(f"[HyperLiquid Service] Valid until: {agent_key.valid_until.isoformat()}")
            
            return True, None
            
        except Exception as e:
            logger.exception(f"[HyperLiquid Service] Error creating API key")
            return False, str(e)
    
    async def get_or_create_api_key(
        self,
        user_id: int,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[HyperliquidApiKey], Optional[str]]:
        """
        Get existing API key or create a new one if needed.
        
        Args:
            user_id: User ID
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (api_key or None, error_message or None)
        """
        chain = "Mainnet" if is_mainnet else "Testnet"
        
        # Check for existing valid key
        existing_key = await self.db.get_hyperliquid_api_key(user_id, chain)
        if existing_key and existing_key.is_valid:
            logger.info(f"[HyperLiquid Service] Found existing valid API key for user {user_id}")
            return existing_key, None
        
        # Create new key
        success, error = await self.create_api_key_for_user(
            user_id=user_id,
            is_mainnet=is_mainnet,
        )
        
        if not success:
            return None, error
        
        # Return the newly created key
        new_key = await self.db.get_hyperliquid_api_key(user_id, chain)
        return new_key, None
    
    async def get_trading_client(
        self,
        user_id: int,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[HyperliquidTradingClient], Optional[str]]:
        """
        Get a trading client for a user.
        
        Args:
            user_id: User ID
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (trading_client or None, error_message or None)
        """
        logger.info(f"[HyperLiquid Service] Getting trading client for user {user_id}")
        
        # Get or create API key
        api_key, error = await self.get_or_create_api_key(user_id, is_mainnet)
        if not api_key:
            return None, error
        
        # Get wallet
        wallet = await self.db.get_user_wallet(user_id, WalletType.EVM)
        if not wallet:
            return None, "No EVM wallet found"
        
        # Get agent private key
        agent_private_key = await self.db.get_hyperliquid_api_key_private_key(api_key.id)
        if not agent_private_key:
            return None, "Failed to decrypt agent private key"
        
        # Create client
        client = HyperliquidTradingClient(
            main_wallet_address=wallet.address,
            agent_private_key=agent_private_key,
            is_mainnet=is_mainnet,
        )
        
        logger.info(f"[HyperLiquid Service] Trading client ready")
        return client, None
    
    async def get_account_state(
        self,
        user_id: int,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[AccountState], Optional[str]]:
        """
        Get account state for a user.
        
        Args:
            user_id: User ID
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (account_state or None, error_message or None)
        """
        client, error = await self.get_trading_client(user_id, is_mainnet)
        if not client:
            return None, error
        
        account_state = await client.get_account_state()
        if not account_state:
            return None, "Failed to fetch account state"
        
        return account_state, None
    
    async def place_order(
        self,
        user_id: int,
        symbol: str,
        side: str,  # "buy" or "sell"
        size: float,
        price: Optional[float] = None,
        is_market: bool = False,
        reduce_only: bool = False,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[OrderResult], Optional[str]]:
        """
        Place an order for a user.
        
        Args:
            user_id: User ID
            symbol: Trading symbol (e.g., "BTC", "ETH")
            side: "buy" or "sell"
            size: Order size
            price: Limit price (optional for market orders)
            is_market: Whether this is a market order
            reduce_only: Whether this order can only reduce position
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (order_result or None, error_message or None)
        """
        logger.info(f"[HyperLiquid Service] Placing {side} order for user {user_id}")
        logger.info(f"[HyperLiquid Service] Symbol: {symbol}, Size: {size}, Price: {price}")
        
        client, error = await self.get_trading_client(user_id, is_mainnet)
        if not client:
            return None, error
        
        # Convert side string to enum
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        
        # Determine order type
        order_type = OrderType.MARKET if is_market else OrderType.LIMIT
        
        # Place the order
        result = await client.place_order(
            symbol=symbol,
            side=order_side,
            size=size,
            price=price,
            order_type=order_type,
            reduce_only=reduce_only,
        )
        
        if result.success:
            logger.info(f"[HyperLiquid Service] Order placed successfully: {result.order_id}")
        else:
            logger.error(f"[HyperLiquid Service] Order failed: {result.error}")
        
        return result, result.error if not result.success else None
    
    async def place_order_by_margin(
        self,
        user_id: int,
        symbol: str,
        side: str,  # "buy" or "sell"
        margin_usdt: float,
        leverage: int,
        price: Optional[float] = None,
        is_market: bool = False,
        reduce_only: bool = False,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[OrderResult], Optional[str]]:
        """
        Place an order for a user specifying the margin amount in USDT.
        
        Position size is calculated as: margin × leverage / price
        
        Args:
            user_id: User ID
            symbol: Trading symbol (e.g., "BTC", "ETH")
            side: "buy" or "sell"
            margin_usdt: Margin amount in USDT
            leverage: Leverage to use (e.g., 10 for 10x)
            price: Limit price (optional for market orders)
            is_market: Whether this is a market order
            reduce_only: Whether this order can only reduce position
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (order_result or None, error_message or None)
        """
        position_value = margin_usdt * leverage
        logger.info(f"[HyperLiquid Service] Placing {side} order: margin=${margin_usdt}, leverage={leverage}x, position=${position_value}")
        
        client, error = await self.get_trading_client(user_id, is_mainnet)
        if not client:
            return None, error
        
        # Set leverage first
        symbol_clean = symbol.upper().replace("/USD", "").replace(":USD", "").replace("USDT", "").replace("PERP", "")
        leverage_success = await client.set_leverage(symbol_clean, leverage, is_cross=True)
        if not leverage_success:
            logger.warning(f"[HyperLiquid Service] Failed to set leverage to {leverage}x, continuing anyway")
        
        # Get current price to calculate size
        execution_price = price
        if execution_price is None:
            # Fetch current market price
            execution_price = await client._get_mark_price(symbol)
            if execution_price is None:
                return None, f"Failed to get current price for {symbol}"
        
        logger.info(f"[HyperLiquid Service] Price for {symbol}: ${execution_price:,.2f}")
        
        # Calculate size from position value (margin × leverage)
        # Position value = size × price, so size = position_value / price
        size = round(position_value / execution_price, 4)
        logger.info(f"[HyperLiquid Service] Calculated size: {size} {symbol} (position ${position_value:,.2f})")
        
        # Place the order using the regular method
        return await self.place_order(
            user_id=user_id,
            symbol=symbol,
            side=side,
            size=size,
            price=price,
            is_market=is_market,
            reduce_only=reduce_only,
            is_mainnet=is_mainnet,
        )
    
    async def place_order_by_usdt(
        self,
        user_id: int,
        symbol: str,
        side: str,  # "buy" or "sell"
        amount_usdt: float,
        price: Optional[float] = None,
        is_market: bool = False,
        reduce_only: bool = False,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[OrderResult], Optional[str]]:
        """
        Place an order for a user specifying the amount in USDT.
        
        DEPRECATED: Use place_order_by_margin instead for margin-based orders.
        
        The actual token size is calculated based on current market price.
        
        Args:
            user_id: User ID
            symbol: Trading symbol (e.g., "BTC", "ETH")
            side: "buy" or "sell"
            amount_usdt: Order value in USDT
            price: Limit price (optional for market orders)
            is_market: Whether this is a market order
            reduce_only: Whether this order can only reduce position
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (order_result or None, error_message or None)
        """
        logger.info(f"[HyperLiquid Service] Placing {side} order for ${amount_usdt} of {symbol}")
        
        client, error = await self.get_trading_client(user_id, is_mainnet)
        if not client:
            return None, error
        
        # Get current price to calculate size
        execution_price = price
        if execution_price is None:
            # Fetch current market price
            execution_price = await client._get_mark_price(symbol)
            if execution_price is None:
                return None, f"Failed to get current price for {symbol}"
        
        logger.info(f"[HyperLiquid Service] Price for {symbol}: ${execution_price:,.2f}")
        
        # Calculate size from USDT amount and round to 4 decimal places
        # (HyperLiquid SDK requires sizes that can be represented as strings with limited precision)
        size = round(amount_usdt / execution_price, 4)
        logger.info(f"[HyperLiquid Service] Calculated size: {size} {symbol}")
        
        # Place the order using the regular method
        return await self.place_order(
            user_id=user_id,
            symbol=symbol,
            side=side,
            size=size,
            price=price,
            is_market=is_market,
            reduce_only=reduce_only,
            is_mainnet=is_mainnet,
        )
    
    async def close_position(
        self,
        user_id: int,
        symbol: str,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[OrderResult], Optional[str]]:
        """
        Close a position for a user.
        
        This places a market order in the opposite direction to close
        the entire position.
        
        Args:
            user_id: User ID
            symbol: Trading symbol
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (order_result or None, error_message or None)
        """
        logger.info(f"[HyperLiquid Service] Closing position for user {user_id}, symbol: {symbol}")
        
        # Get account state to find position
        account_state, error = await self.get_account_state(user_id, is_mainnet)
        if not account_state:
            return None, error
        
        # Find the position
        symbol_clean = symbol.upper().replace("/USD", "").replace(":USD", "").replace("USDT", "").replace("PERP", "")
        position = None
        for pos in account_state.positions:
            if pos.symbol.upper() == symbol_clean:
                position = pos
                break
        
        if not position or position.size == 0:
            return None, f"No open position for {symbol_clean}"
        
        # Determine closing side and size
        size = abs(position.size)
        side = "sell" if position.size > 0 else "buy"
        
        logger.info(f"[HyperLiquid Service] Closing position: {side} {size} {symbol_clean}")
        
        # Place market order to close
        return await self.place_order(
            user_id=user_id,
            symbol=symbol_clean,
            side=side,
            size=size,
            is_market=True,
            reduce_only=True,
            is_mainnet=is_mainnet,
        )
    
    async def cancel_order(
        self,
        user_id: int,
        symbol: str,
        order_id: int,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[OrderResult], Optional[str]]:
        """
        Cancel an order for a user.
        
        Args:
            user_id: User ID
            symbol: Trading symbol
            order_id: Order ID to cancel
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (order_result or None, error_message or None)
        """
        logger.info(f"[HyperLiquid Service] Cancelling order {order_id} for user {user_id}")
        
        client, error = await self.get_trading_client(user_id, is_mainnet)
        if not client:
            return None, error
        
        result = await client.cancel_order(symbol, order_id)
        return result, result.error if not result.success else None
    
    async def cancel_all_orders(
        self,
        user_id: int,
        symbol: Optional[str] = None,
        is_mainnet: bool = True,
    ) -> Tuple[int, Optional[str]]:
        """
        Cancel all orders for a user.
        
        Args:
            user_id: User ID
            symbol: Optional symbol to filter (None = all symbols)
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (cancelled_count, error_message or None)
        """
        logger.info(f"[HyperLiquid Service] Cancelling all orders for user {user_id}")
        
        client, error = await self.get_trading_client(user_id, is_mainnet)
        if not client:
            return 0, error
        
        results = await client.cancel_all_orders(symbol)
        
        success_count = sum(1 for r in results if r.success)
        logger.info(f"[HyperLiquid Service] Cancelled {success_count}/{len(results)} orders")
        
        return success_count, None
    
    async def set_leverage(
        self,
        user_id: int,
        symbol: str,
        leverage: int,
        is_cross: bool = True,
        is_mainnet: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        """
        Set leverage for a symbol.
        
        Args:
            user_id: User ID
            symbol: Trading symbol
            leverage: Leverage value (e.g., 10 for 10x)
            is_cross: True for cross margin, False for isolated
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (success, error_message or None)
        """
        logger.info(f"[HyperLiquid Service] Setting leverage for user {user_id}, {symbol}: {leverage}x")
        
        client, error = await self.get_trading_client(user_id, is_mainnet)
        if not client:
            return False, error
        
        success = await client.set_leverage(symbol, leverage, is_cross)
        return success, None if success else "Failed to set leverage"
    
    async def get_api_key_status(
        self,
        user_id: int,
        is_mainnet: bool = True,
    ) -> dict:
        """
        Get API key status for a user.
        
        Args:
            user_id: User ID
            is_mainnet: Whether to check mainnet or testnet
            
        Returns:
            Dict with API key status info
        """
        chain = "Mainnet" if is_mainnet else "Testnet"
        
        api_key = await self.db.get_hyperliquid_api_key(user_id, chain)
        
        if not api_key:
            return {
                "exists": False,
                "is_valid": False,
                "chain": chain,
                "message": "No API key found",
            }
        
        return {
            "exists": True,
            "is_valid": api_key.is_valid,
            "chain": chain,
            "agent_address": api_key.short_agent_address,
            "agent_name": api_key.agent_name,
            "valid_until": api_key.valid_until.isoformat(),
            "days_until_expiry": api_key.days_until_expiry,
            "created_at": api_key.created_at.isoformat(),
            "message": "Valid" if api_key.is_valid else "Expired",
        }
    
    async def get_positions(
        self,
        user_id: int,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[list], Optional[str]]:
        """
        Get all open positions for a user.
        
        Args:
            user_id: User ID
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (list of Position objects or None, error_message or None)
        """
        logger.info(f"[HyperLiquid Service] Getting positions for user {user_id}")
        
        account_state, error = await self.get_account_state(user_id, is_mainnet)
        if not account_state:
            return None, error or "Failed to get account state"
        
        # Return positions from account state
        positions = account_state.positions if account_state.positions else []
        logger.info(f"[HyperLiquid Service] Found {len(positions)} open positions")
        
        return positions, None
    
    async def get_open_orders(
        self,
        user_id: int,
        is_mainnet: bool = True,
    ) -> Tuple[Optional[list], Optional[str]]:
        """
        Get all open orders for a user.
        
        Args:
            user_id: User ID
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (list of order dicts or None, error_message or None)
        """
        logger.info(f"[HyperLiquid Service] Getting open orders for user {user_id}")
        
        client, error = await self.get_trading_client(user_id, is_mainnet)
        if not client:
            return None, error or "Failed to get trading client"
        
        try:
            orders = await client.get_open_orders()
            logger.info(f"[HyperLiquid Service] Found {len(orders)} open orders")
            return orders, None
        except Exception as e:
            logger.exception(f"[HyperLiquid Service] Error getting open orders")
            return None, str(e)
    
    async def withdraw_from_bridge(
        self,
        user_id: int,
        amount_usd: float,
        is_mainnet: bool = True,
    ) -> Tuple[bool, Optional[str], Optional[dict]]:
        """
        Withdraw USDC from HyperLiquid to Arbitrum.
        
        The funds will be withdrawn to the user's main EVM wallet on Arbitrum.
        Note: ~1 USDC fee will be deducted from the withdrawal amount.
        
        Args:
            user_id: User ID
            amount_usd: Amount in USD to withdraw
            is_mainnet: Whether to use mainnet or testnet
            
        Returns:
            Tuple of (success, error_message or None, raw_response or None)
        """
        logger.info(f"[HyperLiquid Service] Withdrawing ${amount_usd} for user {user_id}")
        
        # Get the account state first to check withdrawable balance
        account_state, error = await self.get_account_state(user_id, is_mainnet)
        if not account_state:
            return False, error or "Failed to get account state", None
        
        if account_state.withdrawable < amount_usd:
            return False, f"Insufficient withdrawable balance. Available: ${account_state.withdrawable:.2f}", None
        
        # Get trading client
        client, error = await self.get_trading_client(user_id, is_mainnet)
        if not client:
            return False, error or "Failed to get trading client", None
        
        # Get main wallet private key for withdrawal (agents can't withdraw)
        wallet = await self.db.get_user_wallet(user_id, WalletType.EVM)
        if not wallet:
            return False, "No EVM wallet found", None
        
        main_wallet_private_key = await self.db.get_wallet_private_key(wallet.id)
        if not main_wallet_private_key:
            return False, "Failed to get wallet private key", None
        
        # Perform withdrawal with main wallet key
        success, error, response = await client.withdraw_from_bridge(
            amount_usd,
            main_wallet_private_key=main_wallet_private_key,
        )
        
        if success:
            logger.info(f"[HyperLiquid Service] Withdrawal successful for user {user_id}")
        else:
            logger.error(f"[HyperLiquid Service] Withdrawal failed: {error}")
        
        return success, error, response


# Singleton instance
_service: Optional[HyperliquidService] = None


async def get_hyperliquid_service(db: Optional[Database] = None) -> HyperliquidService:
    """Get or create the HyperLiquid service instance."""
    global _service
    
    if _service is None:
        if db is None:
            from src.database import get_database
            db = await get_database()
        _service = HyperliquidService(db)
    
    return _service

