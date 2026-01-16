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
from src.exchanges.arbitrum_bridge import (
    get_usdc_balance,
    get_eth_balance,
    deposit_usdc_to_hyperliquid,
    MIN_DEPOSIT_USDC,
)
from src.services.arbitrage_analyzer import ArbitrageAnalyzer, AnalyzerConfig
from src.services.hyperliquid_service import HyperliquidService
from src.models import ExchangeFundingRates
from src.database import Database, get_database, WalletType, decrypt_private_key
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
        self.hl_service: Optional[HyperliquidService] = None
    
    async def setup(self, application: Application) -> None:
        """Set up bot commands menu and database."""
        # Initialize database
        self.db = await get_database()
        logger.info("Database initialized")
        
        # Initialize HyperLiquid service
        self.hl_service = HyperliquidService(self.db)
        logger.info("HyperLiquid service initialized")
        
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
            # HyperLiquid commands
            BotCommand("hl", "HyperLiquid account status"),
            BotCommand("hl_setup", "Create HyperLiquid API key"),
            BotCommand("hl_buy", "Place buy order"),
            BotCommand("hl_sell", "Place sell order"),
            BotCommand("hl_close", "Close position"),
            BotCommand("hl_positions", "View positions"),
            BotCommand("hl_orders", "View open orders"),
            BotCommand("hl_cancel", "Cancel an order"),
            BotCommand("hl_create_api", "Create HyperLiquid API key"),
            BotCommand("export_keys", "Export your private keys"),
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
        
        # HyperLiquid trading commands
        self.application.add_handler(CommandHandler("hl", self.hl_status_command))
        self.application.add_handler(CommandHandler("hyperliquid", self.hl_status_command))
        self.application.add_handler(CommandHandler("hl_setup", self.hl_setup_command))
        self.application.add_handler(CommandHandler("hl_buy", self.hl_buy_command))
        self.application.add_handler(CommandHandler("hl_sell", self.hl_sell_command))
        self.application.add_handler(CommandHandler("hl_close", self.hl_close_command))
        self.application.add_handler(CommandHandler("hl_positions", self.hl_positions_command))
        self.application.add_handler(CommandHandler("hl_orders", self.hl_orders_command))
        self.application.add_handler(CommandHandler("hl_cancel", self.hl_cancel_command))
        self.application.add_handler(CommandHandler("hl_leverage", self.hl_leverage_command))
        self.application.add_handler(CommandHandler("hl_create_api", self.hl_create_api_key_command))
        self.application.add_handler(CommandHandler("bridge", self.bridge_command))
        self.application.add_handler(CommandHandler("export_keys", self.export_keys_command))
        
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
            
            # Check HyperLiquid API key status
            hl_service = await self._get_hl_service()
            api_status = await hl_service.get_api_key_status(db_user.id)
            
            if api_status['is_valid']:
                welcome += f"\n\n🟢 <b>HyperLiquid:</b> API key active"
                welcome += f"\n   Use /hl for trading commands"
            else:
                welcome += f"\n\n⏳ <b>HyperLiquid Setup:</b>"
                welcome += f"\n   1. Deposit USDC to your EVM wallet"
                welcome += f"\n   2. Run /hl_setup to activate trading"
            
            logger.info(f"[/start] HyperLiquid API: {api_status['message']}")
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
        user = update.effective_user
        
        if data.startswith("set_"):
            # Setting change via button
            pass  # Future implementation
        
        elif data.startswith("hl_deposit_"):
            # HyperLiquid deposit confirmation
            await self._handle_hl_deposit_callback(update, query, context, data)
        
        elif data.startswith("export_keys_"):
            # Export keys confirmation
            await self._handle_export_keys_callback(update, query, context, data)
        
        elif data.startswith("bridge_deposit_"):
            # Bridge deposit confirmation
            await self._handle_bridge_deposit_callback(update, query, context, data)
    
    async def _handle_hl_deposit_callback(
        self,
        update: Update,
        query,
        context: ContextTypes.DEFAULT_TYPE,
        data: str,
    ) -> None:
        """Handle HyperLiquid deposit callbacks."""
        user_id = query.from_user.id
        logger.info(f"[Callback] HL deposit callback for user {user_id}: {data}")
        
        await self._ensure_user(update)
        
        if data == "hl_deposit_cancel":
            await query.edit_message_text(
                "❌ <b>Deposit Cancelled</b>\n\n"
                "You can deposit later using /hl_setup command.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        if data == "hl_deposit_confirm":
            db_user = await self.db.get_user(user_id)
            wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
            
            if not wallet:
                await query.edit_message_text(
                    "❌ No EVM wallet found. Please try /start first.",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            # Decrypt private key
            private_key = decrypt_private_key(wallet.encrypted_private_key)
            
            # Show processing message
            await query.edit_message_text(
                "⏳ <b>Processing Deposit...</b>\n\n"
                "Sending USDC to HyperLiquid bridge...\n"
                "This may take up to 1 minute.",
                parse_mode=ParseMode.HTML,
            )
            
            # Perform deposit (run in thread to avoid blocking)
            success, tx_hash, error = await asyncio.to_thread(
                deposit_usdc_to_hyperliquid,
                private_key
            )
            
            if success and tx_hash:
                await query.edit_message_text(
                    f"✅ <b>Deposit Sent!</b>\n\n"
                    f"Transaction: <code>{tx_hash[:20]}...</code>\n"
                    f"<a href='https://arbiscan.io/tx/{tx_hash}'>View on Arbiscan</a>\n\n"
                    f"⏳ Waiting for funds to appear on HyperLiquid (~1 minute)...\n"
                    f"Then API key will be created automatically.",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                
                # Wait for deposit to be credited (about 1 minute)
                await asyncio.sleep(60)  # Wait 60 seconds
                
                # Try to create API key
                try:
                    hl_service = await self._get_hl_service()
                    api_success, api_error = await hl_service.create_api_key_for_user(
                        user_id=db_user.id,
                        validity_days=180,
                        is_mainnet=True,
                    )
                    
                    if api_success:
                        api_status = await hl_service.get_api_key_status(db_user.id)
                        await query.edit_message_text(
                            f"✅ <b>Setup Complete!</b>\n\n"
                            f"<b>Deposit:</b>\n"
                            f"<a href='https://arbiscan.io/tx/{tx_hash}'>View on Arbiscan</a>\n\n"
                            f"<b>API Key:</b>\n"
                            f"Agent: <code>{api_status['agent_address']}</code>\n"
                            f"Valid for: {api_status['days_until_expiry']} days\n\n"
                            f"You can now use /hl for trading!",
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )
                    else:
                        await query.edit_message_text(
                            f"✅ <b>Deposit Successful!</b>\n\n"
                            f"<a href='https://arbiscan.io/tx/{tx_hash}'>View on Arbiscan</a>\n\n"
                            f"⚠️ API key creation failed: {api_error}\n\n"
                            f"Please wait a bit and run /hl_create_api to try again.",
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )
                except Exception as e:
                    logger.exception("Error creating API key after deposit")
                    await query.edit_message_text(
                        f"✅ <b>Deposit Successful!</b>\n\n"
                        f"<a href='https://arbiscan.io/tx/{tx_hash}'>View on Arbiscan</a>\n\n"
                        f"⚠️ API key creation error: {str(e)}\n\n"
                        f"Please run /hl_create_api to create your API key.",
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
            else:
                await query.edit_message_text(
                    f"❌ <b>Deposit Failed</b>\n\n"
                    f"Error: {error}\n\n"
                    f"Please try again or deposit manually at https://app.hyperliquid.xyz",
                    parse_mode=ParseMode.HTML,
                )
    
    async def _handle_export_keys_callback(
        self,
        update: Update,
        query,
        context: ContextTypes.DEFAULT_TYPE,
        data: str,
    ) -> None:
        """Handle export keys callbacks."""
        user_id = query.from_user.id
        logger.info(f"[Callback] Export keys callback for user {user_id}: {data}")
        
        await self._ensure_user(update)
        
        if data == "export_keys_cancel":
            await query.edit_message_text(
                "✅ <b>Export Cancelled</b>\n\n"
                "Your private keys remain secure.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        if data == "export_keys_confirm":
            db_user = await self.db.get_user(user_id)
            wallets = await self.db.get_user_wallets(db_user.id)
            
            if not wallets:
                await query.edit_message_text(
                    "❌ No wallets found.",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            lines = [
                "🔐 <b>YOUR PRIVATE KEYS</b>",
                "",
                "⚠️ <b>IMPORTANT SECURITY WARNING:</b>",
                "• Never share these keys with anyone",
                "• Delete this message after saving keys",
                "• Anyone with these keys can steal your funds",
                "",
                "─" * 30,
            ]
            
            for wallet in wallets:
                private_key = decrypt_private_key(wallet.encrypted_private_key)
                emoji = "🔷" if wallet.wallet_type == WalletType.EVM else "🟣"
                type_name = "EVM" if wallet.wallet_type == WalletType.EVM else "Solana"
                
                lines.append("")
                lines.append(f"{emoji} <b>{type_name}</b>")
                lines.append(f"Address: <code>{wallet.address}</code>")
                lines.append(f"Private Key:")
                lines.append(f"<code>{private_key}</code>")
            
            lines.append("")
            lines.append("─" * 30)
            lines.append("⚠️ <i>This message will NOT be auto-deleted.</i>")
            lines.append("<i>Please delete it after saving your keys!</i>")
            
            await query.edit_message_text(
                "\n".join(lines),
                parse_mode=ParseMode.HTML,
            )
    
    async def _handle_bridge_deposit_callback(
        self,
        update: Update,
        query,
        context: ContextTypes.DEFAULT_TYPE,
        data: str,
    ) -> None:
        """Handle bridge deposit callbacks."""
        user_id = query.from_user.id
        logger.info(f"[Callback] Bridge deposit callback for user {user_id}: {data}")
        
        await self._ensure_user(update)
        
        if data == "bridge_deposit_cancel":
            await query.edit_message_text(
                "❌ <b>Deposit Cancelled</b>\n\n"
                "You can deposit later using /bridge command.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        if data == "bridge_deposit_confirm":
            db_user = await self.db.get_user(user_id)
            wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
            
            if not wallet:
                await query.edit_message_text(
                    "❌ No EVM wallet found. Please try /start first.",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            # Decrypt private key
            private_key = decrypt_private_key(wallet.encrypted_private_key)
            
            # Show processing message
            await query.edit_message_text(
                "⏳ <b>Processing Deposit...</b>\n\n"
                "Sending USDC to HyperLiquid bridge...\n"
                "This may take up to 1 minute.",
                parse_mode=ParseMode.HTML,
            )
            
            # Perform deposit (run in thread to avoid blocking)
            success, tx_hash, error = await asyncio.to_thread(
                deposit_usdc_to_hyperliquid,
                private_key
            )
            
            if success and tx_hash:
                await query.edit_message_text(
                    f"✅ <b>Deposit Successful!</b>\n\n"
                    f"Transaction: <code>{tx_hash[:20]}...</code>\n"
                    f"<a href='https://arbiscan.io/tx/{tx_hash}'>View on Arbiscan</a>\n\n"
                    f"⏳ Funds should appear on HyperLiquid in ~1-2 minutes.\n\n"
                    f"Use /hl to check your balance.",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            else:
                await query.edit_message_text(
                    f"❌ <b>Deposit Failed</b>\n\n"
                    f"Error: {error}\n\n"
                    f"Please try again later using /bridge",
                    parse_mode=ParseMode.HTML,
                )
    
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
    
    # ==================== HyperLiquid Commands ====================
    
    async def _get_hl_service(self) -> HyperliquidService:
        """Get HyperLiquid service, initializing if needed."""
        if not self.hl_service:
            if not self.db:
                self.db = await get_database()
            self.hl_service = HyperliquidService(self.db)
        return self.hl_service
    
    async def hl_setup_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /hl_setup command - setup HyperLiquid.
        
        Flow:
        1. Check Arbitrum USDC balance
        2. If balance >= 5 USDC, offer to deposit to HyperLiquid
        3. After deposit, create API key
        """
        user = update.effective_user
        logger.info(f"[/hl_setup] User {user.id} requested HL setup")
        
        await self._ensure_user(update)
        db_user = await self.db.get_user(update.effective_user.id)
        
        # Check if API key already exists and is valid
        hl_service = await self._get_hl_service()
        api_status = await hl_service.get_api_key_status(db_user.id)
        
        if api_status['is_valid']:
            await update.message.reply_text(
                f"✅ <b>API Key Already Active</b>\n\n"
                f"Your HyperLiquid API key is already set up and valid.\n"
                f"Agent: <code>{api_status['agent_address']}</code>\n"
                f"Expires: {api_status['valid_until'][:10]} ({api_status['days_until_expiry']} days)\n\n"
                f"Use /hl to see your account status.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        # Get user's EVM wallet
        wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
        if not wallet:
            await update.message.reply_text(
                "❌ No EVM wallet found. Please try /start first.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        # Send loading message
        loading_msg = await update.message.reply_text(
            f"⏳ <b>Checking Arbitrum Balance...</b>\n\n"
            f"Wallet: <code>{wallet.address}</code>",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            # Check Arbitrum USDC balance (run in thread to avoid blocking)
            usdc_balance, usdc_raw = await asyncio.to_thread(
                get_usdc_balance,
                wallet.address
            )
            eth_balance = await asyncio.to_thread(
                get_eth_balance,
                wallet.address
            )
            
            logger.info(f"[/hl_setup] User {user.id} balance: {usdc_balance:.2f} USDC, {eth_balance:.6f} ETH")
            
            # Build balance message
            lines = [
                f"💰 <b>Arbitrum Balance</b>",
                f"",
                f"Wallet: <code>{wallet.address}</code>",
                f"",
                f"USDC: <b>{usdc_balance:.2f}</b>",
                f"ETH (gas): <b>{eth_balance:.6f}</b>",
            ]
            
            # Check if enough for deposit
            if usdc_balance >= MIN_DEPOSIT_USDC:
                if eth_balance < 0.00001:
                    lines.append("")
                    lines.append("⚠️ <b>Warning:</b> Low ETH balance for gas fees")
                    lines.append("Deposit some ETH for transaction fees")
                    
                    await loading_msg.edit_text(
                        "\n".join(lines),
                        parse_mode=ParseMode.HTML,
                    )
                    return
                
                lines.append("")
                lines.append("─" * 30)
                lines.append("")
                lines.append(f"🚀 You have <b>{usdc_balance:.2f} USDC</b> available!")
                lines.append("")
                lines.append("Would you like to deposit all USDC to HyperLiquid?")
                lines.append(f"<i>Minimum deposit: {MIN_DEPOSIT_USDC} USDC</i>")
                
                # Create inline keyboard for confirmation
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"✅ Deposit {usdc_balance:.2f} USDC",
                            callback_data="hl_deposit_confirm"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Cancel",
                            callback_data="hl_deposit_cancel"
                        ),
                    ]
                ])
                
                await loading_msg.edit_text(
                    "\n".join(lines),
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            else:
                # Not enough USDC
                lines.append("")
                lines.append("─" * 30)
                lines.append("")
                lines.append(f"⚠️ <b>Insufficient USDC</b>")
                lines.append(f"Minimum deposit: {MIN_DEPOSIT_USDC} USDC")
                lines.append("")
                lines.append("<b>To get started:</b>")
                lines.append(f"1. Send USDC to your wallet on Arbitrum:")
                lines.append(f"   <code>{wallet.address}</code>")
                lines.append("2. Also send some ETH for gas fees (~$0.05)")
                lines.append("3. Run /hl_setup again")
                
                await loading_msg.edit_text(
                    "\n".join(lines),
                    parse_mode=ParseMode.HTML,
                )
                
        except Exception as e:
            logger.exception("[/hl_setup] Error checking balance")
            await loading_msg.edit_text(
                f"❌ <b>Error checking balance</b>\n\n{str(e)}",
                parse_mode=ParseMode.HTML,
            )
    
    async def bridge_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /bridge command - check USDC balance and deposit to HyperLiquid.
        
        This command allows users to:
        1. Check their Arbitrum USDC balance
        2. Deposit USDC to HyperLiquid bridge
        """
        user = update.effective_user
        logger.info(f"[/bridge] User {user.id} requested bridge")
        
        await self._ensure_user(update)
        db_user = await self.db.get_user(update.effective_user.id)
        
        # Get user's EVM wallet
        wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
        if not wallet:
            await update.message.reply_text(
                "❌ No EVM wallet found. Please try /start first.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        # Send loading message
        loading_msg = await update.message.reply_text(
            f"⏳ <b>Checking Arbitrum Balance...</b>\n\n"
            f"Wallet: <code>{wallet.address}</code>",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            # Check Arbitrum USDC balance (run in thread to avoid blocking)
            usdc_balance, usdc_raw = await asyncio.to_thread(
                get_usdc_balance,
                wallet.address
            )
            eth_balance = await asyncio.to_thread(
                get_eth_balance,
                wallet.address
            )
            
            logger.info(f"[/bridge] User {user.id} balance: {usdc_balance:.2f} USDC, {eth_balance:.6f} ETH")
            
            # Also check HyperLiquid balance
            hl_balance = None
            try:
                hl_service = await self._get_hl_service()
                client, error = await hl_service.get_trading_client(db_user.id, True)
                if client:
                    account_state = await client.get_account_state()
                    if account_state:
                        hl_balance = account_state.account_value
            except Exception as e:
                logger.warning(f"[/bridge] Could not get HL balance: {e}")
            
            # Build balance message
            lines = [
                f"🌉 <b>Bridge Status</b>",
                f"",
                f"<b>Wallet:</b> <code>{wallet.address}</code>",
                f"",
                f"<b>Arbitrum:</b>",
                f"├ USDC: <b>{usdc_balance:.2f}</b>",
                f"└ ETH (gas): <b>{eth_balance:.6f}</b>",
            ]
            
            if hl_balance is not None:
                lines.append("")
                lines.append(f"<b>HyperLiquid:</b>")
                lines.append(f"└ Account Value: <b>${hl_balance:,.2f}</b>")
            
            # Check if enough for deposit
            if usdc_balance >= MIN_DEPOSIT_USDC:
                if eth_balance < 0.00001:
                    lines.append("")
                    lines.append("⚠️ <b>Warning:</b> Low ETH balance for gas fees")
                    lines.append("Deposit some ETH for transaction fees (~$0.05)")
                    
                    await loading_msg.edit_text(
                        "\n".join(lines),
                        parse_mode=ParseMode.HTML,
                    )
                    return
                
                lines.append("")
                lines.append("─" * 30)
                lines.append("")
                lines.append(f"🚀 You have <b>{usdc_balance:.2f} USDC</b> available!")
                lines.append("")
                lines.append("Would you like to deposit USDC to HyperLiquid?")
                lines.append(f"<i>Minimum deposit: {MIN_DEPOSIT_USDC} USDC</i>")
                
                # Create inline keyboard for confirmation
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"✅ Deposit {usdc_balance:.2f} USDC",
                            callback_data="bridge_deposit_confirm"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Cancel",
                            callback_data="bridge_deposit_cancel"
                        ),
                    ]
                ])
                
                await loading_msg.edit_text(
                    "\n".join(lines),
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            else:
                # Not enough USDC
                lines.append("")
                lines.append("─" * 30)
                lines.append("")
                lines.append(f"⚠️ <b>Insufficient USDC for deposit</b>")
                lines.append(f"Minimum: {MIN_DEPOSIT_USDC} USDC | You have: {usdc_balance:.2f} USDC")
                lines.append("")
                lines.append("<b>To deposit:</b>")
                lines.append(f"1. Send USDC to your wallet on Arbitrum:")
                lines.append(f"   <code>{wallet.address}</code>")
                lines.append("2. Send ETH for gas fees (~$0.05)")
                lines.append("3. Run /bridge again")
                
                await loading_msg.edit_text(
                    "\n".join(lines),
                    parse_mode=ParseMode.HTML,
                )
                
        except Exception as e:
            logger.exception("[/bridge] Error checking balance")
            await loading_msg.edit_text(
                f"❌ <b>Error checking balance</b>\n\n{str(e)}",
                parse_mode=ParseMode.HTML,
            )
    
    async def hl_create_api_key_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle API key creation after deposit is confirmed on HyperLiquid.
        """
        user = update.effective_user
        logger.info(f"[hl_create_api] User {user.id} requested HL API key creation")
        
        await self._ensure_user(update)
        db_user = await self.db.get_user(update.effective_user.id)
        
        # Get user's EVM wallet
        wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
        if not wallet:
            await update.message.reply_text(
                "❌ No EVM wallet found. Please try /start first.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        # Send loading message
        loading_msg = await update.message.reply_text(
            f"⏳ <b>Creating HyperLiquid API Key...</b>\n\n"
            f"This requires funds to be deposited on HyperLiquid first.",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            hl_service = await self._get_hl_service()
            
            # Try to create API key
            success, error = await hl_service.create_api_key_for_user(
                user_id=db_user.id,
                validity_days=180,
                is_mainnet=True,
            )
            
            if success:
                # Get new API key status
                api_status = await hl_service.get_api_key_status(db_user.id)
                
                await loading_msg.edit_text(
                    f"✅ <b>HyperLiquid API Key Created!</b>\n\n"
                    f"Agent: <code>{api_status['agent_address']}</code>\n"
                    f"Valid for: {api_status['days_until_expiry']} days\n\n"
                    f"You can now use trading commands:\n"
                    f"• /hl - Account status\n"
                    f"• /hl_buy BTC 0.001 - Buy order\n"
                    f"• /hl_sell ETH 0.1 - Sell order",
                    parse_mode=ParseMode.HTML,
                )
            else:
                # Check if it's a deposit error
                if error and "deposit" in error.lower():
                    await loading_msg.edit_text(
                        f"❌ <b>Deposit Not Yet Confirmed on HyperLiquid</b>\n\n"
                        f"Your USDC deposit may still be processing.\n"
                        f"HyperLiquid deposits usually take about 1 minute.\n\n"
                        f"Please wait and try again in a few minutes.\n\n"
                        f"<i>Error: {error}</i>",
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await loading_msg.edit_text(
                        f"❌ <b>API Key Creation Failed</b>\n\n"
                        f"Error: {error}\n\n"
                        f"Please try again or contact support.",
                        parse_mode=ParseMode.HTML,
                    )
                    
        except Exception as e:
            logger.exception("[hl_create_api] Error")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def export_keys_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /export_keys command - show user's private keys.
        
        ⚠️ SECURITY: This shows sensitive data. User must confirm.
        """
        user = update.effective_user
        logger.info(f"[/export_keys] User {user.id} requested keys export")
        
        await self._ensure_user(update)
        
        # Show warning and ask for confirmation
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⚠️ Yes, show my private keys",
                    callback_data="export_keys_confirm"
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="export_keys_cancel"
                ),
            ]
        ])
        
        await update.message.reply_text(
            "🔐 <b>Export Private Keys</b>\n\n"
            "⚠️ <b>WARNING:</b> You are about to view your private keys.\n\n"
            "<b>Security risks:</b>\n"
            "• Anyone with these keys can steal your funds\n"
            "• Never share your private keys with anyone\n"
            "• Make sure no one is watching your screen\n"
            "• Delete the message after saving your keys\n\n"
            "Are you sure you want to continue?",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    
    async def hl_status_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /hl command - show HyperLiquid status and account info.
        """
        user = update.effective_user
        logger.info(f"[/hl] User {user.id} requested HL status")
        
        await self._ensure_user(update)
        db_user = await self.db.get_user(update.effective_user.id)
        
        # Send loading message
        loading_msg = await update.message.reply_text(
            "⏳ Loading HyperLiquid status...",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            hl_service = await self._get_hl_service()
            
            # Get API key status
            api_status = await hl_service.get_api_key_status(db_user.id)
            
            lines = [
                "🟢 <b>HyperLiquid Status</b>",
                "",
            ]
            
            if api_status['is_valid']:
                lines.append(f"🔑 <b>API Key:</b> ✅ Active")
                lines.append(f"   Agent: <code>{api_status['agent_address']}</code>")
                lines.append(f"   Expires: {api_status['valid_until'][:10]} ({api_status['days_until_expiry']} days)")
            else:
                # Get wallet for deposit instructions
                wallet = await self.db.get_user_wallet(db_user.id, WalletType.EVM)
                wallet_addr = wallet.address if wallet else "N/A"
                
                lines.append(f"🔑 <b>API Key:</b> ❌ Not Set Up")
                lines.append("")
                lines.append("<b>To enable trading:</b>")
                lines.append(f"1. Deposit USDC to HyperLiquid:")
                lines.append(f"   <code>{wallet_addr}</code>")
                lines.append(f"2. Run /hl_setup to create API key")
                lines.append("")
                lines.append("🔗 https://app.hyperliquid.xyz")
            
            # Get account state if API key is valid
            if api_status['is_valid']:
                account_state, error = await hl_service.get_account_state(db_user.id)
                
                if account_state:
                    lines.append("")
                    lines.append("💰 <b>Account:</b>")
                    lines.append(f"   Value: <code>${account_state.account_value:,.2f}</code>")
                    lines.append(f"   Available: <code>${account_state.available_balance:,.2f}</code>")
                    lines.append(f"   Margin Used: <code>${account_state.margin_used:,.2f}</code>")
                    
                    if account_state.positions:
                        lines.append("")
                        lines.append(f"📊 <b>Positions ({len(account_state.positions)}):</b>")
                        for pos in account_state.positions[:5]:  # Show max 5
                            side_emoji = "🟢" if pos.size > 0 else "🔴"
                            side = "LONG" if pos.size > 0 else "SHORT"
                            pnl_sign = "+" if pos.unrealized_pnl >= 0 else ""
                            lines.append(
                                f"   {side_emoji} <b>{pos.symbol}</b> {side} "
                                f"{abs(pos.size):.4f} @ ${pos.entry_price:,.2f} "
                                f"({pnl_sign}${pos.unrealized_pnl:,.2f})"
                            )
                        if len(account_state.positions) > 5:
                            lines.append(f"   ... and {len(account_state.positions) - 5} more")
                    else:
                        lines.append("")
                        lines.append("📊 No open positions")
                else:
                    lines.append("")
                    lines.append(f"⚠️ Could not fetch account: {error}")
            
            lines.append("")
            lines.append("─" * 30)
            lines.append("")
            lines.append("📝 <b>Commands:</b>")
            lines.append("<code>/hl_buy BTC 0.001 50000</code> - Limit buy")
            lines.append("<code>/hl_sell ETH 0.1</code> - Market sell")
            lines.append("<code>/hl_positions</code> - View positions")
            lines.append("<code>/hl_close BTC</code> - Close position")
            
            await loading_msg.edit_text(
                "\n".join(lines),
                parse_mode=ParseMode.HTML,
            )
            
        except Exception as e:
            logger.exception("[/hl] Error")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def hl_buy_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /hl_buy command - place buy order.
        
        Usage:
            /hl_buy BTC 100 - Market buy $100 worth of BTC
            /hl_buy ETH 50 3500 - Limit buy $50 worth of ETH at $3500
        """
        user = update.effective_user
        args = context.args or []
        logger.info(f"[/hl_buy] User {user.id} args: {args}")
        
        await self._ensure_user(update)
        
        if len(args) < 2:
            await update.message.reply_text(
                "❌ <b>Usage:</b>\n"
                "<code>/hl_buy &lt;symbol&gt; &lt;amount_usdt&gt; [price]</code>\n\n"
                "<b>Examples:</b>\n"
                "<code>/hl_buy BTC 100</code> - Market buy $100 of BTC\n"
                "<code>/hl_buy ETH 50 3500</code> - Limit buy $50 of ETH at $3,500",
                parse_mode=ParseMode.HTML,
            )
            return
        
        symbol = args[0].upper()
        try:
            amount_usdt = float(args[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount. Please enter a number in USDT.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        if amount_usdt < 1:
            await update.message.reply_text(
                "❌ Minimum order amount is $1 USDT.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        price = None
        is_market = True
        if len(args) >= 3:
            try:
                price = float(args[2])
                is_market = False
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid price. Please enter a number.",
                    parse_mode=ParseMode.HTML,
                )
                return
        
        # Send loading message
        order_type = "Market" if is_market else "Limit"
        loading_msg = await update.message.reply_text(
            f"⏳ Placing {order_type} BUY order for ${amount_usdt:,.2f} of {symbol}...",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            db_user = await self.db.get_user(update.effective_user.id)
            hl_service = await self._get_hl_service()
            
            # Calculate size from USDT amount
            result, error = await hl_service.place_order_by_usdt(
                user_id=db_user.id,
                symbol=symbol,
                side="buy",
                amount_usdt=amount_usdt,
                price=price,
                is_market=is_market,
            )
            
            if result and result.success:
                status_emoji = "✅"
                status_text = result.status or "submitted"
                price_text = f"@ ${result.average_price:,.2f}" if result.average_price else (f"@ ${price:,.2f}" if price else "market")
                size = result.filled_size if result.filled_size else amount_usdt / (result.average_price or price or 1)
                
                await loading_msg.edit_text(
                    f"{status_emoji} <b>BUY Order {status_text.upper()}</b>\n\n"
                    f"Symbol: <code>{symbol}</code>\n"
                    f"Amount: <code>${amount_usdt:,.2f}</code>\n"
                    f"Size: <code>{size:.6f}</code>\n"
                    f"Price: <code>{price_text}</code>\n"
                    f"Order ID: <code>{result.order_id or 'N/A'}</code>",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await loading_msg.edit_text(
                    f"❌ <b>Order Failed</b>\n\n"
                    f"Error: {error or result.error if result else 'Unknown error'}",
                    parse_mode=ParseMode.HTML,
                )
                
        except Exception as e:
            logger.exception("[/hl_buy] Error")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def hl_sell_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /hl_sell command - place sell order.
        
        Usage:
            /hl_sell BTC 100 - Market sell $100 worth of BTC
            /hl_sell ETH 50 3500 - Limit sell $50 worth of ETH at $3500
        """
        user = update.effective_user
        args = context.args or []
        logger.info(f"[/hl_sell] User {user.id} args: {args}")
        
        await self._ensure_user(update)
        
        if len(args) < 2:
            await update.message.reply_text(
                "❌ <b>Usage:</b>\n"
                "<code>/hl_sell &lt;symbol&gt; &lt;amount_usdt&gt; [price]</code>\n\n"
                "<b>Examples:</b>\n"
                "<code>/hl_sell BTC 100</code> - Market sell $100 of BTC\n"
                "<code>/hl_sell ETH 50 3500</code> - Limit sell $50 of ETH at $3,500",
                parse_mode=ParseMode.HTML,
            )
            return
        
        symbol = args[0].upper()
        try:
            amount_usdt = float(args[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount. Please enter a number in USDT.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        if amount_usdt < 1:
            await update.message.reply_text(
                "❌ Minimum order amount is $1 USDT.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        price = None
        is_market = True
        if len(args) >= 3:
            try:
                price = float(args[2])
                is_market = False
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid price. Please enter a number.",
                    parse_mode=ParseMode.HTML,
                )
                return
        
        # Send loading message
        order_type = "Market" if is_market else "Limit"
        loading_msg = await update.message.reply_text(
            f"⏳ Placing {order_type} SELL order for ${amount_usdt:,.2f} of {symbol}...",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            db_user = await self.db.get_user(update.effective_user.id)
            hl_service = await self._get_hl_service()
            
            # Calculate size from USDT amount
            result, error = await hl_service.place_order_by_usdt(
                user_id=db_user.id,
                symbol=symbol,
                side="sell",
                amount_usdt=amount_usdt,
                price=price,
                is_market=is_market,
            )
            
            if result and result.success:
                status_emoji = "✅"
                status_text = result.status or "submitted"
                price_text = f"@ ${result.average_price:,.2f}" if result.average_price else (f"@ ${price:,.2f}" if price else "market")
                size = result.filled_size if result.filled_size else amount_usdt / (result.average_price or price or 1)
                
                await loading_msg.edit_text(
                    f"{status_emoji} <b>SELL Order {status_text.upper()}</b>\n\n"
                    f"Symbol: <code>{symbol}</code>\n"
                    f"Amount: <code>${amount_usdt:,.2f}</code>\n"
                    f"Size: <code>{size:.6f}</code>\n"
                    f"Price: <code>{price_text}</code>\n"
                    f"Order ID: <code>{result.order_id or 'N/A'}</code>",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await loading_msg.edit_text(
                    f"❌ <b>Order Failed</b>\n\n"
                    f"Error: {error or result.error if result else 'Unknown error'}",
                    parse_mode=ParseMode.HTML,
                )
                
        except Exception as e:
            logger.exception("[/hl_sell] Error")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def hl_close_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /hl_close command - close a position.
        
        Usage:
            /hl_close BTC - Close entire BTC position
        """
        user = update.effective_user
        args = context.args or []
        logger.info(f"[/hl_close] User {user.id} args: {args}")
        
        await self._ensure_user(update)
        
        if len(args) < 1:
            await update.message.reply_text(
                "❌ <b>Usage:</b>\n"
                "<code>/hl_close &lt;symbol&gt;</code>\n\n"
                "<b>Example:</b>\n"
                "<code>/hl_close BTC</code> - Close BTC position",
                parse_mode=ParseMode.HTML,
            )
            return
        
        symbol = args[0].upper()
        
        # Send loading message
        loading_msg = await update.message.reply_text(
            f"⏳ Closing {symbol} position...",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            db_user = await self.db.get_user(update.effective_user.id)
            hl_service = await self._get_hl_service()
            
            result, error = await hl_service.close_position(
                user_id=db_user.id,
                symbol=symbol,
            )
            
            if result and result.success:
                await loading_msg.edit_text(
                    f"✅ <b>Position Closed</b>\n\n"
                    f"Symbol: <code>{symbol}</code>\n"
                    f"Filled: <code>{result.filled_size}</code>\n"
                    f"Avg Price: <code>${result.average_price:,.2f}</code>" if result.average_price else "",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await loading_msg.edit_text(
                    f"❌ <b>Close Failed</b>\n\n"
                    f"Error: {error or result.error if result else 'Unknown error'}",
                    parse_mode=ParseMode.HTML,
                )
                
        except Exception as e:
            logger.exception("[/hl_close] Error")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def hl_positions_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /hl_positions command - view all positions."""
        user = update.effective_user
        logger.info(f"[/hl_positions] User {user.id}")
        
        await self._ensure_user(update)
        
        loading_msg = await update.message.reply_text(
            "⏳ Loading positions...",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            db_user = await self.db.get_user(update.effective_user.id)
            hl_service = await self._get_hl_service()
            
            account_state, error = await hl_service.get_account_state(db_user.id)
            
            if not account_state:
                await loading_msg.edit_text(
                    f"❌ Could not fetch positions: {error}",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            if not account_state.positions:
                await loading_msg.edit_text(
                    "📊 <b>No open positions</b>\n\n"
                    f"Account Value: <code>${account_state.account_value:,.2f}</code>\n"
                    f"Available: <code>${account_state.available_balance:,.2f}</code>",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            lines = [
                f"📊 <b>Open Positions ({len(account_state.positions)})</b>",
                "",
                f"💰 Account: <code>${account_state.account_value:,.2f}</code>",
                f"📈 Available: <code>${account_state.available_balance:,.2f}</code>",
                "",
            ]
            
            total_pnl = 0
            for pos in account_state.positions:
                side_emoji = "🟢" if pos.size > 0 else "🔴"
                side = "LONG" if pos.size > 0 else "SHORT"
                pnl_sign = "+" if pos.unrealized_pnl >= 0 else ""
                total_pnl += pos.unrealized_pnl
                
                lines.append(f"{side_emoji} <b>{pos.symbol}</b> {side}")
                lines.append(f"   Size: <code>{abs(pos.size):.6f}</code>")
                lines.append(f"   Entry: <code>${pos.entry_price:,.2f}</code>")
                lines.append(f"   Mark: <code>${pos.mark_price:,.2f}</code>")
                lines.append(f"   PnL: <code>{pnl_sign}${pos.unrealized_pnl:,.2f}</code>")
                if pos.liquidation_price:
                    lines.append(f"   Liq: <code>${pos.liquidation_price:,.2f}</code>")
                lines.append("")
            
            pnl_sign = "+" if total_pnl >= 0 else ""
            lines.append(f"💵 <b>Total PnL: <code>{pnl_sign}${total_pnl:,.2f}</code></b>")
            
            await loading_msg.edit_text(
                "\n".join(lines),
                parse_mode=ParseMode.HTML,
            )
            
        except Exception as e:
            logger.exception("[/hl_positions] Error")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def hl_orders_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /hl_orders command - view open orders."""
        user = update.effective_user
        logger.info(f"[/hl_orders] User {user.id}")
        
        await self._ensure_user(update)
        
        loading_msg = await update.message.reply_text(
            "⏳ Loading orders...",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            db_user = await self.db.get_user(update.effective_user.id)
            hl_service = await self._get_hl_service()
            
            client, error = await hl_service.get_trading_client(db_user.id)
            if not client:
                await loading_msg.edit_text(
                    f"❌ Could not connect: {error}",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            orders = await client.get_open_orders()
            
            if not orders:
                await loading_msg.edit_text(
                    "📋 <b>No open orders</b>",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            lines = [
                f"📋 <b>Open Orders ({len(orders)})</b>",
                "",
            ]
            
            for order in orders[:15]:  # Show max 15
                side = order.get("side", "?")
                side_emoji = "🟢" if side.lower() == "b" else "🔴"
                side_text = "BUY" if side.lower() == "b" else "SELL"
                
                lines.append(
                    f"{side_emoji} <b>{order.get('coin', '?')}</b> {side_text} "
                    f"{order.get('sz', '?')} @ ${float(order.get('limitPx', 0)):,.2f}"
                )
                lines.append(f"   ID: <code>{order.get('oid', '?')}</code>")
                lines.append("")
            
            if len(orders) > 15:
                lines.append(f"... and {len(orders) - 15} more orders")
            
            lines.append("")
            lines.append("Cancel: <code>/hl_cancel SYMBOL ORDER_ID</code>")
            
            await loading_msg.edit_text(
                "\n".join(lines),
                parse_mode=ParseMode.HTML,
            )
            
        except Exception as e:
            logger.exception("[/hl_orders] Error")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def hl_cancel_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /hl_cancel command - cancel an order.
        
        Usage:
            /hl_cancel BTC 12345 - Cancel order 12345 for BTC
            /hl_cancel all - Cancel all orders
        """
        user = update.effective_user
        args = context.args or []
        logger.info(f"[/hl_cancel] User {user.id} args: {args}")
        
        await self._ensure_user(update)
        
        if len(args) < 1:
            await update.message.reply_text(
                "❌ <b>Usage:</b>\n"
                "<code>/hl_cancel &lt;symbol&gt; &lt;order_id&gt;</code>\n"
                "<code>/hl_cancel all</code> - Cancel all orders\n\n"
                "<b>Example:</b>\n"
                "<code>/hl_cancel BTC 12345</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        
        db_user = await self.db.get_user(update.effective_user.id)
        hl_service = await self._get_hl_service()
        
        # Cancel all orders
        if args[0].lower() == "all":
            loading_msg = await update.message.reply_text(
                "⏳ Cancelling all orders...",
                parse_mode=ParseMode.HTML,
            )
            
            try:
                count, error = await hl_service.cancel_all_orders(db_user.id)
                
                if error:
                    await loading_msg.edit_text(
                        f"❌ Error: {error}",
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await loading_msg.edit_text(
                        f"✅ Cancelled {count} orders",
                        parse_mode=ParseMode.HTML,
                    )
            except Exception as e:
                logger.exception("[/hl_cancel all] Error")
                await loading_msg.edit_text(
                    self.formatter.format_error(str(e)),
                    parse_mode=ParseMode.HTML,
                )
            return
        
        # Cancel specific order
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Please provide both symbol and order ID.\n"
                "Example: <code>/hl_cancel BTC 12345</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        
        symbol = args[0].upper()
        try:
            order_id = int(args[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid order ID. Please enter a number.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        loading_msg = await update.message.reply_text(
            f"⏳ Cancelling order {order_id}...",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            result, error = await hl_service.cancel_order(
                user_id=db_user.id,
                symbol=symbol,
                order_id=order_id,
            )
            
            if result and result.success:
                await loading_msg.edit_text(
                    f"✅ Order {order_id} cancelled",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await loading_msg.edit_text(
                    f"❌ Cancel failed: {error or result.error if result else 'Unknown error'}",
                    parse_mode=ParseMode.HTML,
                )
                
        except Exception as e:
            logger.exception("[/hl_cancel] Error")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
    async def hl_leverage_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Handle /hl_leverage command - set leverage for a symbol.
        
        Usage:
            /hl_leverage BTC 10 - Set BTC leverage to 10x
        """
        user = update.effective_user
        args = context.args or []
        logger.info(f"[/hl_leverage] User {user.id} args: {args}")
        
        await self._ensure_user(update)
        
        if len(args) < 2:
            await update.message.reply_text(
                "❌ <b>Usage:</b>\n"
                "<code>/hl_leverage &lt;symbol&gt; &lt;leverage&gt;</code>\n\n"
                "<b>Example:</b>\n"
                "<code>/hl_leverage BTC 10</code> - Set BTC to 10x",
                parse_mode=ParseMode.HTML,
            )
            return
        
        symbol = args[0].upper()
        try:
            leverage = int(args[1])
            if leverage < 1 or leverage > 100:
                raise ValueError("Leverage must be 1-100")
        except ValueError as e:
            await update.message.reply_text(
                f"❌ Invalid leverage: {e}",
                parse_mode=ParseMode.HTML,
            )
            return
        
        loading_msg = await update.message.reply_text(
            f"⏳ Setting {symbol} leverage to {leverage}x...",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            db_user = await self.db.get_user(update.effective_user.id)
            hl_service = await self._get_hl_service()
            
            success, error = await hl_service.set_leverage(
                user_id=db_user.id,
                symbol=symbol,
                leverage=leverage,
            )
            
            if success:
                await loading_msg.edit_text(
                    f"✅ {symbol} leverage set to <code>{leverage}x</code>",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await loading_msg.edit_text(
                    f"❌ Failed: {error}",
                    parse_mode=ParseMode.HTML,
                )
                
        except Exception as e:
            logger.exception("[/hl_leverage] Error")
            await loading_msg.edit_text(
                self.formatter.format_error(str(e)),
                parse_mode=ParseMode.HTML,
            )
    
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
