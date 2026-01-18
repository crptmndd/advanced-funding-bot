"""
Telegram bot for funding rate arbitrage using aiogram.

Features:
- Reply keyboard with main function buttons
- HyperLiquid trading integration
- Arbitrum bridge for USDC deposits
- Funding rate analysis
"""

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from src.exchanges.registry import ExchangeRegistry
from src.exchanges.arbitrum_bridge import (
    get_usdc_balance,
    get_eth_balance,
    deposit_usdc_to_hyperliquid,
    MIN_DEPOSIT_USDC,
)
from src.services.arbitrage_analyzer import ArbitrageAnalyzer, AnalyzerConfig
from src.services.hyperliquid_service import HyperliquidService
from src.services.okx_service import OKXService
from src.services.withdrawal_tracker import WithdrawalTracker, get_withdrawal_tracker
from src.services.funding_cache import FundingRateCache, get_funding_cache, start_funding_cache
from src.config import get_config
from src.database import Database, get_database, WalletType, decrypt_private_key
from .formatters import TelegramFormatter

logger = logging.getLogger(__name__)


# ============================================================
# States for FSM (Finite State Machine)
# ============================================================
class OrderStates(StatesGroup):
    """States for order placement."""
    waiting_for_symbol = State()
    waiting_for_amount = State()
    waiting_for_price = State()


