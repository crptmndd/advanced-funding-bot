"""Wallet generation utilities for EVM and Solana."""

from dataclasses import dataclass
from typing import Tuple

from eth_account import Account
from solders.keypair import Keypair


@dataclass
class GeneratedWallet:
    """Represents a newly generated wallet."""
    address: str
    private_key: str
    wallet_type: str  # "evm" or "solana"


def generate_evm_wallet() -> GeneratedWallet:
    """
    Generate a new EVM (Ethereum-compatible) wallet.
    
    Works with: Ethereum, BSC, Polygon, Arbitrum, Optimism, Base, etc.
    
    Returns:
        GeneratedWallet with address and private key
    """
    # Enable unaudited HD wallet features
    Account.enable_unaudited_hdwallet_features()
    
    # Generate new account
    account = Account.create()
    
    return GeneratedWallet(
        address=account.address,
        private_key=account.key.hex(),
        wallet_type="evm",
    )


def generate_solana_wallet() -> GeneratedWallet:
    """
    Generate a new Solana wallet.
    
    Returns:
        GeneratedWallet with address and private key (base58 encoded)
    """
    # Generate new keypair
    keypair = Keypair()
    
    return GeneratedWallet(
        address=str(keypair.pubkey()),
        private_key=str(keypair),  # Base58 encoded secret key
        wallet_type="solana",
    )


def get_evm_address_from_private_key(private_key: str) -> str:
    """
    Get EVM address from private key.
    
    Args:
        private_key: Hex-encoded private key (with or without 0x prefix)
        
    Returns:
        EVM address
    """
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    
    account = Account.from_key(private_key)
    return account.address


def get_solana_address_from_private_key(private_key: str) -> str:
    """
    Get Solana address from private key.
    
    Args:
        private_key: Base58 encoded secret key
        
    Returns:
        Solana address
    """
    keypair = Keypair.from_base58_string(private_key)
    return str(keypair.pubkey())


def validate_evm_address(address: str) -> bool:
    """Validate EVM address format."""
    if not address.startswith("0x"):
        return False
    if len(address) != 42:
        return False
    try:
        int(address, 16)
        return True
    except ValueError:
        return False


def validate_solana_address(address: str) -> bool:
    """Validate Solana address format."""
    # Solana addresses are base58 encoded, 32-44 characters
    if len(address) < 32 or len(address) > 44:
        return False
    
    # Check for valid base58 characters
    base58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return all(c in base58_chars for c in address)

