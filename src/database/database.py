"""SQLite database for user management."""

import os
import logging
import aiosqlite
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from .models import User, Wallet, UserSettings, WalletType, SubscriptionTier, HyperliquidApiKey, HyperliquidChain, OKXApiKey
from .encryption import encrypt_private_key, decrypt_private_key
from .wallet_generator import generate_evm_wallet, generate_solana_wallet


# Logger
logger = logging.getLogger(__name__)

# Flag to enable/disable auto HyperLiquid API key creation
# NOTE: Disabled because HyperLiquid requires a deposit before API key can be created
AUTO_CREATE_HYPERLIQUID_API_KEY = False

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "funding_bot.db"


class Database:
    """SQLite database manager for user data."""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path or os.getenv("DATABASE_PATH") or str(DEFAULT_DB_PATH)
        self._connection: Optional[aiosqlite.Connection] = None
    
    async def connect(self) -> None:
        """Connect to database and create tables if needed."""
        # Ensure directory exists
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Connecting to database: {self.db_path}")
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        
        # Create tables
        await self._create_tables()
        logger.info("Database connected and tables initialized")
    
    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
    
    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        async with self._connection.cursor() as cursor:
            # Users table
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    subscription_tier TEXT DEFAULT 'free',
                    subscription_expires TEXT,
                    is_active INTEGER DEFAULT 1,
                    is_banned INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_activity TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Wallets table
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS wallets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    wallet_type TEXT NOT NULL,
                    address TEXT NOT NULL,
                    encrypted_private_key TEXT NOT NULL,
                    label TEXT,
                    is_primary INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            
            # User settings table
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE NOT NULL,
                    trade_amount_usdt REAL DEFAULT 100.0,
                    max_trade_amount_usdt REAL DEFAULT 1000.0,
                    max_leverage INTEGER DEFAULT 10,
                    max_position_size_percent REAL DEFAULT 50.0,
                    min_funding_spread REAL DEFAULT 0.01,
                    max_price_spread REAL DEFAULT 1.0,
                    min_volume_24h REAL DEFAULT 100000.0,
                    notify_opportunities INTEGER DEFAULT 1,
                    notify_threshold_spread REAL DEFAULT 0.05,
                    auto_trade_enabled INTEGER DEFAULT 0,
                    preferred_exchanges TEXT DEFAULT '',
                    excluded_exchanges TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            
            # HyperLiquid API keys table
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS hyperliquid_api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    wallet_id INTEGER NOT NULL,
                    agent_address TEXT NOT NULL,
                    encrypted_agent_private_key TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    chain TEXT DEFAULT 'Mainnet',
                    valid_until TEXT NOT NULL,
                    nonce INTEGER NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (wallet_id) REFERENCES wallets (id) ON DELETE CASCADE
                )
            """)
            
            # OKX API keys table
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS okx_api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    encrypted_api_key TEXT NOT NULL,
                    encrypted_secret_key TEXT NOT NULL,
                    encrypted_passphrase TEXT NOT NULL,
                    label TEXT DEFAULT 'OKX Trading',
                    is_sandbox INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes
            await cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users (telegram_id)"
            )
            await cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_wallets_user_id ON wallets (user_id)"
            )
            await cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_hl_api_keys_user_id ON hyperliquid_api_keys (user_id)"
            )
            await cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_hl_api_keys_wallet_id ON hyperliquid_api_keys (wallet_id)"
            )
            await cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_okx_api_keys_user_id ON okx_api_keys (user_id)"
            )
            
            await self._connection.commit()
    
    # ==================== User Operations ====================
    
    async def get_user(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID."""
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return None
            
            return self._row_to_user(row)
    
    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by internal ID."""
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return None
            
            return self._row_to_user(row)
    
    async def create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> User:
        """
        Create a new user with wallets and HyperLiquid API key.
        
        This will:
        1. Create user record
        2. Generate EVM wallet
        3. Generate Solana wallet
        4. Create default settings
        5. Create HyperLiquid API key (if enabled)
        """
        logger.info(f"Creating new user: telegram_id={telegram_id}, username={username}")
        
        async with self._connection.cursor() as cursor:
            # Insert user
            await cursor.execute("""
                INSERT INTO users (telegram_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, username, first_name, last_name))
            
            user_id = cursor.lastrowid
            await self._connection.commit()
        
        logger.info(f"User created with internal ID: {user_id}")
        
        # Get created user
        user = await self.get_user_by_id(user_id)
        
        # Generate wallets
        logger.info(f"Generating wallets for user {user_id}...")
        await self._generate_user_wallets(user_id)
        
        # Create default settings
        logger.info(f"Creating default settings for user {user_id}...")
        await self._create_default_settings(user_id)
        
        # Create HyperLiquid API key (if enabled)
        if AUTO_CREATE_HYPERLIQUID_API_KEY:
            logger.info(f"Creating HyperLiquid API key for user {user_id}...")
            await self._create_hyperliquid_api_key(user_id)
        
        logger.info(f"User {telegram_id} fully registered with wallets, settings, and API keys")
        return user
    
    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> User:
        """Get existing user or create new one."""
        user = await self.get_user(telegram_id)
        
        if user is None:
            logger.info(f"New user detected: telegram_id={telegram_id}")
            user = await self.create_user(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
        else:
            logger.debug(f"Existing user: telegram_id={telegram_id}, id={user.id}")
            # Update last activity
            await self.update_user_activity(telegram_id)
        
        return user
    
    async def update_user_activity(self, telegram_id: int) -> None:
        """Update user's last activity timestamp."""
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                UPDATE users 
                SET last_activity = ?, updated_at = ?
                WHERE telegram_id = ?
            """, (datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), telegram_id))
            await self._connection.commit()
    
    async def get_all_users(self, active_only: bool = True) -> List[User]:
        """Get all users."""
        async with self._connection.cursor() as cursor:
            if active_only:
                await cursor.execute(
                    "SELECT * FROM users WHERE is_active = 1 AND is_banned = 0"
                )
            else:
                await cursor.execute("SELECT * FROM users")
            
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows]
    
    def _row_to_user(self, row: aiosqlite.Row) -> User:
        """Convert database row to User object."""
        subscription_expires = None
        if row["subscription_expires"]:
            subscription_expires = datetime.fromisoformat(row["subscription_expires"])
        
        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            subscription_tier=SubscriptionTier(row["subscription_tier"]),
            subscription_expires=subscription_expires,
            is_active=bool(row["is_active"]),
            is_banned=bool(row["is_banned"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_activity=datetime.fromisoformat(row["last_activity"]),
        )
    
    # ==================== Wallet Operations ====================
    
    async def _generate_user_wallets(self, user_id: int) -> None:
        """Generate EVM and Solana wallets for user."""
        try:
            # Generate EVM wallet
            logger.debug(f"Generating EVM wallet for user {user_id}...")
            evm_wallet = generate_evm_wallet()
            await self._save_wallet(
                user_id=user_id,
                wallet_type=WalletType.EVM,
                address=evm_wallet.address,
                private_key=evm_wallet.private_key,
                label="Primary EVM Wallet",
            )
            logger.info(f"EVM wallet created for user {user_id}: {evm_wallet.address[:10]}...")
            
            # Generate Solana wallet
            logger.debug(f"Generating Solana wallet for user {user_id}...")
            sol_wallet = generate_solana_wallet()
            await self._save_wallet(
                user_id=user_id,
                wallet_type=WalletType.SOLANA,
                address=sol_wallet.address,
                private_key=sol_wallet.private_key,
                label="Primary Solana Wallet",
            )
            logger.info(f"Solana wallet created for user {user_id}: {sol_wallet.address[:10]}...")
            
        except Exception as e:
            logger.error(f"Failed to generate wallets for user {user_id}: {e}", exc_info=True)
            raise
    
    async def _create_hyperliquid_api_key(self, user_id: int, chain: str = "Mainnet") -> bool:
        """
        Create HyperLiquid API key for user.
        
        This creates an agent wallet and registers it with HyperLiquid.
        The agent wallet can then be used for trading.
        
        Args:
            user_id: User ID
            chain: "Mainnet" or "Testnet"
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Import here to avoid circular imports
            from src.exchanges.hyperliquid_auth import (
                create_agent_key,
                register_agent_with_hyperliquid,
            )
            
            # Get user's EVM wallet
            wallet = await self.get_user_wallet(user_id, WalletType.EVM)
            if not wallet:
                logger.error(f"No EVM wallet found for user {user_id}")
                return False
            
            logger.info(f"[HL API Key] Creating for user {user_id}, wallet {wallet.short_address}")
            
            # Get wallet private key
            private_key = await self.get_wallet_private_key(wallet.id)
            if not private_key:
                logger.error(f"Failed to get wallet private key for user {user_id}")
                return False
            
            # Create agent key (locally)
            logger.info(f"[HL API Key] Generating agent wallet and signing approval...")
            agent_key = create_agent_key(
                main_wallet_private_key=private_key,
                validity_days=180,
                chain=chain,
            )
            
            # Register with HyperLiquid
            logger.info(f"[HL API Key] Registering agent with HyperLiquid API...")
            success, error = await register_agent_with_hyperliquid(
                agent_key=agent_key,
                main_wallet_address=wallet.address,
            )
            
            if not success:
                logger.error(f"[HL API Key] Registration failed for user {user_id}: {error}")
                # Don't raise - user is still created, just without HL API key
                return False
            
            # Save to database
            logger.info(f"[HL API Key] Saving to database...")
            await self.save_hyperliquid_api_key(
                user_id=user_id,
                wallet_id=wallet.id,
                agent_address=agent_key.agent_address,
                agent_private_key=agent_key.agent_private_key,
                agent_name=agent_key.agent_name,
                chain=chain,
                valid_until=agent_key.valid_until,
                nonce=agent_key.nonce,
            )
            
            logger.info(f"[HL API Key] Successfully created for user {user_id}")
            logger.info(f"[HL API Key] Agent: {agent_key.agent_address[:10]}..., valid until {agent_key.valid_until.date()}")
            return True
            
        except Exception as e:
            logger.error(f"[HL API Key] Failed to create for user {user_id}: {e}", exc_info=True)
            # Don't raise - user is still created, just without HL API key
            return False
    
    async def _save_wallet(
        self,
        user_id: int,
        wallet_type: WalletType,
        address: str,
        private_key: str,
        label: Optional[str] = None,
    ) -> int:
        """Save wallet to database with encrypted private key."""
        encrypted_key = encrypt_private_key(private_key)
        
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO wallets (user_id, wallet_type, address, encrypted_private_key, label)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, wallet_type.value, address, encrypted_key, label))
            
            wallet_id = cursor.lastrowid
            await self._connection.commit()
            
            return wallet_id
    
    async def get_user_wallets(self, user_id: int) -> List[Wallet]:
        """Get all wallets for a user."""
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT * FROM wallets WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            rows = await cursor.fetchall()
            
            return [self._row_to_wallet(row) for row in rows]
    
    async def get_user_wallet(
        self,
        user_id: int,
        wallet_type: WalletType,
    ) -> Optional[Wallet]:
        """Get primary wallet of specific type for user."""
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                SELECT * FROM wallets 
                WHERE user_id = ? AND wallet_type = ? AND is_primary = 1 AND is_active = 1
            """, (user_id, wallet_type.value))
            
            row = await cursor.fetchone()
            if row is None:
                return None
            
            return self._row_to_wallet(row)
    
    async def get_wallet_private_key(self, wallet_id: int) -> Optional[str]:
        """
        Get decrypted private key for wallet.
        
        WARNING: Handle with care! Only use when absolutely necessary.
        """
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT encrypted_private_key FROM wallets WHERE id = ?",
                (wallet_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return None
            
            return decrypt_private_key(row["encrypted_private_key"])
    
    def _row_to_wallet(self, row: aiosqlite.Row) -> Wallet:
        """Convert database row to Wallet object."""
        return Wallet(
            id=row["id"],
            user_id=row["user_id"],
            wallet_type=WalletType(row["wallet_type"]),
            address=row["address"],
            encrypted_private_key=row["encrypted_private_key"],
            label=row["label"],
            is_primary=bool(row["is_primary"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
    
    # ==================== Settings Operations ====================
    
    async def _create_default_settings(self, user_id: int) -> None:
        """Create default settings for user."""
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO user_settings (user_id)
                VALUES (?)
            """, (user_id,))
            await self._connection.commit()
    
    async def get_user_settings(self, user_id: int) -> Optional[UserSettings]:
        """Get settings for user."""
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT * FROM user_settings WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return None
            
            return self._row_to_settings(row)
    
    async def update_user_settings(
        self,
        user_id: int,
        **kwargs,
    ) -> None:
        """
        Update user settings.
        
        Args:
            user_id: User ID
            **kwargs: Settings to update (e.g., trade_amount_usdt=500)
        """
        if not kwargs:
            return
        
        # Build update query
        set_clauses = []
        values = []
        
        allowed_fields = [
            "trade_amount_usdt", "max_trade_amount_usdt", "max_leverage",
            "max_position_size_percent", "min_funding_spread", "max_price_spread",
            "min_volume_24h", "notify_opportunities", "notify_threshold_spread",
            "auto_trade_enabled", "preferred_exchanges", "excluded_exchanges",
        ]
        
        for key, value in kwargs.items():
            if key in allowed_fields:
                set_clauses.append(f"{key} = ?")
                values.append(value)
        
        if not set_clauses:
            return
        
        # Add updated_at
        set_clauses.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        
        values.append(user_id)
        
        query = f"UPDATE user_settings SET {', '.join(set_clauses)} WHERE user_id = ?"
        
        async with self._connection.cursor() as cursor:
            await cursor.execute(query, values)
            await self._connection.commit()
    
    def _row_to_settings(self, row: aiosqlite.Row) -> UserSettings:
        """Convert database row to UserSettings object."""
        return UserSettings(
            id=row["id"],
            user_id=row["user_id"],
            trade_amount_usdt=row["trade_amount_usdt"],
            max_trade_amount_usdt=row["max_trade_amount_usdt"],
            max_leverage=row["max_leverage"],
            max_position_size_percent=row["max_position_size_percent"],
            min_funding_spread=row["min_funding_spread"],
            max_price_spread=row["max_price_spread"],
            min_volume_24h=row["min_volume_24h"],
            notify_opportunities=bool(row["notify_opportunities"]),
            notify_threshold_spread=row["notify_threshold_spread"],
            auto_trade_enabled=bool(row["auto_trade_enabled"]),
            preferred_exchanges=row["preferred_exchanges"] or "",
            excluded_exchanges=row["excluded_exchanges"] or "",
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
    
    # ==================== HyperLiquid API Key Operations ====================
    
    async def save_hyperliquid_api_key(
        self,
        user_id: int,
        wallet_id: int,
        agent_address: str,
        agent_private_key: str,
        agent_name: str,
        chain: str,
        valid_until: datetime,
        nonce: int,
    ) -> int:
        """
        Save a HyperLiquid API key to the database.
        
        Args:
            user_id: User ID
            wallet_id: Wallet ID (the EVM wallet used to create this API key)
            agent_address: Public address of the agent wallet
            agent_private_key: Private key of the agent wallet (will be encrypted)
            agent_name: Name of the agent
            chain: "Mainnet" or "Testnet"
            valid_until: When the API key expires
            nonce: Nonce used when creating the key
            
        Returns:
            ID of the created API key record
        """
        logger.info(f"[DB] Saving HyperLiquid API key for user {user_id}")
        logger.debug(f"[DB] Agent address: {agent_address[:10]}...")
        logger.debug(f"[DB] Chain: {chain}, Valid until: {valid_until.isoformat()}")
        
        encrypted_key = encrypt_private_key(agent_private_key)
        
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO hyperliquid_api_keys 
                (user_id, wallet_id, agent_address, encrypted_agent_private_key, 
                 agent_name, chain, valid_until, nonce)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, wallet_id, agent_address, encrypted_key,
                agent_name, chain, valid_until.isoformat(), nonce,
            ))
            
            api_key_id = cursor.lastrowid
            await self._connection.commit()
            
            logger.info(f"[DB] HyperLiquid API key saved with ID: {api_key_id}")
            return api_key_id
    
    async def get_hyperliquid_api_key(
        self,
        user_id: int,
        chain: str = "Mainnet",
        active_only: bool = True,
    ) -> Optional[HyperliquidApiKey]:
        """
        Get HyperLiquid API key for a user.
        
        Args:
            user_id: User ID
            chain: "Mainnet" or "Testnet"
            active_only: Only return active keys
            
        Returns:
            HyperliquidApiKey or None if not found
        """
        logger.debug(f"[DB] Getting HyperLiquid API key for user {user_id}, chain={chain}")
        
        async with self._connection.cursor() as cursor:
            query = """
                SELECT * FROM hyperliquid_api_keys 
                WHERE user_id = ? AND chain = ?
            """
            params = [user_id, chain]
            
            if active_only:
                query += " AND is_active = 1"
            
            query += " ORDER BY created_at DESC LIMIT 1"
            
            await cursor.execute(query, params)
            row = await cursor.fetchone()
            
            if row is None:
                logger.debug(f"[DB] No HyperLiquid API key found for user {user_id}")
                return None
            
            return self._row_to_hyperliquid_api_key(row)
    
    async def get_hyperliquid_api_key_private_key(self, api_key_id: int) -> Optional[str]:
        """
        Get decrypted private key for HyperLiquid API key.
        
        WARNING: Handle with care! Only use when absolutely necessary.
        
        Args:
            api_key_id: ID of the API key record
            
        Returns:
            Decrypted agent private key or None
        """
        logger.debug(f"[DB] Getting HyperLiquid API key private key for ID {api_key_id}")
        
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT encrypted_agent_private_key FROM hyperliquid_api_keys WHERE id = ?",
                (api_key_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return None
            
            return decrypt_private_key(row["encrypted_agent_private_key"])
    
    async def get_all_hyperliquid_api_keys(
        self,
        user_id: int,
        active_only: bool = True,
    ) -> List[HyperliquidApiKey]:
        """
        Get all HyperLiquid API keys for a user.
        
        Args:
            user_id: User ID
            active_only: Only return active keys
            
        Returns:
            List of HyperliquidApiKey objects
        """
        async with self._connection.cursor() as cursor:
            query = "SELECT * FROM hyperliquid_api_keys WHERE user_id = ?"
            params = [user_id]
            
            if active_only:
                query += " AND is_active = 1"
            
            query += " ORDER BY created_at DESC"
            
            await cursor.execute(query, params)
            rows = await cursor.fetchall()
            
            return [self._row_to_hyperliquid_api_key(row) for row in rows]
    
    async def deactivate_hyperliquid_api_key(self, api_key_id: int) -> None:
        """
        Deactivate a HyperLiquid API key.
        
        Args:
            api_key_id: ID of the API key to deactivate
        """
        logger.info(f"[DB] Deactivating HyperLiquid API key ID {api_key_id}")
        
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE hyperliquid_api_keys SET is_active = 0 WHERE id = ?",
                (api_key_id,)
            )
            await self._connection.commit()
    
    async def has_valid_hyperliquid_api_key(
        self,
        user_id: int,
        chain: str = "Mainnet",
    ) -> bool:
        """
        Check if user has a valid (active and not expired) HyperLiquid API key.
        
        Args:
            user_id: User ID
            chain: "Mainnet" or "Testnet"
            
        Returns:
            True if user has a valid API key
        """
        api_key = await self.get_hyperliquid_api_key(user_id, chain)
        
        if api_key is None:
            return False
        
        return api_key.is_valid
    
    def _row_to_hyperliquid_api_key(self, row: aiosqlite.Row) -> HyperliquidApiKey:
        """Convert database row to HyperliquidApiKey object."""
        return HyperliquidApiKey(
            id=row["id"],
            user_id=row["user_id"],
            wallet_id=row["wallet_id"],
            agent_address=row["agent_address"],
            encrypted_agent_private_key=row["encrypted_agent_private_key"],
            agent_name=row["agent_name"],
            chain=HyperliquidChain(row["chain"]),
            valid_until=datetime.fromisoformat(row["valid_until"]),
            nonce=row["nonce"],
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
    
    # ==================== OKX API Key Operations ====================
    
    async def save_okx_api_key(
        self,
        user_id: int,
        api_key: str,
        secret_key: str,
        passphrase: str,
        label: str = "OKX Trading",
        is_sandbox: bool = False,
    ) -> int:
        """
        Save an OKX API key to the database.
        
        Args:
            user_id: User ID
            api_key: OKX API key
            secret_key: OKX secret key
            passphrase: OKX passphrase
            label: User-defined label
            is_sandbox: Whether this is a sandbox key
            
        Returns:
            ID of the created API key record
        """
        logger.info(f"[DB] Saving OKX API key for user {user_id}")
        
        # Encrypt credentials
        encrypted_api_key = encrypt_private_key(api_key)
        encrypted_secret_key = encrypt_private_key(secret_key)
        encrypted_passphrase = encrypt_private_key(passphrase)
        
        # Deactivate any existing OKX API keys for this user
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE okx_api_keys SET is_active = 0 WHERE user_id = ?",
                (user_id,)
            )
            
            # Insert new key
            await cursor.execute("""
                INSERT INTO okx_api_keys 
                (user_id, encrypted_api_key, encrypted_secret_key, encrypted_passphrase, label, is_sandbox)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_id, encrypted_api_key, encrypted_secret_key, encrypted_passphrase, label, int(is_sandbox),
            ))
            
            api_key_id = cursor.lastrowid
            await self._connection.commit()
            
            logger.info(f"[DB] OKX API key saved with ID: {api_key_id}")
            return api_key_id
    
    async def get_okx_api_key(
        self,
        user_id: int,
        active_only: bool = True,
    ) -> Optional[OKXApiKey]:
        """
        Get OKX API key for a user.
        
        Args:
            user_id: User ID
            active_only: Only return active keys
            
        Returns:
            OKXApiKey or None if not found
        """
        logger.debug(f"[DB] Getting OKX API key for user {user_id}")
        
        async with self._connection.cursor() as cursor:
            query = "SELECT * FROM okx_api_keys WHERE user_id = ?"
            params = [user_id]
            
            if active_only:
                query += " AND is_active = 1"
            
            query += " ORDER BY created_at DESC LIMIT 1"
            
            await cursor.execute(query, params)
            row = await cursor.fetchone()
            
            if row is None:
                logger.debug(f"[DB] No OKX API key found for user {user_id}")
                return None
            
            return self._row_to_okx_api_key(row)
    
    async def get_okx_api_key_credentials(self, api_key_id: int) -> Optional[dict]:
        """
        Get decrypted OKX API credentials.
        
        WARNING: Handle with care!
        
        Args:
            api_key_id: ID of the API key record
            
        Returns:
            Dict with api_key, secret_key, passphrase or None
        """
        logger.debug(f"[DB] Getting OKX API credentials for ID {api_key_id}")
        
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT encrypted_api_key, encrypted_secret_key, encrypted_passphrase FROM okx_api_keys WHERE id = ?",
                (api_key_id,)
            )
            row = await cursor.fetchone()
            
            if row is None:
                return None
            
            return {
                "api_key": decrypt_private_key(row["encrypted_api_key"]),
                "secret_key": decrypt_private_key(row["encrypted_secret_key"]),
                "passphrase": decrypt_private_key(row["encrypted_passphrase"]),
            }
    
    async def has_okx_api_key(self, user_id: int) -> bool:
        """Check if user has an active OKX API key."""
        api_key = await self.get_okx_api_key(user_id)
        return api_key is not None and api_key.is_valid
    
    async def deactivate_okx_api_key(self, api_key_id: int) -> None:
        """Deactivate an OKX API key."""
        logger.info(f"[DB] Deactivating OKX API key ID {api_key_id}")
        
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE okx_api_keys SET is_active = 0, updated_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), api_key_id)
            )
            await self._connection.commit()
    
    def _row_to_okx_api_key(self, row: aiosqlite.Row) -> OKXApiKey:
        """Convert database row to OKXApiKey object."""
        return OKXApiKey(
            id=row["id"],
            user_id=row["user_id"],
            encrypted_api_key=row["encrypted_api_key"],
            encrypted_secret_key=row["encrypted_secret_key"],
            encrypted_passphrase=row["encrypted_passphrase"],
            label=row["label"] or "OKX Trading",
            is_sandbox=bool(row["is_sandbox"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
    
    # ==================== Statistics ====================
    
    async def get_stats(self) -> dict:
        """Get database statistics."""
        async with self._connection.cursor() as cursor:
            # Total users
            await cursor.execute("SELECT COUNT(*) FROM users")
            total_users = (await cursor.fetchone())[0]
            
            # Active users
            await cursor.execute(
                "SELECT COUNT(*) FROM users WHERE is_active = 1 AND is_banned = 0"
            )
            active_users = (await cursor.fetchone())[0]
            
            # Total wallets
            await cursor.execute("SELECT COUNT(*) FROM wallets WHERE is_active = 1")
            total_wallets = (await cursor.fetchone())[0]
            
            # Total HyperLiquid API keys
            await cursor.execute("SELECT COUNT(*) FROM hyperliquid_api_keys WHERE is_active = 1")
            total_hl_api_keys = (await cursor.fetchone())[0]
            
            return {
                "total_users": total_users,
                "active_users": active_users,
                "total_wallets": total_wallets,
                "total_hl_api_keys": total_hl_api_keys,
            }


# Global database instance
_db: Optional[Database] = None


async def get_database() -> Database:
    """Get or create database instance."""
    global _db
    
    if _db is None:
        _db = Database()
        await _db.connect()
    
    return _db


async def close_database() -> None:
    """Close database connection."""
    global _db
    
    if _db is not None:
        await _db.close()
        _db = None