# ============================================================
# Reply Keyboard Markup (Main Menu)
# ============================================================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Create main menu keyboard."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Rates"),
                KeyboardButton(text="💹 Arbitrage"),
            ],
            [
                KeyboardButton(text="🟢 HyperLiquid"),
                KeyboardButton(text="🌉 Bridge"),
            ],
            [
                KeyboardButton(text="💰 Positions"),
                KeyboardButton(text="📋 Orders"),
            ],
            [
                KeyboardButton(text="👛 Wallet"),
                KeyboardButton(text="⚙️ Settings"),
            ],
            [
                KeyboardButton(text="❓ Help"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
    return keyboard


def get_trading_keyboard() -> ReplyKeyboardMarkup:
    """Create trading menu keyboard."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📈 Buy"),
                KeyboardButton(text="📉 Sell"),
            ],
            [
                KeyboardButton(text="❌ Close Position"),
                KeyboardButton(text="🔧 Set Leverage"),
            ],
            [
                KeyboardButton(text="🔙 Back to Menu"),
            ],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Create cancel keyboard."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )
    return keyboard


# ============================================================
# Bot Class
# ============================================================
class FundingBot:
    """Telegram bot for funding rate arbitrage using aiogram."""
    
    def __init__(self, token: str):
        """Initialize the bot."""
        self.token = token
        self.bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.dp = Dispatcher(storage=MemoryStorage())
        self.router = Router()
        self.formatter = TelegramFormatter()
        self.db: Optional[Database] = None
        self.hl_service: Optional[HyperliquidService] = None
        self.okx_service: Optional[OKXService] = None
        
        # Register handlers
        self._register_handlers()
    
    def _register_handlers(self) -> None:
        """Register all message and callback handlers."""
        # Command handlers
        self.router.message.register(self.start_command, CommandStart())
        self.router.message.register(self.help_command, Command("help"))
        self.router.message.register(self.rates_command, Command("rates"))
        self.router.message.register(self.arbitrage_command, Command("arbitrage"))
        self.router.message.register(self.exchanges_command, Command("exchanges"))
        self.router.message.register(self.wallet_command, Command("wallet"))
        self.router.message.register(self.settings_command, Command("settings"))
        self.router.message.register(self.set_command, Command("set"))
        
        # HyperLiquid commands
        self.router.message.register(self.hl_status_command, Command("hl"))
        self.router.message.register(self.hl_setup_command, Command("hl_setup"))
        self.router.message.register(self.hl_buy_command, Command("hl_buy"))
        self.router.message.register(self.hl_sell_command, Command("hl_sell"))
        self.router.message.register(self.hl_close_command, Command("hl_close"))
        self.router.message.register(self.hl_positions_command, Command("hl_positions"))
        self.router.message.register(self.hl_orders_command, Command("hl_orders"))
        self.router.message.register(self.hl_cancel_command, Command("hl_cancel"))
        self.router.message.register(self.hl_leverage_command, Command("hl_leverage"))
        self.router.message.register(self.hl_withdraw_command, Command("hl_withdraw"))
        self.router.message.register(self.bridge_command, Command("bridge"))
        self.router.message.register(self.export_keys_command, Command("export_keys"))
        
        # OKX commands
        self.router.message.register(self.okx_status_command, Command("okx"))
        self.router.message.register(self.okx_setup_command, Command("okx_setup"))
        self.router.message.register(self.okx_buy_command, Command("okx_buy"))
        self.router.message.register(self.okx_sell_command, Command("okx_sell"))
        self.router.message.register(self.okx_close_command, Command("okx_close"))
        self.router.message.register(self.okx_positions_command, Command("okx_positions"))
        self.router.message.register(self.okx_orders_command, Command("okx_orders"))
        self.router.message.register(self.okx_cancel_command, Command("okx_cancel"))
        self.router.message.register(self.okx_leverage_command, Command("okx_leverage"))
        
        # Button handlers (Reply Keyboard)
        self.router.message.register(self.handle_rates_button, F.text == "📊 Rates")
        self.router.message.register(self.handle_arbitrage_button, F.text == "💹 Arbitrage")
        self.router.message.register(self.handle_hl_button, F.text == "🟢 HyperLiquid")
        self.router.message.register(self.handle_bridge_button, F.text == "🌉 Bridge")
        self.router.message.register(self.handle_positions_button, F.text == "💰 Positions")
        self.router.message.register(self.handle_orders_button, F.text == "📋 Orders")
        self.router.message.register(self.handle_wallet_button, F.text == "👛 Wallet")
        self.router.message.register(self.handle_settings_button, F.text == "⚙️ Settings")
        self.router.message.register(self.handle_help_button, F.text == "❓ Help")
        self.router.message.register(self.handle_buy_button, F.text == "📈 Buy")
        self.router.message.register(self.handle_sell_button, F.text == "📉 Sell")
        self.router.message.register(self.handle_close_button, F.text == "❌ Close Position")
        self.router.message.register(self.handle_leverage_button, F.text == "🔧 Set Leverage")
        self.router.message.register(self.handle_back_button, F.text == "🔙 Back to Menu")
        self.router.message.register(self.handle_cancel_button, F.text == "❌ Cancel")
        
        # Callback query handlers (Inline Keyboard)
        self.router.callback_query.register(self.handle_deposit_callback, F.data.startswith("deposit_"))
        self.router.callback_query.register(self.handle_bridge_callback, F.data.startswith("bridge_"))
        self.router.callback_query.register(self.handle_export_callback, F.data.startswith("export_"))
        self.router.callback_query.register(self.handle_settings_callback, F.data.startswith("settings_"))
        
        # Add router to dispatcher
        self.dp.include_router(self.router)
    
    async def setup(self) -> None:
        """Initialize database and services."""
        self.db = await get_database()
        logger.info("Database initialized")
        
        self.hl_service = HyperliquidService(self.db)
        logger.info("HyperLiquid service initialized")
        
        self.okx_service = OKXService(self.db)
        logger.info("OKX service initialized")
        
        # Initialize withdrawal tracker with notification callback
        self.withdrawal_tracker = get_withdrawal_tracker()
        self.withdrawal_tracker.set_notification_callback(self._send_withdrawal_notification)
        logger.info("Withdrawal tracker initialized")
        
        # Start funding rate cache if enabled
        config = get_config()
        if config.funding.cache_enabled:
            self.funding_cache = await start_funding_cache()
            logger.info("Funding rate cache started")
        
        # Set bot commands
        commands = [
            BotCommand(command="start", description="Start the bot"),
            BotCommand(command="help", description="Show help"),
            BotCommand(command="rates", description="Get funding rates"),
            BotCommand(command="arbitrage", description="Find arbitrage"),
            BotCommand(command="hl", description="HyperLiquid status"),
            BotCommand(command="bridge", description="Deposit USDC"),
            BotCommand(command="wallet", description="View wallets"),
            BotCommand(command="settings", description="Settings"),
            BotCommand(command="set", description="Update a setting"),
        ]
        await self.bot.set_my_commands(commands)
    
    async def _send_withdrawal_notification(self, withdrawal_info, message: str) -> None:
        """Send withdrawal notification to user via Telegram."""
        try:
            await self.bot.send_message(
                chat_id=withdrawal_info.telegram_user_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            logger.info(f"Sent withdrawal notification to user {withdrawal_info.telegram_user_id}")
        except Exception as e:
            logger.error(f"Failed to send withdrawal notification: {e}")
    
    async def _ensure_user(self, user_id: int, username: str = None, 
                           first_name: str = None, last_name: str = None) -> None:
        """Ensure user exists in database."""
        if not self.db:
            self.db = await get_database()
        
        await self.db.get_or_create_user(
            telegram_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        logger.info(f"User authenticated: {user_id} (@{username or 'no_username'})")
    
    async def _get_hl_service(self) -> HyperliquidService:
        """Get or create HyperLiquid service."""
        if not self.hl_service:
            if not self.db:
                self.db = await get_database()
            self.hl_service = HyperliquidService(self.db)
        return self.hl_service
    
    async def _get_okx_service(self) -> OKXService:
        """Get or create OKX service."""
        if not self.okx_service:
            if not self.db:
                self.db = await get_database()
            self.okx_service = OKXService(self.db)
        return self.okx_service
    
    # ============================================================
    # Command Handlers
    # ============================================================
    
    async def start_command(self, message: Message) -> None:
        """Handle /start command."""
        user = message.from_user
        logger.info(f"[/start] User {user.id} started bot")
        
        await self._ensure_user(user.id, user.username, user.first_name, user.last_name)
        
        text = (
            "🚀 <b>Welcome to Funding Rate Arbitrage Bot!</b>\n\n"
            "This bot helps you:\n"
            "• Track funding rates across exchanges\n"
            "• Find arbitrage opportunities\n"
            "• Trade on HyperLiquid\n"
            "• Manage your crypto wallets\n\n"
            "Use the buttons below or type /help for commands."
        )
        
        await message.answer(text, reply_markup=get_main_keyboard())
    
    async def help_command(self, message: Message) -> None:
        """Handle /help command."""
        await self._ensure_user(message.from_user.id, message.from_user.username)
        
        text = self.formatter.format_help()
        await message.answer(text)
    
    async def rates_command(self, message: Message) -> None:
        """Handle /rates command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/rates] User {user.id} args: {args}")
        
        await self._ensure_user(user.id, user.username)
        
        try:
            # Parse arguments
            exchanges = []
            limit = 10
            force_refresh = False
            
            for arg in args:
                if arg.isdigit():
                    limit = min(int(arg), 50)
                elif arg.lower() == "refresh":
                    force_refresh = True
                else:
                    exchanges.append(arg.lower())
            
            # Check if cache is available
            config = get_config()
            cache = get_funding_cache()
            
            if config.funding.cache_enabled and cache.is_cached and not force_refresh:
                # Use cached data
                cache_info = cache.get_cache_info()
                loading_msg = await message.answer(
                    f"📊 Loading rates from cache (updated {int(cache_info['age_seconds'])}s ago)..."
                )
                all_rates = await cache.get_all_rates(
                    exchanges=exchanges if exchanges else None,
                    force_refresh=False,
                )
            else:
                loading_msg = await message.answer("⏳ Fetching funding rates...")
                # Fetch fresh data
                all_rates = await ExchangeRegistry.fetch_all_funding_rates(
                    exchanges=exchanges if exchanges else None,
                    use_cache=True,
                )
            
            if not all_rates:
                await loading_msg.edit_text("❌ No funding rates available.")
                return
            
            text = self.formatter.format_funding_rates(all_rates, limit)
            await loading_msg.edit_text(text)
            
        except Exception as e:
            logger.exception("[/rates] Error")
            await message.answer(f"❌ Error: {str(e)}")
    
    async def arbitrage_command(self, message: Message) -> None:
        """Handle /arbitrage command with optional exchange filtering."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/arbitrage] User {user.id} args: {args}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        # Parse arguments: exchange names and/or limit
        # Example: /arbitrage okx hyperliquid 15
        limit = 10
        exchange_filter = []
        
        for arg in args:
            if arg.isdigit():
                limit = min(int(arg), 30)
            else:
                # Normalize exchange name
                exchange_name = arg.lower()
                # Map common aliases
                exchange_aliases = {
                    "hl": "hyperliquid",
                    "hyper": "hyperliquid",
                    "okx": "okx",
                    "binance": "binance",
                    "bybit": "bybit",
                    "bitget": "bitget",
                    "gate": "gate",
                    "gateio": "gate",
                    "mexc": "mexc",
                    "backpack": "backpack",
                    "drift": "drift",
                    "bingx": "bingx",
                }
                exchange_name = exchange_aliases.get(exchange_name, exchange_name)
                exchange_filter.append(exchange_name)
        
        filter_text = f" ({', '.join(exchange_filter)})" if exchange_filter else ""
        loading_msg = await message.answer(f"⏳ Analyzing arbitrage opportunities{filter_text}...")
        
        try:
            # Fetch rates - pass exchange filter to fetch only from specified exchanges
            registry = ExchangeRegistry()
            
            if exchange_filter:
                # Fetch only from specified exchanges
                all_rates = await registry.fetch_all_funding_rates(exchanges=exchange_filter)
            else:
                # Fetch from all exchanges
                all_rates = await registry.fetch_all_funding_rates()
            
            if not all_rates:
                if exchange_filter:
                    await loading_msg.edit_text(
                        f"❌ No rates found for exchanges: {', '.join(exchange_filter)}\n\n"
                        f"<b>Available exchanges:</b>\n"
                        f"hyperliquid, okx, binance, bybit, bitget, gate, mexc, backpack, drift, bingx"
                    )
                else:
                    await loading_msg.edit_text("❌ No funding rates available.")
                return
            
            # Analyze - all_rates is List[ExchangeFundingRates]
            config = AnalyzerConfig(
                min_funding_spread=settings.min_funding_spread,
                min_volume_24h=settings.min_volume_24h,
            )
            analyzer = ArbitrageAnalyzer(config)
            opportunities = analyzer.find_opportunities(all_rates, limit)
            
            if not opportunities:
                filter_info = f" for {', '.join(exchange_filter)}" if exchange_filter else ""
                await loading_msg.edit_text(
                    f"❌ No arbitrage opportunities found{filter_info}.\n"
                    f"Min spread: {settings.min_funding_spread}%"
                )
                return
            
            text = self.formatter.format_arbitrage_opportunities(opportunities, settings)
            
            # Add filter info to header if filtered
            if exchange_filter:
                text = text.replace(
                    "💹 <b>Arbitrage Opportunities</b>",
                    f"💹 <b>Arbitrage: {' vs '.join([e.upper() for e in exchange_filter])}</b>"
                )
            
            await loading_msg.edit_text(text)
            
        except Exception as e:
            logger.exception("[/arbitrage] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def exchanges_command(self, message: Message) -> None:
        """Handle /exchanges command."""
        await self._ensure_user(message.from_user.id, message.from_user.username)
        
        registry = ExchangeRegistry()
        exchanges = registry.get_available_exchanges()
        
        text = self.formatter.format_exchanges(exchanges)
        await message.answer(text)
    
    async def wallet_command(self, message: Message) -> None:
        """Handle /wallet command."""
        user = message.from_user
        logger.info(f"[/wallet] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        wallets = await self.db.get_user_wallets(db_user.id)
        
        if not wallets:
            await message.answer("❌ No wallets found. Something went wrong.")
            return
        
        text = self.formatter.format_wallets(wallets)
        await message.answer(text)
    
    async def settings_command(self, message: Message) -> None:
        """Handle /settings command."""
        user = message.from_user
        await self._ensure_user(user.id, user.username)
        
        db_user = await self.db.get_user(user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        text = self.formatter.format_settings(settings)
        await message.answer(text)
    
    async def set_command(self, message: Message) -> None:
        """Handle /set command to customize trading settings."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        
        await self._ensure_user(user.id, user.username)
        
        if len(args) < 2:
            config = get_config()
            await message.answer(
                "⚙️ <b>Settings Configuration</b>\n\n"
                "<b>Usage:</b> <code>/set &lt;setting&gt; &lt;value&gt;</code>\n\n"
                "<b>Trading Settings:</b>\n"
                "• <code>amount</code> - Default trade amount (USDT)\n"
                "• <code>maxamount</code> - Max trade amount (USDT)\n"
                f"• <code>leverage</code> - Max leverage (1-{config.trading.max_leverage})\n\n"
                "<b>Arbitrage Filters:</b>\n"
                "• <code>spread</code> - Min funding spread (%, e.g. 0.01)\n"
                "• <code>volume</code> - Min 24h volume (USD)\n"
                "• <code>pricespread</code> - Max price spread (%)\n\n"
                "<b>Notifications:</b>\n"
                "• <code>notify</code> - Enable notifications (1/0)\n"
                "• <code>threshold</code> - Notify threshold spread (%)\n\n"
                "<b>Examples:</b>\n"
                "• <code>/set leverage 20</code>\n"
                "• <code>/set spread 0.02</code>\n"
                "• <code>/set volume 500000</code>"
            )
            return
        
        setting_name = args[0].lower()
        try:
            value = float(args[1])
        except ValueError:
            await message.answer("❌ Invalid value. Please enter a number.")
            return
        
        db_user = await self.db.get_user(user.id)
        config = get_config()
        
        # Map setting names to database field names
        setting_map = {
            "amount": ("trade_amount_usdt", 1, config.trading.max_trade_amount, "Trade amount"),
            "maxamount": ("max_trade_amount_usdt", 1, 100000, "Max trade amount"),
            "leverage": ("max_leverage", 1, config.trading.max_leverage, "Max leverage"),
            "spread": ("min_funding_spread", 0, 10, "Min funding spread"),
            "volume": ("min_volume_24h", 0, 100000000, "Min 24h volume"),
            "pricespread": ("max_price_spread", 0, 10, "Max price spread"),
            "notify": ("notify_opportunities", 0, 1, "Notify opportunities"),
            "threshold": ("notify_threshold_spread", 0, 10, "Notify threshold"),
        }
        
        if setting_name not in setting_map:
            await message.answer(
                f"❌ Unknown setting: <code>{setting_name}</code>\n\n"
                "Use <code>/set</code> to see available settings."
            )
            return
        
        db_field, min_val, max_val, display_name = setting_map[setting_name]
        
        # Validate range
        if value < min_val or value > max_val:
            await message.answer(f"❌ {display_name} must be between {min_val} and {max_val}")
            return
        
        # Convert to int for integer fields
        if db_field in ("max_leverage", "notify_opportunities"):
            value = int(value)
        
        # Update setting
        try:
            await self.db.update_user_settings(db_user.id, **{db_field: value})
            await message.answer(
                f"✅ <b>{display_name}</b> updated to <code>{value}</code>"
            )
        except Exception as e:
            logger.error(f"[/set] Error updating setting: {e}")
            await message.answer("❌ Failed to update setting")
    
    # ============================================================
    # HyperLiquid Commands
    # ============================================================
    
    async def hl_status_command(self, message: Message) -> None:
        """Handle /hl command - HyperLiquid status."""
        user = message.from_user
        logger.info(f"[/hl] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        
        loading_msg = await message.answer("⏳ Loading HyperLiquid status...")
        
        try:
            hl_service = await self._get_hl_service()
            api_status = await hl_service.get_api_key_status(db_user.id)
            
            lines = ["🟢 <b>HyperLiquid Status</b>", ""]
            
            if api_status['is_valid']:
                lines.append(f"API Key: ✅ Active")
                lines.append(f"Agent: <code>{api_status['agent_address'][:16]}...</code>")
                lines.append(f"Expires: {api_status['valid_until'][:10]} ({api_status['days_until_expiry']} days)")
                
                # Get account info
                client, error = await hl_service.get_trading_client(db_user.id, True)
                if client:
                    account_state = await client.get_account_state()
                    if account_state:
                        lines.append("")
                        lines.append("💰 <b>Account:</b>")
                        lines.append(f"Value: <code>${account_state.account_value:,.2f}</code>")
                        lines.append(f"Available: <code>${account_state.available_balance:,.2f}</code>")
                        
                        if account_state.positions:
                            lines.append(f"Positions: <code>{len(account_state.positions)}</code>")
            else:
                lines.append("API Key: ❌ Not set up")
                lines.append("")
                lines.append("Use /hl_setup to create API key")
            
            await loading_msg.edit_text("\n".join(lines))
            
        except Exception as e:
            logger.exception("[/hl] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def hl_setup_command(self, message: Message) -> None:
        """Handle /hl_setup command."""
        user = message.from_user
        logger.info(f"[/hl_setup] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        
        # Check if API key exists
        hl_service = await self._get_hl_service()
        api_status = await hl_service.get_api_key_status(db_user.id)
        
        if api_status['is_valid']:
            await message.answer(
                f"✅ <b>API Key Already Active</b>\n\n"
                f"Agent: <code>{api_status['agent_address']}</code>\n"
                f"Expires: {api_status['valid_until'][:10]}\n\n"
                f"Use /hl for account status."
            )
            return
        
        # Get wallet
        wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
        if not wallet:
            await message.answer("❌ No EVM wallet found. Please try /start first.")
            return
        
        loading_msg = await message.answer(
            f"⏳ <b>Checking Arbitrum Balance...</b>\n\n"
            f"Wallet: <code>{wallet.address}</code>"
        )
        
        try:
            # Check balances
            usdc_balance, _ = await asyncio.to_thread(get_usdc_balance, wallet.address)
            eth_balance = await asyncio.to_thread(get_eth_balance, wallet.address)
            
            lines = [
                "💰 <b>Arbitrum Balance</b>",
                "",
                f"Wallet: <code>{wallet.address}</code>",
                "",
                f"USDC: <b>{usdc_balance:.2f}</b>",
                f"ETH (gas): <b>{eth_balance:.6f}</b>",
            ]
            
            if usdc_balance >= MIN_DEPOSIT_USDC:
                if eth_balance < 0.00001:
                    lines.extend(["", "⚠️ Low ETH for gas fees"])
                    await loading_msg.edit_text("\n".join(lines))
                    return
                
                lines.extend([
                    "",
                    "─" * 25,
                    "",
                    f"🚀 Deposit <b>{usdc_balance:.2f} USDC</b> to HyperLiquid?",
                ])
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"✅ Deposit {usdc_balance:.2f} USDC",
                        callback_data="deposit_confirm"
                    )],
                    [InlineKeyboardButton(text="❌ Cancel", callback_data="deposit_cancel")],
                ])
                
                await loading_msg.edit_text("\n".join(lines), reply_markup=keyboard)
            else:
                lines.extend([
                    "",
                    f"⚠️ Need min {MIN_DEPOSIT_USDC} USDC",
                    f"Send USDC to: <code>{wallet.address}</code>",
                ])
                await loading_msg.edit_text("\n".join(lines))
                
        except Exception as e:
            logger.exception("[/hl_setup] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def hl_buy_command(self, message: Message) -> None:
        """Handle /hl_buy command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/hl_buy] User {user.id} args: {args}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        if len(args) < 2:
            await message.answer(
                "📈 <b>Buy Order (Long)</b>\n\n"
                "<b>Usage:</b>\n"
                "<code>/hl_buy &lt;symbol&gt; &lt;margin&gt; [leverage] [price]</code>\n\n"
                "<b>Parameters:</b>\n"
                "• <code>margin</code> - Margin amount in USDT\n"
                "• <code>leverage</code> - Leverage (default from settings)\n"
                "• <code>price</code> - Limit price (optional, market if omitted)\n\n"
                "<b>Examples:</b>\n"
                "<code>/hl_buy ETH 100</code> - Market buy, $100 margin\n"
                "<code>/hl_buy ETH 100 10</code> - Market buy, $100 margin, 10x\n"
                "<code>/hl_buy BTC 50 20 97000</code> - Limit buy at $97k, $50 margin, 20x\n\n"
                f"<i>Default leverage: {settings.max_leverage}x</i>"
            )
            return
        
        symbol = args[0].upper()
        try:
            margin_usdt = float(args[1])
        except ValueError:
            await message.answer("❌ Invalid margin amount")
            return
        
        if margin_usdt < 1:
            await message.answer("❌ Minimum margin is $1 USDT")
            return
        
        # Parse leverage (optional, default from settings)
        leverage = settings.max_leverage
        price = None
        
        if len(args) >= 3:
            try:
                leverage = int(args[2])
                if leverage < 1 or leverage > 100:
                    await message.answer("❌ Leverage must be between 1 and 100")
                    return
            except ValueError:
                # Maybe it's price without leverage
                try:
                    price = float(args[2])
                except ValueError:
                    await message.answer("❌ Invalid leverage or price")
                    return
        
        # Parse price (optional)
        if len(args) >= 4 and price is None:
            try:
                price = float(args[3])
            except ValueError:
                await message.answer("❌ Invalid price")
                return
        
        position_value = margin_usdt * leverage
        loading_msg = await message.answer(
            f"⏳ Placing BUY order...\n"
            f"Margin: ${margin_usdt:.2f} × {leverage}x = ${position_value:.2f} position"
        )
        
        try:
            hl_service = await self._get_hl_service()
            
            result, error = await hl_service.place_order_by_margin(
                user_id=db_user.id,
                symbol=symbol,
                side="buy",
                margin_usdt=margin_usdt,
                leverage=leverage,
                price=price,
                is_market=(price is None),
            )
            
            if result and result.success:
                price_text = f"@ ${result.average_price:,.2f}" if result.average_price else "market"
                await loading_msg.edit_text(
                    f"✅ <b>BUY Order {result.status or 'submitted'}</b>\n\n"
                    f"Symbol: <code>{symbol}</code>\n"
                    f"Margin: <code>${margin_usdt:.2f}</code>\n"
                    f"Leverage: <code>{leverage}x</code>\n"
                    f"Position: <code>${position_value:.2f}</code>\n"
                    f"Price: <code>{price_text}</code>\n"
                    f"Order ID: <code>{result.order_id or 'N/A'}</code>"
                )
            else:
                await loading_msg.edit_text(f"❌ Order failed: {error or result.error if result else 'Unknown'}")
                
        except Exception as e:
            logger.exception("[/hl_buy] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def hl_sell_command(self, message: Message) -> None:
        """Handle /hl_sell command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/hl_sell] User {user.id} args: {args}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        if len(args) < 2:
            await message.answer(
                "📉 <b>Sell Order (Short)</b>\n\n"
                "<b>Usage:</b>\n"
                "<code>/hl_sell &lt;symbol&gt; &lt;margin&gt; [leverage] [price]</code>\n\n"
                "<b>Parameters:</b>\n"
                "• <code>margin</code> - Margin amount in USDT\n"
                "• <code>leverage</code> - Leverage (default from settings)\n"
                "• <code>price</code> - Limit price (optional, market if omitted)\n\n"
                "<b>Examples:</b>\n"
                "<code>/hl_sell ETH 100</code> - Market short, $100 margin\n"
                "<code>/hl_sell ETH 100 10</code> - Market short, $100 margin, 10x\n"
                "<code>/hl_sell BTC 50 20 97000</code> - Limit short at $97k, $50 margin, 20x\n\n"
                f"<i>Default leverage: {settings.max_leverage}x</i>"
            )
            return
        
        symbol = args[0].upper()
        try:
            margin_usdt = float(args[1])
        except ValueError:
            await message.answer("❌ Invalid margin amount")
            return
        
        if margin_usdt < 1:
            await message.answer("❌ Minimum margin is $1 USDT")
            return
        
        # Parse leverage (optional, default from settings)
        leverage = settings.max_leverage
        price = None
        
        if len(args) >= 3:
            try:
                leverage = int(args[2])
                if leverage < 1 or leverage > 100:
                    await message.answer("❌ Leverage must be between 1 and 100")
                    return
            except ValueError:
                # Maybe it's price without leverage
                try:
                    price = float(args[2])
                except ValueError:
                    await message.answer("❌ Invalid leverage or price")
                    return
        
        # Parse price (optional)
        if len(args) >= 4 and price is None:
            try:
                price = float(args[3])
            except ValueError:
                await message.answer("❌ Invalid price")
                return
        
        position_value = margin_usdt * leverage
        loading_msg = await message.answer(
            f"⏳ Placing SELL order...\n"
            f"Margin: ${margin_usdt:.2f} × {leverage}x = ${position_value:.2f} position"
        )
        
        try:
            hl_service = await self._get_hl_service()
            
            result, error = await hl_service.place_order_by_margin(
                user_id=db_user.id,
                symbol=symbol,
                side="sell",
                margin_usdt=margin_usdt,
                leverage=leverage,
                price=price,
                is_market=(price is None),
            )
            
            if result and result.success:
                price_text = f"@ ${result.average_price:,.2f}" if result.average_price else "market"
                await loading_msg.edit_text(
                    f"✅ <b>SELL Order {result.status or 'submitted'}</b>\n\n"
                    f"Symbol: <code>{symbol}</code>\n"
                    f"Margin: <code>${margin_usdt:.2f}</code>\n"
                    f"Leverage: <code>{leverage}x</code>\n"
                    f"Position: <code>${position_value:.2f}</code>\n"
                    f"Price: <code>{price_text}</code>\n"
                    f"Order ID: <code>{result.order_id or 'N/A'}</code>"
                )
            else:
                await loading_msg.edit_text(f"❌ Order failed: {error or result.error if result else 'Unknown'}")
                
        except Exception as e:
            logger.exception("[/hl_sell] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def hl_close_command(self, message: Message) -> None:
        """Handle /hl_close command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/hl_close] User {user.id} args: {args}")
        
        await self._ensure_user(user.id, user.username)
        
        if not args:
            await message.answer(
                "❌ <b>Usage:</b> <code>/hl_close &lt;symbol&gt;</code>\n\n"
                "<b>Example:</b> <code>/hl_close BTC</code>"
            )
            return
        
        symbol = args[0].upper()
        loading_msg = await message.answer(f"⏳ Closing position for {symbol}...")
        
        try:
            db_user = await self.db.get_user(user.id)
            hl_service = await self._get_hl_service()
            
            result, error = await hl_service.close_position(db_user.id, symbol)
            
            if result and result.success:
                await loading_msg.edit_text(
                    f"✅ <b>Position Closed</b>\n\n"
                    f"Symbol: <code>{symbol}</code>\n"
                    f"Order ID: <code>{result.order_id or 'N/A'}</code>"
                )
            else:
                await loading_msg.edit_text(f"❌ Failed: {error or result.error if result else 'Unknown'}")
                
        except Exception as e:
            logger.exception("[/hl_close] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def hl_positions_command(self, message: Message) -> None:
        """Handle /hl_positions command."""
        user = message.from_user
        logger.info(f"[/hl_positions] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        
        loading_msg = await message.answer("⏳ Loading positions...")
        
        try:
            hl_service = await self._get_hl_service()
            positions, error = await hl_service.get_positions(db_user.id)
            
            if error:
                await loading_msg.edit_text(f"❌ {error}")
                return
            
            if not positions:
                await loading_msg.edit_text("📭 No open positions")
                return
            
            text = self.formatter.format_hyperliquid_positions(positions)
            await loading_msg.edit_text(text)
            
        except Exception as e:
            logger.exception("[/hl_positions] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def hl_orders_command(self, message: Message) -> None:
        """Handle /hl_orders command."""
        user = message.from_user
        logger.info(f"[/hl_orders] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        
        loading_msg = await message.answer("⏳ Loading orders...")
        
        try:
            hl_service = await self._get_hl_service()
            orders, error = await hl_service.get_open_orders(db_user.id)
            
            if error:
                await loading_msg.edit_text(f"❌ {error}")
                return
            
            if not orders:
                await loading_msg.edit_text("📭 No open orders")
                return
            
            text = self.formatter.format_hyperliquid_orders(orders)
            await loading_msg.edit_text(text)
            
        except Exception as e:
            logger.exception("[/hl_orders] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def hl_cancel_command(self, message: Message) -> None:
        """Handle /hl_cancel command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        
        await self._ensure_user(user.id, user.username)
        
        if len(args) < 2:
            await message.answer(
                "❌ <b>Usage:</b> <code>/hl_cancel &lt;symbol&gt; &lt;order_id&gt;</code>\n\n"
                "<b>Example:</b> <code>/hl_cancel BTC 12345</code>"
            )
            return
        
        symbol = args[0].upper()
        try:
            order_id = int(args[1])
        except ValueError:
            await message.answer("❌ Invalid order ID")
            return
        
        loading_msg = await message.answer(f"⏳ Cancelling order {order_id}...")
        
        try:
            db_user = await self.db.get_user(user.id)
            hl_service = await self._get_hl_service()
            
            result, error = await hl_service.cancel_order(db_user.id, symbol, order_id)
            
            if result and result.success:
                await loading_msg.edit_text(f"✅ Order {order_id} cancelled")
            else:
                await loading_msg.edit_text(f"❌ Failed: {error or result.error if result else 'Unknown'}")
                
        except Exception as e:
            logger.exception("[/hl_cancel] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def hl_leverage_command(self, message: Message) -> None:
        """Handle /hl_leverage command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        
        await self._ensure_user(user.id, user.username)
        
        if len(args) < 2:
            await message.answer(
                "❌ <b>Usage:</b> <code>/hl_leverage &lt;symbol&gt; &lt;leverage&gt;</code>\n\n"
                "<b>Example:</b> <code>/hl_leverage BTC 10</code>"
            )
            return
        
        symbol = args[0].upper()
        try:
            leverage = int(args[1])
        except ValueError:
            await message.answer("❌ Invalid leverage")
            return
        
        if leverage < 1 or leverage > 100:
            await message.answer("❌ Leverage must be 1-100")
            return
        
        loading_msg = await message.answer(f"⏳ Setting {symbol} leverage to {leverage}x...")
        
        try:
            db_user = await self.db.get_user(user.id)
            hl_service = await self._get_hl_service()
            
            success = await hl_service.set_leverage(db_user.id, symbol, leverage)
            
            if success:
                await loading_msg.edit_text(f"✅ {symbol} leverage set to <b>{leverage}x</b>")
            else:
                await loading_msg.edit_text("❌ Failed to set leverage")
                
        except Exception as e:
            logger.exception("[/hl_leverage] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def hl_withdraw_command(self, message: Message) -> None:
        """Handle /hl_withdraw command - withdraw USDC from HyperLiquid to Arbitrum."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/hl_withdraw] User {user.id} args: {args}")
        
        await self._ensure_user(user.id, user.username)
        
        if not args:
            await message.answer(
                "💸 <b>HyperLiquid Withdrawal</b>\n\n"
                "<b>Usage:</b> <code>/hl_withdraw &lt;amount&gt;</code>\n\n"
                "<b>Examples:</b>\n"
                "• <code>/hl_withdraw 100</code> - Withdraw $100\n"
                "• <code>/hl_withdraw all</code> - Withdraw all available\n\n"
                "<i>Note: ~$1 fee will be deducted.\n"
                "Funds go to your EVM wallet on Arbitrum.</i>"
            )
            return
        
        loading_msg = await message.answer("⏳ Processing withdrawal...")
        
        try:
            db_user = await self.db.get_user(user.id)
            hl_service = await self._get_hl_service()
            
            # Get account state to check balance
            account_state, error = await hl_service.get_account_state(db_user.id)
            if not account_state:
                await loading_msg.edit_text(f"❌ Failed to get account: {error}")
                return
            
            # Parse amount
            amount_str = args[0].lower()
            if amount_str == "all":
                amount = account_state.withdrawable - 1  # Leave ~$1 for fees
                if amount <= 0:
                    await loading_msg.edit_text(
                        f"❌ Insufficient withdrawable balance.\n"
                        f"Available: <code>${account_state.withdrawable:.2f}</code>"
                    )
                    return
            else:
                try:
                    amount = float(amount_str)
                except ValueError:
                    await loading_msg.edit_text("❌ Invalid amount")
                    return
            
            if amount <= 0:
                await loading_msg.edit_text("❌ Amount must be positive")
                return
            
            if amount > account_state.withdrawable:
                await loading_msg.edit_text(
                    f"❌ Insufficient withdrawable balance.\n"
                    f"Requested: <code>${amount:.2f}</code>\n"
                    f"Available: <code>${account_state.withdrawable:.2f}</code>"
                )
                return
            
            # Perform withdrawal
            await loading_msg.edit_text(f"⏳ Withdrawing ${amount:.2f} to Arbitrum...")
            
            success, error, response = await hl_service.withdraw_from_bridge(
                db_user.id, amount
            )
            
            if success:
                # Get wallet address for tracking
                wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
                wallet_address = wallet.address if wallet else ""
                
                # Extract transaction hash from response if available
                tx_hash = None
                if response:
                    # HyperLiquid may return tx hash in different formats
                    tx_hash = response.get("response", {}).get("data", {}).get("hash")
                    if not tx_hash:
                        tx_hash = response.get("hash")
                
                # Start tracking the withdrawal
                if hasattr(self, 'withdrawal_tracker') and self.withdrawal_tracker:
                    await self.withdrawal_tracker.track_withdrawal(
                        user_id=db_user.id,
                        telegram_user_id=user.id,
                        amount_usd=amount,
                        wallet_address=wallet_address,
                        tx_hash=tx_hash,
                    )
                    tracking_msg = "\n\n📡 <i>Tracking transaction... You'll be notified when confirmed.</i>"
                else:
                    tracking_msg = ""
                
                await loading_msg.edit_text(
                    f"✅ <b>Withdrawal Initiated</b>\n\n"
                    f"Amount: <code>${amount:.2f}</code>\n"
                    f"Network: Arbitrum\n"
                    f"Status: Processing\n\n"
                    f"<i>Note: ~$1 fee deducted. Arrival: 1-5 minutes.</i>"
                    f"{tracking_msg}"
                )
            else:
                await loading_msg.edit_text(f"❌ Withdrawal failed: {error}")
                
        except Exception as e:
            logger.exception("[/hl_withdraw] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def bridge_command(self, message: Message) -> None:
        """Handle /bridge command."""
        user = message.from_user
        logger.info(f"[/bridge] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        
        wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
        if not wallet:
            await message.answer("❌ No EVM wallet found")
            return
        
        loading_msg = await message.answer(
            f"⏳ Checking balances...\n"
            f"Wallet: <code>{wallet.address}</code>"
        )
        
        try:
            usdc_balance, _ = await asyncio.to_thread(get_usdc_balance, wallet.address)
            eth_balance = await asyncio.to_thread(get_eth_balance, wallet.address)
            
            # Try to get HL balance
            hl_balance = None
            try:
                hl_service = await self._get_hl_service()
                client, _ = await hl_service.get_trading_client(db_user.id, True)
                if client:
                    state = await client.get_account_state()
                    if state:
                        hl_balance = state.account_value
            except:
                pass
            
            lines = [
                "🌉 <b>Bridge Status</b>",
                "",
                f"<b>Wallet:</b> <code>{wallet.address}</code>",
                "",
                "<b>Arbitrum:</b>",
                f"├ USDC: <b>{usdc_balance:.2f}</b>",
                f"└ ETH: <b>{eth_balance:.6f}</b>",
            ]
            
            if hl_balance is not None:
                lines.extend(["", f"<b>HyperLiquid:</b> <b>${hl_balance:,.2f}</b>"])
            
            if usdc_balance >= MIN_DEPOSIT_USDC and eth_balance >= 0.00001:
                lines.extend(["", f"🚀 Deposit <b>{usdc_balance:.2f} USDC</b>?"])
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"✅ Deposit {usdc_balance:.2f} USDC",
                        callback_data="bridge_confirm"
                    )],
                    [InlineKeyboardButton(text="❌ Cancel", callback_data="bridge_cancel")],
                ])
                await loading_msg.edit_text("\n".join(lines), reply_markup=keyboard)
            else:
                if usdc_balance < MIN_DEPOSIT_USDC:
                    lines.append(f"\n⚠️ Need min {MIN_DEPOSIT_USDC} USDC")
                if eth_balance < 0.00001:
                    lines.append("⚠️ Need ETH for gas")
                await loading_msg.edit_text("\n".join(lines))
                
        except Exception as e:
            logger.exception("[/bridge] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def export_keys_command(self, message: Message) -> None:
        """Handle /export_keys command."""
        await self._ensure_user(message.from_user.id, message.from_user.username)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ Show Private Keys", callback_data="export_confirm")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="export_cancel")],
        ])
        
        await message.answer(
            "🔐 <b>Export Private Keys</b>\n\n"
            "⚠️ <b>WARNING:</b> Anyone with your private keys can steal your funds!\n\n"
            "Are you sure?",
            reply_markup=keyboard
        )
    
    # ============================================================
    # OKX Commands
    # ============================================================
    
    async def okx_status_command(self, message: Message) -> None:
        """Handle /okx command - OKX status."""
        user = message.from_user
        logger.info(f"[/okx] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        
        loading_msg = await message.answer("⏳ Loading OKX status...")
        
        try:
            okx_service = await self._get_okx_service()
            api_status = await okx_service.get_api_key_status(db_user.id)
            
            lines = ["🟠 <b>OKX Status</b>", ""]
            
            if api_status['exists'] and api_status['is_valid']:
                lines.append(f"API Key: ✅ Active")
                lines.append(f"Label: <code>{api_status['label']}</code>")
                lines.append(f"Mode: {'Sandbox' if api_status['is_sandbox'] else 'Live'}")
                
                # Get account info
                account_state, error = await okx_service.get_account_state(db_user.id)
                if account_state:
                    lines.append("")
                    lines.append("💰 <b>Account:</b>")
                    lines.append(f"Equity: <code>${account_state.total_equity:,.2f}</code>")
                    lines.append(f"Available: <code>${account_state.available_balance:,.2f}</code>")
                    
                    if account_state.positions:
                        lines.append(f"Positions: <code>{len(account_state.positions)}</code>")
            else:
                lines.append("API Key: ❌ Not set up")
                lines.append("")
                lines.append("Use /okx_setup to add your API key")
            
            await loading_msg.edit_text("\n".join(lines))
            
        except Exception as e:
            logger.exception("[/okx] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def okx_setup_command(self, message: Message) -> None:
        """Handle /okx_setup command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/okx_setup] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        
        if len(args) < 3:
            await message.answer(
                "🟠 <b>OKX API Setup</b>\n\n"
                "<b>Usage:</b>\n"
                "<code>/okx_setup API_KEY SECRET PASSPHRASE</code>\n\n"
                "<b>How to get API keys:</b>\n"
                "1. Go to OKX → Settings → API\n"
                "2. Create new API key\n"
                "3. Enable 'Trade' permission\n"
                "4. Copy API Key, Secret, and Passphrase\n\n"
                "<b>Example:</b>\n"
                "<code>/okx_setup abc123 xyz789 mypassphrase</code>\n\n"
                "⚠️ <b>Security:</b>\n"
                "• Never share your API keys\n"
                "• Use IP whitelist on OKX\n"
                "• Only enable 'Trade' permission"
            )
            return
        
        api_key = args[0]
        secret_key = args[1]
        passphrase = " ".join(args[2:])  # Passphrase might have spaces
        
        loading_msg = await message.answer("⏳ Verifying OKX credentials...")
        
        try:
            okx_service = await self._get_okx_service()
            success, error = await okx_service.save_api_key(
                user_id=db_user.id,
                api_key=api_key,
                secret_key=secret_key,
                passphrase=passphrase,
            )
            
            if success:
                await loading_msg.edit_text(
                    "✅ <b>OKX API Key Saved!</b>\n\n"
                    "Your OKX account is now connected.\n\n"
                    "<b>Commands:</b>\n"
                    "/okx - Account status\n"
                    "/okx_buy ETH 100 - Long $100 margin\n"
                    "/okx_sell ETH 100 - Short $100 margin\n"
                    "/okx_positions - View positions\n"
                    "/okx_close ETH - Close position"
                )
            else:
                await loading_msg.edit_text(f"❌ Failed to save API key: {error}")
                
        except Exception as e:
            logger.exception("[/okx_setup] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def okx_buy_command(self, message: Message) -> None:
        """Handle /okx_buy command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/okx_buy] User {user.id} args: {args}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        if len(args) < 2:
            await message.answer(
                "📈 <b>OKX Buy Order (Long)</b>\n\n"
                "<b>Usage:</b>\n"
                "<code>/okx_buy &lt;symbol&gt; &lt;margin&gt; [leverage] [price]</code>\n\n"
                "<b>Examples:</b>\n"
                "<code>/okx_buy ETH 100</code> - $100 margin, market\n"
                "<code>/okx_buy ETH 100 10</code> - $100 margin, 10x\n"
                "<code>/okx_buy BTC 50 20 97000</code> - limit at $97k\n\n"
                f"<i>Default leverage: {settings.max_leverage}x</i>"
            )
            return
        
        symbol = args[0].upper()
        try:
            margin_usdt = float(args[1])
        except ValueError:
            await message.answer("❌ Invalid margin amount")
            return
        
        if margin_usdt < 1:
            await message.answer("❌ Minimum margin is $1 USDT")
            return
        
        leverage = settings.max_leverage
        price = None
        
        if len(args) >= 3:
            try:
                leverage = int(args[2])
                if leverage < 1 or leverage > 100:
                    await message.answer("❌ Leverage must be between 1 and 100")
                    return
            except ValueError:
                try:
                    price = float(args[2])
                except ValueError:
                    await message.answer("❌ Invalid leverage or price")
                    return
        
        if len(args) >= 4 and price is None:
            try:
                price = float(args[3])
            except ValueError:
                await message.answer("❌ Invalid price")
                return
        
        position_value = margin_usdt * leverage
        loading_msg = await message.answer(
            f"⏳ Placing OKX BUY order...\n"
            f"Margin: ${margin_usdt:.2f} × {leverage}x = ${position_value:.2f} position"
        )
        
        try:
            okx_service = await self._get_okx_service()
            
            result, error = await okx_service.place_order_by_margin(
                user_id=db_user.id,
                symbol=symbol,
                side="buy",
                margin_usdt=margin_usdt,
                leverage=leverage,
                price=price,
                is_market=(price is None),
            )
            
            if result and result.success:
                price_text = f"@ ${result.average_price:,.2f}" if result.average_price else "market"
                await loading_msg.edit_text(
                    f"✅ <b>OKX BUY Order {result.status or 'submitted'}</b>\n\n"
                    f"Symbol: <code>{symbol}</code>\n"
                    f"Margin: <code>${margin_usdt:.2f}</code>\n"
                    f"Leverage: <code>{leverage}x</code>\n"
                    f"Position: <code>${position_value:.2f}</code>\n"
                    f"Price: <code>{price_text}</code>\n"
                    f"Order ID: <code>{result.order_id or 'N/A'}</code>"
                )
            else:
                await loading_msg.edit_text(f"❌ Order failed: {error or result.error if result else 'Unknown'}")
                
        except Exception as e:
            logger.exception("[/okx_buy] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def okx_sell_command(self, message: Message) -> None:
        """Handle /okx_sell command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/okx_sell] User {user.id} args: {args}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        if len(args) < 2:
            await message.answer(
                "📉 <b>OKX Sell Order (Short)</b>\n\n"
                "<b>Usage:</b>\n"
                "<code>/okx_sell &lt;symbol&gt; &lt;margin&gt; [leverage] [price]</code>\n\n"
                "<b>Examples:</b>\n"
                "<code>/okx_sell ETH 100</code> - $100 margin, market\n"
                "<code>/okx_sell ETH 100 10</code> - $100 margin, 10x\n"
                "<code>/okx_sell BTC 50 20 97000</code> - limit at $97k\n\n"
                f"<i>Default leverage: {settings.max_leverage}x</i>"
            )
            return
        
        symbol = args[0].upper()
        try:
            margin_usdt = float(args[1])
        except ValueError:
            await message.answer("❌ Invalid margin amount")
            return
        
        if margin_usdt < 1:
            await message.answer("❌ Minimum margin is $1 USDT")
            return
        
        leverage = settings.max_leverage
        price = None
        
        if len(args) >= 3:
            try:
                leverage = int(args[2])
                if leverage < 1 or leverage > 100:
                    await message.answer("❌ Leverage must be between 1 and 100")
                    return
            except ValueError:
                try:
                    price = float(args[2])
                except ValueError:
                    await message.answer("❌ Invalid leverage or price")
                    return
        
        if len(args) >= 4 and price is None:
            try:
                price = float(args[3])
            except ValueError:
                await message.answer("❌ Invalid price")
                return
        
        position_value = margin_usdt * leverage
        loading_msg = await message.answer(
            f"⏳ Placing OKX SELL order...\n"
            f"Margin: ${margin_usdt:.2f} × {leverage}x = ${position_value:.2f} position"
        )
        
        try:
            okx_service = await self._get_okx_service()
            
            result, error = await okx_service.place_order_by_margin(
                user_id=db_user.id,
                symbol=symbol,
                side="sell",
                margin_usdt=margin_usdt,
                leverage=leverage,
                price=price,
                is_market=(price is None),
            )
            
            if result and result.success:
                price_text = f"@ ${result.average_price:,.2f}" if result.average_price else "market"
                await loading_msg.edit_text(
                    f"✅ <b>OKX SELL Order {result.status or 'submitted'}</b>\n\n"
                    f"Symbol: <code>{symbol}</code>\n"
                    f"Margin: <code>${margin_usdt:.2f}</code>\n"
                    f"Leverage: <code>{leverage}x</code>\n"
                    f"Position: <code>${position_value:.2f}</code>\n"
                    f"Price: <code>{price_text}</code>\n"
                    f"Order ID: <code>{result.order_id or 'N/A'}</code>"
                )
            else:
                await loading_msg.edit_text(f"❌ Order failed: {error or result.error if result else 'Unknown'}")
                
        except Exception as e:
            logger.exception("[/okx_sell] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def okx_positions_command(self, message: Message) -> None:
        """Handle /okx_positions command."""
        user = message.from_user
        logger.info(f"[/okx_positions] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        
        loading_msg = await message.answer("⏳ Loading OKX positions...")
        
        try:
            okx_service = await self._get_okx_service()
            positions, error = await okx_service.get_positions(db_user.id)
            
            if error:
                await loading_msg.edit_text(f"❌ {error}")
                return
            
            if not positions:
                await loading_msg.edit_text("📭 No open positions on OKX")
                return
            
            text = self.formatter.format_okx_positions(positions)
            await loading_msg.edit_text(text)
            
        except Exception as e:
            logger.exception("[/okx_positions] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def okx_orders_command(self, message: Message) -> None:
        """Handle /okx_orders command."""
        user = message.from_user
        logger.info(f"[/okx_orders] User {user.id}")
        
        await self._ensure_user(user.id, user.username)
        db_user = await self.db.get_user(user.id)
        
        loading_msg = await message.answer("⏳ Loading OKX orders...")
        
        try:
            okx_service = await self._get_okx_service()
            orders, error = await okx_service.get_open_orders(db_user.id)
            
            if error:
                await loading_msg.edit_text(f"❌ {error}")
                return
            
            if not orders:
                await loading_msg.edit_text("📭 No open orders on OKX")
                return
            
            text = self.formatter.format_okx_orders(orders)
            await loading_msg.edit_text(text)
            
        except Exception as e:
            logger.exception("[/okx_orders] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def okx_close_command(self, message: Message) -> None:
        """Handle /okx_close command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        logger.info(f"[/okx_close] User {user.id} args: {args}")
        
        await self._ensure_user(user.id, user.username)
        
        if not args:
            await message.answer(
                "❌ <b>Usage:</b> <code>/okx_close &lt;symbol&gt;</code>\n\n"
                "<b>Example:</b> <code>/okx_close BTC</code>"
            )
            return
        
        symbol = args[0].upper()
        loading_msg = await message.answer(f"⏳ Closing OKX position for {symbol}...")
        
        try:
            db_user = await self.db.get_user(user.id)
            okx_service = await self._get_okx_service()
            
            result, error = await okx_service.close_position(db_user.id, symbol)
            
            if result and result.success:
                await loading_msg.edit_text(
                    f"✅ <b>Position Closed</b>\n\n"
                    f"Symbol: <code>{symbol}</code>"
                )
            else:
                await loading_msg.edit_text(f"❌ Failed: {error or result.error if result else 'Unknown'}")
                
        except Exception as e:
            logger.exception("[/okx_close] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def okx_cancel_command(self, message: Message) -> None:
        """Handle /okx_cancel command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        
        await self._ensure_user(user.id, user.username)
        
        if len(args) < 2:
            await message.answer(
                "❌ <b>Usage:</b> <code>/okx_cancel &lt;symbol&gt; &lt;order_id&gt;</code>\n\n"
                "<b>Example:</b> <code>/okx_cancel BTC 12345</code>"
            )
            return
        
        symbol = args[0].upper()
        order_id = args[1]
        
        loading_msg = await message.answer(f"⏳ Cancelling order {order_id}...")
        
        try:
            db_user = await self.db.get_user(user.id)
            okx_service = await self._get_okx_service()
            
            result, error = await okx_service.cancel_order(db_user.id, symbol, order_id)
            
            if result and result.success:
                await loading_msg.edit_text(f"✅ Order {order_id} cancelled")
            else:
                await loading_msg.edit_text(f"❌ Failed: {error or result.error if result else 'Unknown'}")
                
        except Exception as e:
            logger.exception("[/okx_cancel] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def okx_leverage_command(self, message: Message) -> None:
        """Handle /okx_leverage command."""
        user = message.from_user
        args = message.text.split()[1:] if message.text else []
        
        await self._ensure_user(user.id, user.username)
        
        if len(args) < 2:
            await message.answer(
                "❌ <b>Usage:</b> <code>/okx_leverage &lt;symbol&gt; &lt;leverage&gt;</code>\n\n"
                "<b>Example:</b> <code>/okx_leverage BTC 10</code>"
            )
            return
        
        symbol = args[0].upper()
        try:
            leverage = int(args[1])
        except ValueError:
            await message.answer("❌ Invalid leverage")
            return
        
        if leverage < 1 or leverage > 100:
            await message.answer("❌ Leverage must be 1-100")
            return
        
        loading_msg = await message.answer(f"⏳ Setting {symbol} leverage to {leverage}x...")
        
        try:
            db_user = await self.db.get_user(user.id)
            okx_service = await self._get_okx_service()
            
            success, error = await okx_service.set_leverage(db_user.id, symbol, leverage)
            
            if success:
                await loading_msg.edit_text(f"✅ {symbol} leverage set to <b>{leverage}x</b>")
            else:
                await loading_msg.edit_text(f"❌ Failed to set leverage: {error}")
                
        except Exception as e:
            logger.exception("[/okx_leverage] Error")
            await loading_msg.edit_text(f"❌ Error: {str(e)}")
    
    # ============================================================
    # Button Handlers (Reply Keyboard)
    # ============================================================
    
    async def handle_rates_button(self, message: Message) -> None:
        """Handle Rates button."""
        new_message = message.model_copy(update={"text": "/rates"})
        await self.rates_command(new_message)
    
    async def handle_arbitrage_button(self, message: Message) -> None:
        """Handle Arbitrage button."""
        new_message = message.model_copy(update={"text": "/arbitrage"})
        await self.arbitrage_command(new_message)
    
    async def handle_hl_button(self, message: Message) -> None:
        """Handle HyperLiquid button."""
        await self._ensure_user(message.from_user.id, message.from_user.username)
        await message.answer("🟢 <b>HyperLiquid Trading</b>\n\nSelect action:", 
                           reply_markup=get_trading_keyboard())
    
    async def handle_bridge_button(self, message: Message) -> None:
        """Handle Bridge button - show deposit/withdraw options."""
        await self._ensure_user(message.from_user.id, message.from_user.username)
        
        # Create inline keyboard with deposit/withdraw options
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📥 Deposit", callback_data="bridge_deposit"),
                InlineKeyboardButton(text="📤 Withdraw", callback_data="bridge_withdraw"),
            ],
            [
                InlineKeyboardButton(text="📊 Bridge Status", callback_data="bridge_status"),
            ],
        ])
        
        await message.answer(
            "🌉 <b>HyperLiquid Bridge</b>\n\n"
            "Select an action:\n\n"
            "• <b>Deposit</b> - Send USDC from Arbitrum to HyperLiquid\n"
            "• <b>Withdraw</b> - Send USDC from HyperLiquid to Arbitrum\n"
            "• <b>Status</b> - Check bridge status and balances",
            reply_markup=keyboard,
        )
    
    async def handle_positions_button(self, message: Message) -> None:
        """Handle Positions button."""
        new_message = message.model_copy(update={"text": "/hl_positions"})
        await self.hl_positions_command(new_message)
    
    async def handle_orders_button(self, message: Message) -> None:
        """Handle Orders button."""
        new_message = message.model_copy(update={"text": "/hl_orders"})
        await self.hl_orders_command(new_message)
    
    async def handle_wallet_button(self, message: Message) -> None:
        """Handle Wallet button."""
        new_message = message.model_copy(update={"text": "/wallet"})
        await self.wallet_command(new_message)
    
    async def handle_settings_button(self, message: Message) -> None:
        """Handle Settings button - show settings with inline options."""
        user = message.from_user
        await self._ensure_user(user.id, user.username)
        
        db_user = await self.db.get_user(user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        # Create inline keyboard for quick settings
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Trade Amount", callback_data="settings_amount"),
                InlineKeyboardButton(text="📊 Leverage", callback_data="settings_leverage"),
            ],
            [
                InlineKeyboardButton(text="📈 Min Spread", callback_data="settings_spread"),
                InlineKeyboardButton(text="💵 Min Volume", callback_data="settings_volume"),
            ],
            [
                InlineKeyboardButton(text="🔔 Notifications", callback_data="settings_notify"),
            ],
        ])
        
        text = self.formatter.format_settings(settings)
        text += "\n\n<i>Tap a button to change a setting, or use:</i>\n"
        text += "<code>/set &lt;setting&gt; &lt;value&gt;</code>"
        
        await message.answer(text, reply_markup=keyboard)
    
    async def handle_help_button(self, message: Message) -> None:
        """Handle Help button."""
        new_message = message.model_copy(update={"text": "/help"})
        await self.help_command(new_message)
    
    async def handle_buy_button(self, message: Message) -> None:
        """Handle Buy button."""
        await self._ensure_user(message.from_user.id, message.from_user.username)
        db_user = await self.db.get_user(message.from_user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        await message.answer(
            "📈 <b>Buy Order (Long)</b>\n\n"
            "Use command:\n"
            "<code>/hl_buy ETH 100</code> - $100 margin, market\n"
            "<code>/hl_buy ETH 100 10</code> - $100 margin, 10x leverage\n"
            "<code>/hl_buy BTC 50 20 97000</code> - $50 margin, 20x, limit $97k\n\n"
            f"<i>Your default leverage: {settings.max_leverage}x</i>"
        )
    
    async def handle_sell_button(self, message: Message) -> None:
        """Handle Sell button."""
        await self._ensure_user(message.from_user.id, message.from_user.username)
        db_user = await self.db.get_user(message.from_user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        await message.answer(
            "📉 <b>Sell Order (Short)</b>\n\n"
            "Use command:\n"
            "<code>/hl_sell ETH 100</code> - $100 margin, market\n"
            "<code>/hl_sell ETH 100 10</code> - $100 margin, 10x leverage\n"
            "<code>/hl_sell BTC 50 20 97000</code> - $50 margin, 20x, limit $97k\n\n"
            f"<i>Your default leverage: {settings.max_leverage}x</i>"
        )
    
    async def handle_close_button(self, message: Message) -> None:
        """Handle Close Position button."""
        await message.answer(
            "❌ <b>Close Position</b>\n\n"
            "Use: <code>/hl_close BTC</code>"
        )
    
    async def handle_leverage_button(self, message: Message) -> None:
        """Handle Set Leverage button."""
        await message.answer(
            "🔧 <b>Set Leverage</b>\n\n"
            "Use: <code>/hl_leverage BTC 10</code>"
        )
    
    async def handle_back_button(self, message: Message) -> None:
        """Handle Back button."""
        await message.answer("🔙 Back to main menu", reply_markup=get_main_keyboard())
    
    async def handle_cancel_button(self, message: Message, state: FSMContext) -> None:
        """Handle Cancel button."""
        await state.clear()
        await message.answer("❌ Cancelled", reply_markup=get_main_keyboard())
    
    # ============================================================
    # Callback Handlers (Inline Keyboard)
    # ============================================================
    
    async def handle_deposit_callback(self, callback: CallbackQuery) -> None:
        """Handle deposit confirmation callbacks."""
        user_id = callback.from_user.id
        data = callback.data
        
        await callback.answer()
        
        if data == "deposit_cancel":
            await callback.message.edit_text("❌ Deposit cancelled")
            return
        
        if data == "deposit_confirm":
            await self._perform_deposit_with_api_key(callback)
    
    async def handle_bridge_callback(self, callback: CallbackQuery) -> None:
        """Handle bridge callbacks."""
        user_id = callback.from_user.id
        data = callback.data
        
        await callback.answer()
        
        if data == "bridge_cancel":
            await callback.message.edit_text("❌ Cancelled")
            return
        
        if data == "bridge_confirm":
            await self._perform_deposit(callback)
            return
        
        if data == "bridge_deposit":
            # Show deposit instructions
            await self._ensure_user(user_id, callback.from_user.username)
            db_user = await self.db.get_user(user_id)
            wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
            
            if not wallet:
                await callback.message.edit_text(
                    "❌ No EVM wallet found. Use /wallet to create one."
                )
                return
            
            await callback.message.edit_text(
                "📥 <b>Deposit USDC to HyperLiquid</b>\n\n"
                f"<b>Your wallet:</b>\n<code>{wallet.address}</code>\n\n"
                "<b>Steps:</b>\n"
                "1️⃣ Send USDC (Arbitrum) to your wallet address above\n"
                "2️⃣ Use /bridge command to deposit from Arbitrum to HyperLiquid\n\n"
                "<b>Or deposit directly:</b>\n"
                "Send USDC to HyperLiquid L1 address from any wallet.\n\n"
                "<i>Min deposit: 5 USDC</i>"
            )
            return
        
        if data == "bridge_withdraw":
            # Show withdraw instructions
            await self._ensure_user(user_id, callback.from_user.username)
            db_user = await self.db.get_user(user_id)
            
            # Get account state
            hl_service = await self._get_hl_service()
            account_state, error = await hl_service.get_account_state(db_user.id)
            
            if not account_state:
                await callback.message.edit_text(
                    "❌ Could not get account state. Make sure you have a HyperLiquid API key setup.\n\n"
                    "Use /hl_setup to create one."
                )
                return
            
            await callback.message.edit_text(
                "📤 <b>Withdraw from HyperLiquid</b>\n\n"
                f"<b>Account value:</b> <code>${account_state.account_value:.2f}</code>\n"
                f"<b>Withdrawable:</b> <code>${account_state.withdrawable:.2f}</code>\n\n"
                "<b>To withdraw:</b>\n"
                "<code>/hl_withdraw &lt;amount&gt;</code>\n\n"
                "<b>Examples:</b>\n"
                "• <code>/hl_withdraw 100</code> - Withdraw $100\n"
                "• <code>/hl_withdraw all</code> - Withdraw all\n\n"
                "<i>Note: ~$1 fee. Funds go to your Arbitrum wallet.</i>"
            )
            return
        
        if data == "bridge_status":
            # Show bridge status - redirect to /bridge command
            fake_message = callback.message.model_copy(update={"text": "/bridge"})
            fake_message = fake_message.model_copy(update={"from_user": callback.from_user})
            await self.bridge_command(fake_message)
    
    async def handle_export_callback(self, callback: CallbackQuery) -> None:
        """Handle export keys callbacks."""
        user_id = callback.from_user.id
        data = callback.data
        
        await callback.answer()
        
        if data == "export_cancel":
            await callback.message.edit_text("✅ Export cancelled")
            return
        
        if data == "export_confirm":
            await self._ensure_user(user_id, callback.from_user.username)
            db_user = await self.db.get_user(user_id)
            wallets = await self.db.get_user_wallets(db_user.id)
            
            if not wallets:
                await callback.message.edit_text("❌ No wallets found")
                return
            
            lines = [
                "🔐 <b>PRIVATE KEYS</b>",
                "",
                "⚠️ DELETE THIS MESSAGE AFTER SAVING!",
                "",
            ]
            
            for wallet in wallets:
                pk = decrypt_private_key(wallet.encrypted_private_key)
                emoji = "🔷" if wallet.wallet_type == WalletType.EVM else "🟣"
                name = "EVM" if wallet.wallet_type == WalletType.EVM else "Solana"
                lines.extend([
                    f"{emoji} <b>{name}</b>",
                    f"<code>{wallet.address}</code>",
                    f"<code>{pk}</code>",
                    "",
                ])
            
            await callback.message.edit_text("\n".join(lines))
    
    async def handle_settings_callback(self, callback: CallbackQuery) -> None:
        """Handle settings inline button callbacks."""
        user_id = callback.from_user.id
        data = callback.data
        
        await callback.answer()
        await self._ensure_user(user_id, callback.from_user.username)
        
        db_user = await self.db.get_user(user_id)
        settings = await self.db.get_user_settings(db_user.id)
        config = get_config()
        
        # Define setting info
        setting_info = {
            "settings_amount": {
                "name": "Trade Amount",
                "field": "trade_amount_usdt",
                "current": settings.trade_amount_usdt if settings else 100,
                "unit": "USDT",
                "options": [50, 100, 250, 500, 1000],
            },
            "settings_leverage": {
                "name": "Max Leverage",
                "field": "max_leverage",
                "current": settings.max_leverage if settings else 10,
                "unit": "x",
                "options": [3, 5, 10, 15, 20],
            },
            "settings_spread": {
                "name": "Min Funding Spread",
                "field": "min_funding_spread",
                "current": settings.min_funding_spread if settings else 0.01,
                "unit": "%",
                "options": [0.005, 0.01, 0.02, 0.05, 0.1],
            },
            "settings_volume": {
                "name": "Min 24h Volume",
                "field": "min_volume_24h",
                "current": settings.min_volume_24h if settings else 100000,
                "unit": "USD",
                "options": [50000, 100000, 250000, 500000, 1000000],
            },
            "settings_notify": {
                "name": "Notifications",
                "field": "notify_opportunities",
                "current": 1 if settings and settings.notify_opportunities else 0,
                "unit": "",
                "options": [0, 1],
            },
        }
        
        # Check if setting a value
        if "_set_" in data:
            # Format: settings_amount_set_500
            parts = data.split("_set_")
            setting_key = parts[0]
            value = float(parts[1])
            
            if setting_key in setting_info:
                info = setting_info[setting_key]
                
                # Convert to int for specific fields
                if info["field"] in ("max_leverage", "notify_opportunities"):
                    value = int(value)
                
                await self.db.update_user_settings(db_user.id, **{info["field"]: value})
                
                # Format display value
                if info["field"] == "notify_opportunities":
                    display = "ON ✅" if value else "OFF ❌"
                elif info["field"] == "min_volume_24h":
                    display = f"${int(value):,}"
                else:
                    display = f"{value}{info['unit']}"
                
                await callback.message.edit_text(
                    f"✅ <b>{info['name']}</b> set to <code>{display}</code>\n\n"
                    f"Use ⚙️ Settings to view all settings."
                )
            return
        
        # Show options for the setting
        if data in setting_info:
            info = setting_info[data]
            
            # Create buttons for options
            buttons = []
            row = []
            
            for opt in info["options"]:
                # Format button text
                if info["field"] == "notify_opportunities":
                    text = "ON ✅" if opt else "OFF ❌"
                elif info["field"] == "min_volume_24h":
                    text = f"${int(opt/1000)}K"
                else:
                    text = f"{opt}{info['unit']}"
                
                # Highlight current value
                if opt == info["current"]:
                    text = f"• {text} •"
                
                row.append(InlineKeyboardButton(
                    text=text,
                    callback_data=f"{data}_set_{opt}"
                ))
                
                if len(row) >= 3:
                    buttons.append(row)
                    row = []
            
            if row:
                buttons.append(row)
            
            # Add back button
            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="settings_back")])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            # Format current value for display
            if info["field"] == "notify_opportunities":
                current_display = "ON ✅" if info["current"] else "OFF ❌"
            elif info["field"] == "min_volume_24h":
                current_display = f"${int(info['current']):,}"
            else:
                current_display = f"{info['current']}{info['unit']}"
            
            await callback.message.edit_text(
                f"⚙️ <b>{info['name']}</b>\n\n"
                f"Current: <code>{current_display}</code>\n\n"
                f"Select new value:",
                reply_markup=keyboard
            )
            return
        
        # Back to main settings
        if data == "settings_back":
            settings = await self.db.get_user_settings(db_user.id)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="💰 Trade Amount", callback_data="settings_amount"),
                    InlineKeyboardButton(text="📊 Leverage", callback_data="settings_leverage"),
                ],
                [
                    InlineKeyboardButton(text="📈 Min Spread", callback_data="settings_spread"),
                    InlineKeyboardButton(text="💵 Min Volume", callback_data="settings_volume"),
                ],
                [
                    InlineKeyboardButton(text="🔔 Notifications", callback_data="settings_notify"),
                ],
            ])
            
            text = self.formatter.format_settings(settings)
            text += "\n\n<i>Tap a button to change a setting</i>"
            
            await callback.message.edit_text(text, reply_markup=keyboard)
    
    async def _perform_deposit(self, callback: CallbackQuery) -> None:
        """Perform USDC deposit to HyperLiquid."""
        user_id = callback.from_user.id
        
        await self._ensure_user(user_id, callback.from_user.username)
        db_user = await self.db.get_user(user_id)
        wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
        
        if not wallet:
            await callback.message.edit_text("❌ No wallet found")
            return
        
        private_key = decrypt_private_key(wallet.encrypted_private_key)
        
        await callback.message.edit_text(
            "⏳ <b>Depositing USDC...</b>\n\n"
            "This may take ~1 minute."
        )
        
        success, tx_hash, error = await asyncio.to_thread(
            deposit_usdc_to_hyperliquid, private_key
        )
        
        if success and tx_hash:
            await callback.message.edit_text(
                f"✅ <b>Deposit Successful!</b>\n\n"
                f"TX: <code>{tx_hash[:20]}...</code>\n"
                f"<a href='https://arbiscan.io/tx/{tx_hash}'>View on Arbiscan</a>\n\n"
                f"Funds appear on HyperLiquid in ~1-2 min.",
                disable_web_page_preview=True
            )
        else:
            await callback.message.edit_text(f"❌ Deposit failed: {error}")
    
    async def _perform_deposit_with_api_key(self, callback: CallbackQuery) -> None:
        """Perform deposit and create API key."""
        user_id = callback.from_user.id
        
        await self._ensure_user(user_id, callback.from_user.username)
        db_user = await self.db.get_user(user_id)
        wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
        
        if not wallet:
            await callback.message.edit_text("❌ No wallet found")
            return
        
        private_key = decrypt_private_key(wallet.encrypted_private_key)
        
        await callback.message.edit_text("⏳ <b>Step 1/2:</b> Depositing USDC...")
        
        success, tx_hash, error = await asyncio.to_thread(
            deposit_usdc_to_hyperliquid, private_key
        )
        
        if not success:
            await callback.message.edit_text(f"❌ Deposit failed: {error}")
            return
        
        await callback.message.edit_text(
            f"✅ Deposit sent!\n"
            f"TX: <code>{tx_hash[:20]}...</code>\n\n"
            f"⏳ <b>Step 2/2:</b> Creating API key (~60s)..."
        )
        
        await asyncio.sleep(60)
        
        hl_service = await self._get_hl_service()
        api_success, api_error = await hl_service.create_api_key_for_user(
            user_id=db_user.id,
            validity_days=180,
            is_mainnet=True,
        )
        
        if api_success:
            api_status = await hl_service.get_api_key_status(db_user.id)
            await callback.message.edit_text(
                f"✅ <b>Setup Complete!</b>\n\n"
                f"<b>Deposit:</b>\n"
                f"<a href='https://arbiscan.io/tx/{tx_hash}'>View TX</a>\n\n"
                f"<b>API Key:</b>\n"
                f"Agent: <code>{api_status['agent_address'][:16]}...</code>\n"
                f"Valid: {api_status['days_until_expiry']} days\n\n"
                f"Use /hl for trading!",
                disable_web_page_preview=True
            )
        else:
            await callback.message.edit_text(
                f"✅ Deposit successful!\n"
                f"❌ API key creation failed: {api_error}\n\n"
                f"Try /hl_setup again later."
            )
    
    # ============================================================
    # Run Bot
    # ============================================================
    
    async def run(self) -> None:
        """Start the bot."""
        logger.info("Starting Funding Rate Arbitrage Bot (aiogram)...")
        
        await self.setup()
        
        try:
            await self.dp.start_polling(self.bot, allowed_updates=["message", "callback_query"])
        finally:
            # Cleanup
            config = get_config()
            if config.funding.cache_enabled and hasattr(self, 'funding_cache'):
                from src.services.funding_cache import stop_funding_cache
                await stop_funding_cache()
                logger.info("Funding cache stopped")
            
            # Close exchange sessions
            await ExchangeRegistry.close_all()
            logger.info("Exchange sessions closed")
            
            await self.bot.session.close()

