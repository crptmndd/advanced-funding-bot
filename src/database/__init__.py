"""Database module for user management and wallet storage."""

from .models import (
    User,
    Wallet,
    UserSettings,
    WalletType,
    SubscriptionTier,
    HyperliquidApiKey,
    HyperliquidChain,
    OKXApiKey,
)
from .database import Database, get_database, close_database
from .encryption import encrypt_private_key, decrypt_private_key
from .wallet_generator import generate_evm_wallet, generate_solana_wallet

__all__ = [
    "User",
    "Wallet", 
    "UserSettings",
    "WalletType",
    "SubscriptionTier",
    "HyperliquidApiKey",
    "HyperliquidChain",
    "OKXApiKey",
    "Database",
    "get_database",
    "close_database",
    "encrypt_private_key",
    "decrypt_private_key",
    "generate_evm_wallet",
    "generate_solana_wallet",
]

