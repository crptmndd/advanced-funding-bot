"""
OKX Service - High-level service for OKX operations.

This service provides a high-level interface for:
- Managing OKX API keys
- Placing orders
- Managing positions
"""

import logging
from typing import Optional, Tuple, List

from src.database import Database, OKXApiKey
from src.exchanges.okx_client import (
    OKXClient,
    OKXOrderResult,
    OKXPosition,
    OKXAccountState,
)

logger = logging.getLogger(__name__)


class OKXService:
    """
    High-level service for OKX operations.
    
    Provides a clean interface for bot commands and other services
    to interact with OKX.
    """
    
    def __init__(self, db: Database):
        """Initialize the service."""
        self.db = db
        logger.info("[OKX Service] Initialized")
    
    async def save_api_key(
        self,
        user_id: int,
        api_key: str,
        secret_key: str,
        passphrase: str,
        label: str = "OKX Trading",
        is_sandbox: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        """
        Save OKX API key for a user.
        
        Args:
            user_id: User ID
            api_key: OKX API key
            secret_key: OKX secret key
            passphrase: OKX passphrase
            label: User-defined label
            is_sandbox: Whether this is a sandbox key
            
        Returns:
            Tuple of (success, error_message or None)
        """
        logger.info(f"[OKX Service] Saving API key for user {user_id}")
        
        try:
            # Verify the credentials work
            client = OKXClient(
                api_key=api_key,
                secret_key=secret_key,
                passphrase=passphrase,
                sandbox=is_sandbox,
                log_tag=f"user_{user_id}",
            )
            
            # Try to get account config to verify credentials
            config = await client.get_account_config(use_cache=False)
            if config is None:
                return False, "Invalid credentials - could not connect to OKX API"
            
            # Save to database
            await self.db.save_okx_api_key(
                user_id=user_id,
                api_key=api_key,
                secret_key=secret_key,
                passphrase=passphrase,
                label=label,
                is_sandbox=is_sandbox,
            )
            
            logger.info(f"[OKX Service] API key saved for user {user_id}")
            return True, None
            
        except Exception as e:
            logger.exception(f"[OKX Service] Error saving API key for user {user_id}")
            return False, str(e)
    
    async def get_trading_client(
        self,
        user_id: int,
    ) -> Tuple[Optional[OKXClient], Optional[str]]:
        """
        Get a trading client for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Tuple of (OKXClient or None, error_message or None)
        """
        logger.info(f"[OKX Service] Getting trading client for user {user_id}")
        
        # Get API key from database
        api_key = await self.db.get_okx_api_key(user_id)
        if not api_key:
            return None, "No OKX API key found. Use /okx_setup to add your API key."
        
        # Get credentials
        credentials = await self.db.get_okx_api_key_credentials(api_key.id)
        if not credentials:
            return None, "Failed to decrypt API credentials"
        
        # Create client
        client = OKXClient(
            api_key=credentials["api_key"],
            secret_key=credentials["secret_key"],
            passphrase=credentials["passphrase"],
            sandbox=api_key.is_sandbox,
            log_tag=f"user_{user_id}",
        )
        
        logger.info(f"[OKX Service] Trading client ready for user {user_id}")
        return client, None
    
    async def get_api_key_status(self, user_id: int) -> dict:
        """
        Get API key status for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Dict with API key status info
        """
        api_key = await self.db.get_okx_api_key(user_id)
        
        if not api_key:
            return {
                "exists": False,
                "is_valid": False,
                "message": "No API key found",
            }
        
        return {
            "exists": True,
            "is_valid": api_key.is_valid,
            "label": api_key.label,
            "is_sandbox": api_key.is_sandbox,
            "created_at": api_key.created_at.isoformat(),
            "message": "Active" if api_key.is_valid else "Inactive",
        }
    
    async def get_account_state(
        self,
        user_id: int,
    ) -> Tuple[Optional[OKXAccountState], Optional[str]]:
        """
        Get account state for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Tuple of (OKXAccountState or None, error_message or None)
        """
        client, error = await self.get_trading_client(user_id)
        if not client:
            return None, error
        
        account_state = await client.get_account_state()
        if not account_state:
            return None, "Failed to fetch account state"
        
        return account_state, None
    
    async def get_positions(
        self,
        user_id: int,
    ) -> Tuple[Optional[List[OKXPosition]], Optional[str]]:
        """
        Get all open positions for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Tuple of (list of OKXPosition or None, error_message or None)
        """
        logger.info(f"[OKX Service] Getting positions for user {user_id}")
        
        client, error = await self.get_trading_client(user_id)
        if not client:
            return None, error
        
        try:
            positions = await client.get_positions()
            logger.info(f"[OKX Service] Found {len(positions)} open positions")
            return positions, None
        except Exception as e:
            logger.exception(f"[OKX Service] Error getting positions")
            return None, str(e)
    
    async def get_open_orders(
        self,
        user_id: int,
    ) -> Tuple[Optional[list], Optional[str]]:
        """
        Get all open orders for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Tuple of (list of orders or None, error_message or None)
        """
        logger.info(f"[OKX Service] Getting open orders for user {user_id}")
        
        client, error = await self.get_trading_client(user_id)
        if not client:
            return None, error
        
        try:
            orders = await client.get_open_orders()
            logger.info(f"[OKX Service] Found {len(orders)} open orders")
            return orders, None
        except Exception as e:
            logger.exception(f"[OKX Service] Error getting open orders")
            return None, str(e)
    
    async def place_order_by_margin(
        self,
        user_id: int,
        symbol: str,
        side: str,  # "buy" or "sell"
        margin_usdt: float,
        leverage: int,
        price: Optional[float] = None,
        is_market: bool = False,
        margin_mode: str = "isolated",
    ) -> Tuple[Optional[OKXOrderResult], Optional[str]]:
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
            margin_mode: Margin mode ("isolated" or "cross")
            
        Returns:
            Tuple of (OKXOrderResult or None, error_message or None)
        """
        position_value = margin_usdt * leverage
        logger.info(f"[OKX Service] Placing {side} order: margin=${margin_usdt}, leverage={leverage}x, position=${position_value}")
        
        client, error = await self.get_trading_client(user_id)
        if not client:
            return None, error
        
        # Get instrument ID
        inst_id = await client.get_instrument_id(symbol)
        if not inst_id:
            return None, f"Could not find instrument for {symbol}"
        
        # Get current price if not provided
        execution_price = price
        if execution_price is None:
            execution_price = await client.get_last_price(inst_id)
            if execution_price is None:
                return None, f"Failed to get current price for {symbol}"
        
        logger.info(f"[OKX Service] Price for {symbol}: ${execution_price:,.2f}")
        
        # Get instrument info for size calculation
        instrument_info = await client.get_instrument_info(inst_id)
        if not instrument_info:
            return None, f"Failed to get instrument info for {symbol}"
        
        # Calculate size from margin and leverage
        size = client.calculate_position_size(
            margin_amount=margin_usdt,
            entry_price=execution_price,
            leverage=leverage,
            instrument_info=instrument_info,
        )
        
        if size <= 0:
            return None, "Calculated position size is too small"
        
        logger.info(f"[OKX Service] Calculated size: {size} contracts (position ${position_value:,.2f})")
        
        # Determine position side
        position_side = "long" if side.lower() == "buy" else "short"
        
        # Place the order
        if is_market or price is None:
            result = await client.place_market_order(
                instrument_id=inst_id,
                side=side.lower(),
                size=size,
                margin_mode=margin_mode,
                position_side=position_side,
                leverage=leverage,
            )
        else:
            result = await client.place_limit_order(
                instrument_id=inst_id,
                side=side.lower(),
                price=price,
                size=size,
                leverage=leverage,
                margin_mode=margin_mode,
                position_side=position_side,
            )
        
        if result.success:
            logger.info(f"[OKX Service] Order placed successfully: {result.order_id}")
        else:
            logger.error(f"[OKX Service] Order failed: {result.error}")
        
        return result, result.error if not result.success else None
    
    async def close_position(
        self,
        user_id: int,
        symbol: str,
        margin_mode: str = "isolated",
    ) -> Tuple[Optional[OKXOrderResult], Optional[str]]:
        """
        Close a position for a user.
        
        Args:
            user_id: User ID
            symbol: Trading symbol
            margin_mode: Margin mode
            
        Returns:
            Tuple of (OKXOrderResult or None, error_message or None)
        """
        logger.info(f"[OKX Service] Closing position for user {user_id}, symbol: {symbol}")
        
        client, error = await self.get_trading_client(user_id)
        if not client:
            return None, error
        
        # Get instrument ID
        inst_id = await client.get_instrument_id(symbol)
        if not inst_id:
            return None, f"Could not find instrument for {symbol}"
        
        # Get positions to find the one to close
        positions = await client.get_positions(inst_id)
        if not positions:
            return None, f"No open position for {symbol}"
        
        # Close the position
        success = await client.close_position(inst_id, margin_mode=margin_mode)
        
        if success:
            return OKXOrderResult(success=True, status="closed"), None
        else:
            return OKXOrderResult(success=False, error="Failed to close position"), "Failed to close position"
    
    async def cancel_order(
        self,
        user_id: int,
        symbol: str,
        order_id: str,
    ) -> Tuple[Optional[OKXOrderResult], Optional[str]]:
        """
        Cancel an order for a user.
        
        Args:
            user_id: User ID
            symbol: Trading symbol
            order_id: Order ID to cancel
            
        Returns:
            Tuple of (OKXOrderResult or None, error_message or None)
        """
        logger.info(f"[OKX Service] Cancelling order {order_id} for user {user_id}")
        
        client, error = await self.get_trading_client(user_id)
        if not client:
            return None, error
        
        # Get instrument ID
        inst_id = await client.get_instrument_id(symbol)
        if not inst_id:
            return None, f"Could not find instrument for {symbol}"
        
        success = await client.cancel_order(inst_id, order_id)
        
        if success:
            return OKXOrderResult(success=True, order_id=order_id, status="cancelled"), None
        else:
            return OKXOrderResult(success=False, error="Failed to cancel order"), "Failed to cancel order"
    
    async def set_leverage(
        self,
        user_id: int,
        symbol: str,
        leverage: int,
        margin_mode: str = "isolated",
    ) -> Tuple[bool, Optional[str]]:
        """
        Set leverage for a symbol.
        
        Args:
            user_id: User ID
            symbol: Trading symbol
            leverage: Leverage value
            margin_mode: Margin mode
            
        Returns:
            Tuple of (success, error_message or None)
        """
        logger.info(f"[OKX Service] Setting leverage for user {user_id}, {symbol}: {leverage}x")
        
        client, error = await self.get_trading_client(user_id)
        if not client:
            return False, error
        
        # Get instrument ID
        inst_id = await client.get_instrument_id(symbol)
        if not inst_id:
            return False, f"Could not find instrument for {symbol}"
        
        success = await client.set_leverage(inst_id, leverage, margin_mode)
        return success, None if success else "Failed to set leverage"


# Singleton instance
_service: Optional[OKXService] = None


async def get_okx_service(db: Optional[Database] = None) -> OKXService:
    """Get or create the OKX service instance."""
    global _service
    
    if _service is None:
        if db is None:
            from src.database import get_database
            db = await get_database()
        _service = OKXService(db)
    
    return _service

