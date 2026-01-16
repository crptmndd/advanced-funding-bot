"""Database models for users, wallets and settings."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class WalletType(Enum):
    """Supported wallet types."""
    EVM = "evm"
    SOLANA = "solana"


class SubscriptionTier(Enum):
    """Subscription tiers."""
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    UNLIMITED = "unlimited"


class HyperliquidChain(Enum):
    """HyperLiquid chain types."""
    MAINNET = "Mainnet"
    TESTNET = "Testnet"


@dataclass
class User:
    """User model."""
    
    id: int  # Primary key (auto-increment)
    telegram_id: int  # Telegram user ID
    username: Optional[str] = None  # Telegram username
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    
    # Subscription
    subscription_tier: SubscriptionTier = SubscriptionTier.FREE
    subscription_expires: Optional[datetime] = None
    
    # Status
    is_active: bool = True
    is_banned: bool = False
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def has_active_subscription(self) -> bool:
        """Check if user has active subscription."""
        # For now, everyone has subscription
        return True
        # Future implementation:
        # if self.subscription_tier == SubscriptionTier.FREE:
        #     return True  # Free tier always active
        # if self.subscription_expires is None:
        #     return False
        # return self.subscription_expires > datetime.utcnow()
    
    @property
    def display_name(self) -> str:
        """Get display name for user."""
        if self.username:
            return f"@{self.username}"
        if self.first_name:
            if self.last_name:
                return f"{self.first_name} {self.last_name}"
            return self.first_name
        return f"User {self.telegram_id}"


@dataclass
class Wallet:
    """Wallet model for storing user wallets."""
    
    id: int  # Primary key
    user_id: int  # Foreign key to User
    
    wallet_type: WalletType  # EVM or Solana
    address: str  # Public address
    
    # Encrypted private key (stored securely)
    encrypted_private_key: str
    
    # Optional label
    label: Optional[str] = None
    
    # Status
    is_primary: bool = True  # Is this the primary wallet for this type
    is_active: bool = True
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def short_address(self) -> str:
        """Get shortened address for display."""
        if len(self.address) > 12:
            return f"{self.address[:6]}...{self.address[-4:]}"
        return self.address


@dataclass
class UserSettings:
    """User settings for trading."""
    
    id: int  # Primary key
    user_id: int  # Foreign key to User
    
    # Trading settings
    trade_amount_usdt: float = 100.0  # Default trade amount in USDT
    max_trade_amount_usdt: float = 1000.0  # Maximum trade amount
    
    # Risk settings
    max_leverage: int = 10  # Maximum leverage to use
    max_position_size_percent: float = 50.0  # Max % of balance per position
    
    # Filters
    min_funding_spread: float = 0.01  # Minimum spread to consider (%)
    max_price_spread: float = 1.0  # Maximum price difference (%)
    min_volume_24h: float = 100000.0  # Minimum 24h volume (USDT)
    
    # Notifications
    notify_opportunities: bool = True  # Notify about new opportunities
    notify_threshold_spread: float = 0.05  # Min spread for notifications (%)
    
    # Auto-trading (future)
    auto_trade_enabled: bool = False
    
    # Preferred exchanges (comma-separated)
    preferred_exchanges: str = ""  # Empty = all exchanges
    excluded_exchanges: str = ""  # Exchanges to exclude
    
    # Timestamps
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def get_preferred_exchanges_list(self) -> list:
        """Get list of preferred exchanges."""
        if not self.preferred_exchanges:
            return []
        return [e.strip().lower() for e in self.preferred_exchanges.split(",") if e.strip()]
    
    def get_excluded_exchanges_list(self) -> list:
        """Get list of excluded exchanges."""
        if not self.excluded_exchanges:
            return []
        return [e.strip().lower() for e in self.excluded_exchanges.split(",") if e.strip()]


@dataclass
class HyperliquidApiKey:
    """
    HyperLiquid API key model.
    
    HyperLiquid uses a special "agent wallet" system where you sign a message
    with your main wallet to authorize an "agent" (API wallet) to trade on your behalf.
    
    The agent wallet's private key is used for signing trading requests.
    """
    
    id: int  # Primary key
    user_id: int  # Foreign key to User
    wallet_id: int  # Foreign key to EVM Wallet used to create this API key
    
    # Agent wallet info (the API key itself)
    agent_address: str  # Public address of the agent wallet
    encrypted_agent_private_key: str  # Encrypted private key of agent wallet
    
    # API key metadata
    agent_name: str  # Name given to the API key (e.g., "api2 valid_until 1784064998102")
    
    # Chain info
    chain: HyperliquidChain = HyperliquidChain.MAINNET
    
    # Validity
    valid_until: datetime = field(default_factory=datetime.utcnow)  # When the API key expires
    nonce: int = 0  # Nonce used when creating the key
    
    # Status
    is_active: bool = True
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def is_valid(self) -> bool:
        """Check if API key is still valid (not expired)."""
        return self.is_active and self.valid_until > datetime.utcnow()
    
    @property
    def days_until_expiry(self) -> int:
        """Get days until API key expires."""
        if not self.is_valid:
            return 0
        delta = self.valid_until - datetime.utcnow()
        return max(0, delta.days)
    
    @property
    def short_agent_address(self) -> str:
        """Get shortened agent address for display."""
        if len(self.agent_address) > 12:
            return f"{self.agent_address[:6]}...{self.agent_address[-4:]}"
        return self.agent_address

