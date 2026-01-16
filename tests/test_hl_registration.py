#!/usr/bin/env python3
"""
Test script for HyperLiquid API key registration.

This directly tests the registration endpoint to debug issues.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.wallet_generator import generate_evm_wallet
from src.exchanges.hyperliquid_auth import (
    create_agent_key,
    register_agent_with_hyperliquid,
)

# Configure logging - VERY verbose
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Set all loggers to DEBUG
for name in ['src.exchanges.hyperliquid_auth', 'aiohttp', 'urllib3']:
    logging.getLogger(name).setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)


async def test_registration():
    """Test API key registration with a test wallet."""
    logger.info("=" * 60)
    logger.info("Testing HyperLiquid API key registration")
    logger.info("=" * 60)
    
    # Generate a test wallet
    logger.info("Generating test wallet...")
    test_wallet = generate_evm_wallet()
    logger.info(f"Test wallet address: {test_wallet.address}")
    
    # Create agent key
    logger.info("")
    logger.info("Creating agent key...")
    agent_key = create_agent_key(
        main_wallet_private_key=test_wallet.private_key,
        validity_days=180,
        chain="Mainnet",
    )
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("AGENT KEY DETAILS:")
    logger.info("=" * 60)
    logger.info(f"Agent address: {agent_key.agent_address}")
    logger.info(f"Agent name: {agent_key.agent_name}")
    logger.info(f"Nonce: {agent_key.nonce}")
    logger.info(f"Valid until: {agent_key.valid_until}")
    logger.info(f"Chain: {agent_key.chain}")
    logger.info(f"Signature r: {agent_key.signature['r']}")
    logger.info(f"Signature s: {agent_key.signature['s']}")
    logger.info(f"Signature v: {agent_key.signature['v']}")
    
    # Register with HyperLiquid
    logger.info("")
    logger.info("=" * 60)
    logger.info("REGISTERING WITH HYPERLIQUID...")
    logger.info("=" * 60)
    
    success, error = await register_agent_with_hyperliquid(
        agent_key=agent_key,
        main_wallet_address=test_wallet.address,
    )
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("RESULT:")
    logger.info("=" * 60)
    logger.info(f"Success: {success}")
    if error:
        logger.info(f"Error: {error}")
    
    return success


if __name__ == "__main__":
    success = asyncio.run(test_registration())
    sys.exit(0 if success else 1)

