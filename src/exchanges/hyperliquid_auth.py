"""
HyperLiquid API key creation and authentication module.

This module handles the creation of HyperLiquid "agent" API keys.
HyperLiquid uses a unique authentication system where:
1. You have a main wallet (the one you deposit to)
2. You create an "agent" wallet that can trade on your behalf
3. You sign a typed message (EIP-712) with your main wallet to authorize the agent

The agent wallet's private key is then used for signing trading requests.
"""

import time
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple
import json

import aiohttp
from eth_account import Account
from eth_account.messages import encode_typed_data

from src.database.wallet_generator import generate_evm_wallet, GeneratedWallet

# Logger
logger = logging.getLogger(__name__)


# HyperLiquid API endpoints
HYPERLIQUID_MAINNET_API = "https://api.hyperliquid.xyz"
HYPERLIQUID_TESTNET_API = "https://api.hyperliquid-testnet.xyz"

# HyperLiquid UI API for agent approval (used by frontend)
HYPERLIQUID_MAINNET_UI_API = "https://api-ui.hyperliquid.xyz"
HYPERLIQUID_TESTNET_UI_API = "https://api-ui.hyperliquid-testnet.xyz"

# Maximum API key validity (180 days in milliseconds)
MAX_VALIDITY_DAYS = 180
MAX_VALIDITY_MS = MAX_VALIDITY_DAYS * 24 * 60 * 60 * 1000

# Signature chain ID for Arbitrum (used by HyperLiquid)
SIGNATURE_CHAIN_ID = "0xa4b1"  # Arbitrum One chain ID in hex


@dataclass
class HyperliquidAgentKey:
    """Represents a created HyperLiquid agent (API) key."""
    
    # Agent wallet info
    agent_address: str
    agent_private_key: str
    
    # Authorization info
    agent_name: str
    valid_until_ms: int
    nonce: int
    
    # Chain
    chain: str  # "Mainnet" or "Testnet"
    
    # The signed authorization (to be sent to HyperLiquid)
    signature: dict  # Contains r, s, v
    
    @property
    def valid_until(self) -> datetime:
        """Get validity as datetime."""
        return datetime.utcfromtimestamp(self.valid_until_ms / 1000)
    
    @property
    def is_mainnet(self) -> bool:
        """Check if this key is for mainnet."""
        return self.chain == "Mainnet"


def _get_current_nonce() -> int:
    """Get current timestamp in milliseconds as nonce."""
    return int(time.time() * 1000)


def _calculate_valid_until(days: int = 180) -> int:
    """
    Calculate valid_until timestamp in milliseconds.
    
    Args:
        days: Number of days the key should be valid (max 180)
        
    Returns:
        Timestamp in milliseconds
    """
    days = min(days, MAX_VALIDITY_DAYS)
    future_time = datetime.utcnow() + timedelta(days=days)
    return int(future_time.timestamp() * 1000)


def _create_agent_name(valid_until_ms: int, prefix: str = "api2") -> str:
    """
    Create agent name in HyperLiquid format.
    
    HyperLiquid expects format: "api2 valid_until {timestamp}"
    
    Args:
        valid_until_ms: Validity timestamp in milliseconds
        prefix: Prefix for the agent name (usually "api2")
        
    Returns:
        Formatted agent name
    """
    return f"{prefix} valid_until {valid_until_ms}"


def _build_typed_data_for_agent_approval(
    chain: str,
    agent_address: str,
    agent_name: str,
    nonce: int,
) -> dict:
    """
    Build EIP-712 typed data for agent approval.
    
    This is the message structure that HyperLiquid expects for
    authorizing an agent wallet to trade on behalf of the main wallet.
    
    Args:
        chain: "Mainnet" or "Testnet"
        agent_address: Address of the agent wallet
        agent_name: Name of the agent (includes validity)
        nonce: Nonce (current timestamp in ms)
        
    Returns:
        EIP-712 typed data structure
    """
    # HyperLiquid uses a specific EIP-712 structure
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "HyperliquidTransaction:ApproveAgent": [
                {"name": "hyperliquidChain", "type": "string"},
                {"name": "agentAddress", "type": "address"},
                {"name": "agentName", "type": "string"},
                {"name": "nonce", "type": "uint64"},
            ],
        },
        "primaryType": "HyperliquidTransaction:ApproveAgent",
        "domain": {
            "name": "HyperliquidSignTransaction",
            "version": "1",
            "chainId": 42161,  # Arbitrum One
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        },
        "message": {
            "hyperliquidChain": chain,
            "agentAddress": agent_address,
            "agentName": agent_name,
            "nonce": nonce,
        },
    }
    
    return typed_data


