"""Telegram bot for funding rate arbitrage."""

import asyncio
import logging
from typing import List, Optional

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from src.exchanges.registry import ExchangeRegistry
from src.services.arbitrage_analyzer import ArbitrageAnalyzer, AnalyzerConfig
from src.models import ExchangeFundingRates
from src.database import Database, get_database, WalletType
from .formatters import TelegramFormatter

# Get logger (configured in bot_main.py)
logger = logging.getLogger(__name__)


class FundingBot:
    """Telegram bot for funding rate arbitrage data."""
    
    def __init__(self, token: str):
        """
        Initialize the bot.
        
        Args:
            token: Telegram bot token from BotFather
        """
        self.token = token
        self.formatter = TelegramFormatter()
        self.application: Optional[Application] = None
        self.db: Optional[Database] = None
    
    async def setup(self, application: Application) -> None:
        """Set up bot commands menu and database."""
        # Initialize database
        self.db = await get_database()
        logger.info("Database initialized")
        
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help message"),
            BotCommand("rates", "Get funding rates"),
            BotCommand("arbitrage", "Find arbitrage opportunities"),
            BotCommand("exchanges", "List available exchanges"),
            BotCommand("wallet", "View your wallets"),
            BotCommand("settings", "View/edit your settings"),
            BotCommand("set", "Change a setting"),
        ]
        await application.bot.set_my_commands(commands)
    
    def build(self) -> Application:
        """Build the bot application."""
        self.application = (
            Application.builder()
            .token(self.token)
            .build()
        )
        
        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("rates", self.rates_command))
        self.application.add_handler(CommandHandler("arbitrage", self.arbitrage_command))
        self.application.add_handler(CommandHandler("exchanges", self.exchanges_command))
        self.application.add_handler(CommandHandler("wallet", self.wallet_command))
        self.application.add_handler(CommandHandler("wallets", self.wallet_command))
        self.application.add_handler(CommandHandler("settings", self.settings_command))
        self.application.add_handler(CommandHandler("set", self.set_command))
        
        # Add callback query handler for inline buttons
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Add error handler
        self.application.add_error_handler(self.error_handler)
        
        return self.application
    
    def run(self) -> None:
        """Run the bot (blocking)."""
        app = self.build()
        
        # Set up commands after starting
        app.post_init = self.setup
        
        logger.info("Starting Funding Rate Arbitrage Bot...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    
    async def _ensure_user(self, update: Update) -> None:
        """Ensure user exists in database."""
        if not self.db:
            self.db = await get_database()
        
        user = update.effective_user
        db_user = await self.db.get_or_create_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        logger.info(f"User authenticated: {user.id} (@{user.username or 'no_username'})")
    
    async def start_command(
        self, 
        update: Update, 
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /start command."""
        user = update.effective_user
        logger.info(f"[/start] User {user.id} (@{user.username}) started bot")
        
        # Register/update user
        await self._ensure_user(update)
        
        # Get user info
        db_user = await self.db.get_user(update.effective_user.id)
        wallets = await self.db.get_user_wallets(db_user.id)
        
        logger.info(f"[/start] User {user.id} has {len(wallets)} wallets")
        
        # Build welcome message with wallet info
        welcome = self.formatter.format_start()
        
        # Add wallet creation confirmation for new users
        if wallets:
            welcome += "\n\n" + "─" * 30 + "\n"
            welcome += f"✅ <b>Your wallets are ready!</b>\n"
            welcome += f"Use /wallet to see your addresses.\n"
            welcome += f"Use /settings to configure trading parameters."
            for w in wallets:
                logger.info(f"[/start] Wallet: {w.wallet_type.value} = {w.short_address}")
        else:
            logger.warning(f"[/start] User {user.id} has NO wallets! This should not happen.")
        
        await update.message.reply_text(
            welcome,
            parse_mode=ParseMode.HTML,
        )
    
    async def help_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /help command."""
        await self._ensure_user(update)
        await update.message.reply_text(
            self.formatter.format_help(),
            parse_mode=ParseMode.HTML,
        )
    
    async def exchanges_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /exchanges command."""
        await self._ensure_user(update)
        exchanges = ExchangeRegistry.get_all_names()
        await update.message.reply_text(
            self.formatter.format_exchanges_list(exchanges),
            parse_mode=ParseMode.HTML,
        )
    
    async def wallet_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /wallet command - show user's wallets."""
        user = update.effective_user
        logger.info(f"[/wallet] User {user.id} requested wallets")
        
        await self._ensure_user(update)
        
        db_user = await self.db.get_user(update.effective_user.id)
        wallets = await self.db.get_user_wallets(db_user.id)
        logger.info(f"[/wallet] Found {len(wallets)} wallets for user {user.id}")
        
        if not wallets:
            await update.message.reply_text(
                "❌ No wallets found. This shouldn't happen - please contact support.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        # Format wallet info
        lines = [
            "💳 <b>Your Wallets</b>",
            "",
        ]
        
        for wallet in wallets:
            emoji = "🔷" if wallet.wallet_type == WalletType.EVM else "🟣"
            type_name = "EVM (ETH/BSC/ARB...)" if wallet.wallet_type == WalletType.EVM else "Solana"
            
            lines.append(f"{emoji} <b>{type_name}</b>")
            lines.append(f"   Address: <code>{wallet.address}</code>")
            if wallet.label:
                lines.append(f"   Label: {wallet.label}")
            lines.append("")
        
        lines.append("─" * 30)
        lines.append("")
        lines.append("💡 <i>Deposit funds to these addresses to enable trading.</i>")
        lines.append("⚠️ <i>Only deposit from networks matching wallet type!</i>")
        
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )
    
    async def settings_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /settings command - show user's settings."""
        user = update.effective_user
        logger.info(f"[/settings] User {user.id} requested settings")
        
        await self._ensure_user(update)
        
        db_user = await self.db.get_user(update.effective_user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        if not settings:
            await update.message.reply_text(
                "❌ Settings not found. Please try /start again.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        # Format settings
        lines = [
            "⚙️ <b>Your Settings</b>",
            "",
            "💰 <b>Trading:</b>",
            f"   Trade Amount: <code>${settings.trade_amount_usdt:.2f}</code> USDT",
            f"   Max Trade: <code>${settings.max_trade_amount_usdt:.2f}</code> USDT",
            f"   Max Leverage: <code>{settings.max_leverage}x</code>",
            "",
            "🎯 <b>Filters:</b>",
            f"   Min Spread: <code>{settings.min_funding_spread:.2f}%</code>",
            f"   Max Price Δ: <code>{settings.max_price_spread:.2f}%</code>",
            f"   Min Volume: <code>${settings.min_volume_24h:,.0f}</code>",
            "",
            "🔔 <b>Notifications:</b>",
            f"   Opportunities: {'✅ On' if settings.notify_opportunities else '❌ Off'}",
            f"   Min Spread Alert: <code>{settings.notify_threshold_spread:.2f}%</code>",
            "",
            "🤖 <b>Auto-Trading:</b>",
            f"   Status: {'⚠️ Enabled' if settings.auto_trade_enabled else '❌ Disabled'}",
            "",
            "─" * 30,
            "",
            "📝 <b>Change settings with:</b>",
            "<code>/set amount 500</code> - Set trade amount to $500",
            "<code>/set maxamount 2000</code> - Set max trade to $2000",
            "<code>/set leverage 20</code> - Set max leverage to 20x",
            "<code>/set spread 0.02</code> - Set min spread to 0.02%",
        ]
        
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )
    
    async def set_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /set command - change a setting.
        
        Usage:
            /set amount 500 - Set trade amount to $500
            /set maxamount 2000 - Set max trade to $2000
            /set leverage 20 - Set max leverage
            /set spread 0.05 - Set min funding spread
            /set pricespread 0.5 - Set max price spread
            /set volume 50000 - Set min volume
        """
        user = update.effective_user
        args = context.args or []
        logger.info(f"[/set] User {user.id} args: {args}")
        
        await self._ensure_user(update)
        
        if len(args) < 2:
            await update.message.reply_text(
                "❌ <b>Usage:</b> <code>/set &lt;setting&gt; &lt;value&gt;</code>\n\n"
                "<b>Available settings:</b>\n"
                "• <code>amount</code> - Trade amount (USDT)\n"
                "• <code>maxamount</code> - Max trade amount (USDT)\n"
                "• <code>leverage</code> - Max leverage (1-100)\n"
                "• <code>spread</code> - Min funding spread (%)\n"
                "• <code>pricespread</code> - Max price spread (%)\n"
                "• <code>volume</code> - Min 24h volume (USDT)\n"
                "• <code>notify</code> - Notifications (on/off)\n\n"
                "<b>Examples:</b>\n"
                "<code>/set amount 500</code>\n"
                "<code>/set leverage 20</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        
        setting = args[0].lower()
        value_str = args[1].lower()
        
        db_user = await self.db.get_user(update.effective_user.id)
        
        # Map setting names to database fields
        setting_map = {
            "amount": ("trade_amount_usdt", float, 1, 100000),
            "maxamount": ("max_trade_amount_usdt", float, 1, 1000000),
            "leverage": ("max_leverage", int, 1, 100),
            "spread": ("min_funding_spread", float, 0.001, 10),
            "pricespread": ("max_price_spread", float, 0.01, 50),
            "volume": ("min_volume_24h", float, 0, 100000000),
        }
        
        # Handle boolean settings
        if setting == "notify":
            value = value_str in ("on", "true", "1", "yes")
            await self.db.update_user_settings(db_user.id, notify_opportunities=value)
            status = "✅ enabled" if value else "❌ disabled"
            await update.message.reply_text(
                f"✅ Notifications {status}",
                parse_mode=ParseMode.HTML,
            )
            return
        
        if setting not in setting_map:
            await update.message.reply_text(
                f"❌ Unknown setting: <code>{setting}</code>\n"
                f"Use /set without arguments to see available settings.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        field_name, value_type, min_val, max_val = setting_map[setting]
        
        try:
            value = value_type(value_str)
            
            if value < min_val or value > max_val:
                await update.message.reply_text(
                    f"❌ Value must be between {min_val} and {max_val}",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            # Update setting
            await self.db.update_user_settings(db_user.id, **{field_name: value})
            
            # Confirm
            display_value = f"${value:,.2f}" if "amount" in setting or "volume" in setting.lower() else str(value)
            if "spread" in setting:
                display_value = f"{value}%"
            if setting == "leverage":
                display_value = f"{value}x"
            
            await update.message.reply_text(
                f"✅ <b>{setting}</b> set to <code>{display_value}</code>",
                parse_mode=ParseMode.HTML,
            )
            
        except ValueError:
            await update.message.reply_text(
                f"❌ Invalid value. Expected a {'number' if value_type == float else 'whole number'}.",
                parse_mode=ParseMode.HTML,
            )
    
    async def button_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle inline button callbacks."""
        query = update.callback_query
        await query.answer()
        
        # Handle different callbacks
        data = query.data
        
        if data.startswith("set_"):
            # Setting change via button
            pass  # Future implementation
    
    async def rates_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /rates command.
        
        Usage:
            /rates - All exchanges, top 10
            /rates 20 - All exchanges, top 20
            /rates binance - Single exchange
            /rates binance bybit - Multiple exchanges
            /rates binance 15 - Single exchange, top 15
        """
        user = update.effective_user
        args = context.args or []
        logger.info(f"[/rates] User {user.id} args: {args}")
        
        await self._ensure_user(update)
        
        # Parse arguments
        top_n = 10
        exchange_names: List[str] = []
        
        for arg in args:
            if arg.isdigit():
                top_n = min(int(arg), 30)  # Max 30 to avoid huge messages
            else:
                exchange_names.append(arg.lower())
        
        # Send loading message
        loading_msg = await update.message.reply_text(
            self.formatter.format_loading("Fetching funding rates..."),
            parse_mode=ParseMode.HTML,
        )
        
        try:
            # Determine which exchanges to fetch
            if exchange_names:
                # Validate exchange names
                valid_exchanges = ExchangeRegistry.get_all_names()
                invalid = [e for e in exchange_names if e not in valid_exchanges]
                if invalid:
                    await loading_msg.edit_text(
                        self.formatter.format_error(
                            f"Unknown exchange(s): {', '.join(invalid)}\n"
                            f"Use /exchanges to see available exchanges."
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                    return
                exchanges_to_fetch = exchange_names
            else:
                exchanges_to_fetch = ExchangeRegistry.get_all_names()
            
            # Fetch rates
            results = await self._fetch_rates(exchanges_to_fetch)
            
            # Format response
            if len(results) == 1:
                # Single exchange - detailed view
                response = self.formatter.format_exchange_rates(results[0], top_n)
            else:
                # Multiple exchanges - summary view
                response = self.formatter.format_funding_summary(results, top_n)
            
            # Edit loading message with results
            # Telegram has 4096 char limit, split if needed
            if len(response) > 4000:
                response = response[:3900] + "\n\n<i>... (truncated)</i>"
            
            await loading_msg.edit_text(
                response,
                parse_mode=ParseMode.HTML,
            )
            
        except Exception as e:
            logger.exception("Error in rates command")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def arbitrage_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /arbitrage command.
        
        Usage:
            /arbitrage - Find opportunities, top 10
            /arbitrage 20 - Find opportunities, top 20
        """
        user = update.effective_user
        args = context.args or []
        logger.info(f"[/arbitrage] User {user.id} args: {args}")
        
        await self._ensure_user(update)
        
        # Get user settings for filtering
        db_user = await self.db.get_user(update.effective_user.id)
        settings = await self.db.get_user_settings(db_user.id)
        
        # Parse arguments
        top_n = 10
        for arg in args:
            if arg.isdigit():
                top_n = min(int(arg), 20)  # Max 20 for arbitrage
        
        # Send loading message
        loading_msg = await update.message.reply_text(
            self.formatter.format_loading(
                "Analyzing arbitrage opportunities across all exchanges..."
            ),
            parse_mode=ParseMode.HTML,
        )
        
        try:
            # Fetch all rates
            exchanges = ExchangeRegistry.get_all_names()
            results = await self._fetch_rates(exchanges)
            
            # Check if we got any rates
            total_rates = sum(len(r.rates) for r in results if not r.error)
            
            if total_rates == 0:
                await loading_msg.edit_text(
                    self.formatter.format_error("No funding rates collected."),
                    parse_mode=ParseMode.HTML,
                )
                return
            
            # Use user's settings for filtering
            config = AnalyzerConfig(
                min_funding_spread=settings.min_funding_spread if settings else 0.01,
                max_price_spread=settings.max_price_spread if settings else 1.0,
                min_volume_24h=settings.min_volume_24h if settings else 100000,
            )
            analyzer = ArbitrageAnalyzer(config)
            opportunities = analyzer.analyze(results)
            
            # Format response
            response = self.formatter.format_arbitrage_table(opportunities, top_n)
            
            # Truncate if needed
            if len(response) > 4000:
                response = response[:3900] + "\n\n<i>... (truncated)</i>"
            
            await loading_msg.edit_text(
                response,
                parse_mode=ParseMode.HTML,
            )
            
        except Exception as e:
            logger.exception("Error in arbitrage command")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def _fetch_rates(
        self,
        exchange_names: List[str],
    ) -> List[ExchangeFundingRates]:
        """Fetch funding rates from specified exchanges."""
        async def fetch_single(name: str) -> ExchangeFundingRates:
            exchange = ExchangeRegistry.get_exchange(name)
            if not exchange:
                return ExchangeFundingRates(
                    exchange=name,
                    error=f"Exchange '{name}' not found",
                )
            
            try:
                return await exchange.fetch_funding_rates()
            except Exception as e:
                logger.warning(f"Failed to fetch from {name}: {e}")
                return ExchangeFundingRates(exchange=name, error=str(e))
        
        # Fetch from all exchanges concurrently
        tasks = [fetch_single(name) for name in exchange_names]
        results = await asyncio.gather(*tasks)
        
        return results
    
    async def error_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle errors."""
        logger.error(f"Exception while handling an update: {context.error}")
        
        if update and update.message:
            await update.message.reply_text(
                self.formatter.format_error(
                    "An unexpected error occurred. Please try again."
                ),
                parse_mode=ParseMode.HTML,
            )


def run_bot(token: str) -> None:
    """Run the Telegram bot."""
    bot = FundingBot(token)
    bot.run()
