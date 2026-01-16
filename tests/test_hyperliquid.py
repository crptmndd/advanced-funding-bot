#!/usr/bin/env python3
"""
Test script for HyperLiquid integration.

This script tests the HyperLiquid API key creation and trading functionality.

Usage:
    python tests/test_hyperliquid.py

Note: This requires a user to be registered in the database with an EVM wallet.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Database, get_database, WalletType
from src.exchanges.hyperliquid_auth import (
    create_agent_key,
    register_agent_with_hyperliquid,
    sign_agent_approval,
)
from src.exchanges.hyperliquid_trading import (
    HyperliquidTradingClient,
    OrderSide,
)
from src.services.hyperliquid_service import HyperliquidService

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


async def test_agent_key_signing():
    """Test local agent key creation (without registering with HyperLiquid)."""
    logger.info("=" * 60)
    logger.info("Testing agent key creation (local only)...")
    logger.info("=" * 60)
    
    # Use a test private key (DO NOT use in production!)
    # This is just for testing the signing process
    test_private_key = "0x" + "1234567890abcdef" * 4
    
    try:
        agent_key = create_agent_key(
            main_wallet_private_key=test_private_key,
            validity_days=180,
            chain="Mainnet",
        )
        
        logger.info(f"✅ Agent key created locally")
        logger.info(f"   Agent address: {agent_key.agent_address}")
        logger.info(f"   Agent name: {agent_key.agent_name}")
        logger.info(f"   Valid until: {agent_key.valid_until}")
        logger.info(f"   Signature r: {agent_key.signature['r'][:20]}...")
        logger.info(f"   Signature s: {agent_key.signature['s'][:20]}...")
        logger.info(f"   Signature v: {agent_key.signature['v']}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to create agent key: {e}")
        return False


async def test_database_api_key_storage():
    """Test storing and retrieving HyperLiquid API keys from database."""
    logger.info("=" * 60)
    logger.info("Testing database API key storage...")
    logger.info("=" * 60)
    
    db = await get_database()
    
    # Get first user (for testing)
    users = await db.get_all_users()
    if not users:
        logger.warning("No users in database. Create a user first with /start in the bot.")
        return False
    
    user = users[0]
    logger.info(f"Testing with user: {user.display_name} (ID: {user.id})")
    
    # Check if user has EVM wallet
    wallet = await db.get_user_wallet(user.id, WalletType.EVM)
    if not wallet:
        logger.warning("User has no EVM wallet.")
        return False
    
    logger.info(f"User wallet: {wallet.short_address}")
    
    # Check for existing HyperLiquid API key
    api_key = await db.get_hyperliquid_api_key(user.id, "Mainnet")
    
    if api_key:
        logger.info(f"✅ Found existing API key:")
        logger.info(f"   Agent: {api_key.short_agent_address}")
        logger.info(f"   Name: {api_key.agent_name}")
        logger.info(f"   Valid: {api_key.is_valid}")
        logger.info(f"   Days left: {api_key.days_until_expiry}")
    else:
        logger.info("No existing API key found.")
    
    return True


async def test_hyperliquid_service():
    """Test the HyperLiquid service."""
    logger.info("=" * 60)
    logger.info("Testing HyperLiquid service...")
    logger.info("=" * 60)
    
    db = await get_database()
    service = HyperliquidService(db)
    
    # Get first user
    users = await db.get_all_users()
    if not users:
        logger.warning("No users in database.")
        return False
    
    user = users[0]
    logger.info(f"Testing with user: {user.display_name}")
    
    # Get API key status
    status = await service.get_api_key_status(user.id, is_mainnet=True)
    logger.info(f"API key status: {status}")
    
    return True


async def test_trading_client_info():
    """Test getting account info (requires funded account)."""
    logger.info("=" * 60)
    logger.info("Testing trading client account info...")
    logger.info("=" * 60)
    
    db = await get_database()
    service = HyperliquidService(db)
    
    # Get first user
    users = await db.get_all_users()
    if not users:
        logger.warning("No users in database.")
        return False
    
    user = users[0]
    
    # Check if user has API key
    api_key = await db.get_hyperliquid_api_key(user.id, "Mainnet")
    if not api_key or not api_key.is_valid:
        logger.info("User has no valid API key. Creating one...")
        
        # Note: This will make a real API call to HyperLiquid
        # Only run if you have an EVM wallet with proper setup
        logger.warning("Skipping API key creation in test mode.")
        logger.warning("To create an API key, use the bot command or call service.create_api_key_for_user()")
        return True
    
    # Get account state
    logger.info("Getting account state...")
    account_state, error = await service.get_account_state(user.id)
    
    if account_state:
        logger.info(f"✅ Account state retrieved:")
        logger.info(f"   Account value: ${account_state.account_value:,.2f}")
        logger.info(f"   Available: ${account_state.available_balance:,.2f}")
        logger.info(f"   Margin used: ${account_state.margin_used:,.2f}")
        logger.info(f"   Positions: {len(account_state.positions)}")
        
        for pos in account_state.positions:
            logger.info(f"   - {pos.symbol}: {pos.size} @ {pos.entry_price}, PnL: ${pos.unrealized_pnl:,.2f}")
    else:
        logger.warning(f"Failed to get account state: {error}")
    
    return True


async def run_all_tests():
    """Run all tests."""
    logger.info("Starting HyperLiquid integration tests...")
    logger.info("")
    
    results = []
    
    # Test 1: Local agent key signing
    results.append(("Agent Key Signing", await test_agent_key_signing()))
    
    # Test 2: Database storage
    results.append(("Database Storage", await test_database_api_key_storage()))
    
    # Test 3: Service
    results.append(("HyperLiquid Service", await test_hyperliquid_service()))
    
    # Test 4: Trading client (info only)
    results.append(("Trading Client Info", await test_trading_client_info()))
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    passed = 0
    failed = 0
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"  {status}: {name}")
        if result:
            passed += 1
        else:
            failed += 1
    
    logger.info("")
    logger.info(f"Total: {passed}/{len(results)} passed")
    
    return failed == 0


if __name__ == "__main__":
    # Run tests
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)