def sign_agent_approval(
    main_wallet_private_key: str,
    agent_address: str,
    agent_name: str,
    nonce: int,
    chain: str = "Mainnet",
) -> dict:
    """
    Sign agent approval message with main wallet.
    
    Args:
        main_wallet_private_key: Private key of the main wallet (hex string)
        agent_address: Address of the agent wallet
        agent_name: Name/label for the agent
        nonce: Nonce (timestamp in ms)
        chain: "Mainnet" or "Testnet"
        
    Returns:
        Signature dict with r, s, v components
    """
    logger.info(f"[HyperLiquid] Signing agent approval for {agent_address[:10]}...")
    logger.debug(f"[HyperLiquid] Agent name: {agent_name}")
    logger.debug(f"[HyperLiquid] Nonce: {nonce}")
    logger.debug(f"[HyperLiquid] Chain: {chain}")
    
    # Ensure private key has 0x prefix
    if not main_wallet_private_key.startswith("0x"):
        main_wallet_private_key = "0x" + main_wallet_private_key
    
    # Build typed data
    typed_data = _build_typed_data_for_agent_approval(
        chain=chain,
        agent_address=agent_address,
        agent_name=agent_name,
        nonce=nonce,
    )
    
    logger.debug(f"[HyperLiquid] Typed data message: {json.dumps(typed_data['message'], indent=2)}")
    
    # Sign the typed data
    account = Account.from_key(main_wallet_private_key)
    
    # Encode and sign EIP-712 typed data
    signable_message = encode_typed_data(full_message=typed_data)
    signed = account.sign_message(signable_message)
    
    # Format signature components properly
    # r and s must be 0x-prefixed hex strings, padded to 66 chars (0x + 64 hex chars = 32 bytes)
    r_hex = hex(signed.r)
    s_hex = hex(signed.s)
    
    # Ensure r and s are properly padded (0x + 64 hex chars)
    r_padded = "0x" + r_hex[2:].zfill(64)
    s_padded = "0x" + s_hex[2:].zfill(64)
    
    signature = {
        "r": r_padded,
        "s": s_padded,
        "v": signed.v,
    }
    
    logger.info(f"[HyperLiquid] Agent approval signed successfully")
    logger.info(f"[HyperLiquid] Signature v={signed.v}, r_len={len(r_padded)}, s_len={len(s_padded)}")
    
    return signature


def create_agent_key(
    main_wallet_private_key: str,
    validity_days: int = 180,
    chain: str = "Mainnet",
    agent_wallet: Optional[GeneratedWallet] = None,
) -> HyperliquidAgentKey:
    """
    Create a new HyperLiquid agent (API) key.
    
    This generates a new agent wallet and signs an approval message
    with the main wallet to authorize the agent.
    
    Args:
        main_wallet_private_key: Private key of the main wallet
        validity_days: How many days the key should be valid (max 180)
        chain: "Mainnet" or "Testnet"
        agent_wallet: Optional pre-generated agent wallet
        
    Returns:
        HyperliquidAgentKey with all necessary info
    """
    logger.info(f"[HyperLiquid] Creating new agent key...")
    logger.info(f"[HyperLiquid] Chain: {chain}, Validity: {validity_days} days")
    
    # Get main wallet address for logging
    if not main_wallet_private_key.startswith("0x"):
        main_wallet_private_key = "0x" + main_wallet_private_key
    main_account = Account.from_key(main_wallet_private_key)
    logger.info(f"[HyperLiquid] Main wallet: {main_account.address[:10]}...{main_account.address[-4:]}")
    
    # Generate or use provided agent wallet
    if agent_wallet is None:
        logger.info(f"[HyperLiquid] Generating new agent wallet...")
        agent_wallet = generate_evm_wallet()
    
    logger.info(f"[HyperLiquid] Agent wallet: {agent_wallet.address[:10]}...{agent_wallet.address[-4:]}")
    
    # Calculate validity and nonce
    nonce = _get_current_nonce()
    valid_until_ms = _calculate_valid_until(validity_days)
    agent_name = _create_agent_name(valid_until_ms)
    
    logger.info(f"[HyperLiquid] Agent name: {agent_name}")
    logger.info(f"[HyperLiquid] Valid until: {datetime.utcfromtimestamp(valid_until_ms / 1000).isoformat()}")
    
    # Sign the approval
    signature = sign_agent_approval(
        main_wallet_private_key=main_wallet_private_key,
        agent_address=agent_wallet.address,
        agent_name=agent_name,
        nonce=nonce,
        chain=chain,
    )
    
    agent_key = HyperliquidAgentKey(
        agent_address=agent_wallet.address,
        agent_private_key=agent_wallet.private_key,
        agent_name=agent_name,
        valid_until_ms=valid_until_ms,
        nonce=nonce,
        chain=chain,
        signature=signature,
    )
    
    logger.info(f"[HyperLiquid] Agent key created successfully!")
    
    return agent_key


async def register_agent_with_hyperliquid(
    agent_key: HyperliquidAgentKey,
    main_wallet_address: str,
) -> Tuple[bool, Optional[str]]:
    """
    Register the agent approval with HyperLiquid API.
    
    This sends the signed approval to HyperLiquid to authorize
    the agent wallet to trade on behalf of the main wallet.
    
    Args:
        agent_key: The created agent key with signature
        main_wallet_address: Address of the main wallet
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    logger.info(f"[HyperLiquid] Registering agent with HyperLiquid API...")
    
    # Select API endpoint based on chain
    if agent_key.is_mainnet:
        api_url = HYPERLIQUID_MAINNET_API
    else:
        api_url = HYPERLIQUID_TESTNET_API
    
    # Build the request payload - matching HyperLiquid's expected format
    # Based on actual API requests captured from the HyperLiquid frontend
    payload = {
        "action": {
            "type": "approveAgent",
            "hyperliquidChain": agent_key.chain,
            "signatureChainId": SIGNATURE_CHAIN_ID,  # "0xa4b1" for Arbitrum
            "agentAddress": agent_key.agent_address,
            "agentName": agent_key.agent_name,
            "nonce": agent_key.nonce,
        },
        "nonce": agent_key.nonce,
        "signature": agent_key.signature,
        "vaultAddress": None,
    }
    
    # Log full details for debugging
    logger.info(f"[HyperLiquid] === REGISTRATION REQUEST ===")
    logger.info(f"[HyperLiquid] Main wallet: {main_wallet_address}")
    logger.info(f"[HyperLiquid] Agent address: {agent_key.agent_address}")
    logger.info(f"[HyperLiquid] Agent name: {agent_key.agent_name}")
    logger.info(f"[HyperLiquid] Nonce: {agent_key.nonce}")
    logger.info(f"[HyperLiquid] Chain: {agent_key.chain}")
    logger.info(f"[HyperLiquid] Signature r: {agent_key.signature['r']}")
    logger.info(f"[HyperLiquid] Signature s: {agent_key.signature['s']}")
    logger.info(f"[HyperLiquid] Signature v: {agent_key.signature['v']}")
    
    logger.info(f"[HyperLiquid] Request URL: {api_url}/exchange")
    logger.info(f"[HyperLiquid] Request payload:")
    logger.info(json.dumps(payload, indent=2))
    
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{api_url}/exchange",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                },
            ) as resp:
                response_text = await resp.text()
                
                logger.info(f"[HyperLiquid] Response status: {resp.status}")
                logger.info(f"[HyperLiquid] Response body: {response_text}")
                
                if resp.status == 200:
                    try:
                        response_data = json.loads(response_text)
                        
                        # Check for success
                        if response_data.get("status") == "ok":
                            logger.info(f"[HyperLiquid] Agent registered successfully!")
                            return True, None
                        else:
                            error_msg = response_data.get("response", response_text)
                            logger.error(f"[HyperLiquid] Registration failed: {error_msg}")
                            return False, str(error_msg)
                            
                    except json.JSONDecodeError:
                        # Response might be plain "ok" or similar
                        if "ok" in response_text.lower():
                            logger.info(f"[HyperLiquid] Agent registered successfully!")
                            return True, None
                        return False, response_text
                else:
                    logger.error(f"[HyperLiquid] API error: {resp.status} - {response_text}")
                    return False, f"HTTP {resp.status}: {response_text}"
                    
    except aiohttp.ClientError as e:
        logger.error(f"[HyperLiquid] Network error: {e}")
        return False, f"Network error: {str(e)}"
    except Exception as e:
        logger.exception(f"[HyperLiquid] Unexpected error during registration")
        return False, f"Unexpected error: {str(e)}"


async def create_and_register_agent_key(
    main_wallet_private_key: str,
    validity_days: int = 180,
    chain: str = "Mainnet",
) -> Tuple[Optional[HyperliquidAgentKey], Optional[str]]:
    """
    Create and register a new HyperLiquid agent key.
    
    This is the main function to use for creating API keys.
    It generates the agent wallet, signs the approval, and registers
    it with HyperLiquid in one step.
    
    Args:
        main_wallet_private_key: Private key of the main wallet
        validity_days: How many days the key should be valid (max 180)
        chain: "Mainnet" or "Testnet"
        
    Returns:
        Tuple of (agent_key or None, error_message or None)
    """
    logger.info(f"[HyperLiquid] === Creating and registering agent key ===")
    
    try:
        # Create the agent key locally
        agent_key = create_agent_key(
            main_wallet_private_key=main_wallet_private_key,
            validity_days=validity_days,
            chain=chain,
        )
        
        # Get main wallet address
        if not main_wallet_private_key.startswith("0x"):
            main_wallet_private_key = "0x" + main_wallet_private_key
        main_account = Account.from_key(main_wallet_private_key)
        
        # Register with HyperLiquid
        success, error = await register_agent_with_hyperliquid(
            agent_key=agent_key,
            main_wallet_address=main_account.address,
        )
        
        if success:
            logger.info(f"[HyperLiquid] === Agent key created and registered successfully! ===")
            return agent_key, None
        else:
            logger.error(f"[HyperLiquid] === Failed to register agent key: {error} ===")
            return None, error
            
    except Exception as e:
        logger.exception(f"[HyperLiquid] === Error creating agent key ===")
        return None, str(e)


def get_agent_wallet_from_private_key(private_key: str) -> Tuple[str, str]:
    """
    Get address from agent private key.
    
    Args:
        private_key: Agent wallet private key
        
    Returns:
        Tuple of (address, private_key with 0x prefix)
    """
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    
    account = Account.from_key(private_key)
    return account.address, private_key

