"""Telegram bot for funding rate arbitrage."""

import asyncio
import logging
from typing import List, Optional

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from src.exchanges.registry import ExchangeRegistry
from src.services.arbitrage_analyzer import ArbitrageAnalyzer, AnalyzerConfig
from src.models import ExchangeFundingRates
from .formatters import TelegramFormatter

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
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
    
    async def setup(self, application: Application) -> None:
        """Set up bot commands menu."""
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help message"),
            BotCommand("rates", "Get funding rates"),
            BotCommand("arbitrage", "Find arbitrage opportunities"),
            BotCommand("exchanges", "List available exchanges"),
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
    
    async def start_command(
        self, 
        update: Update, 
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /start command."""
        await update.message.reply_text(
            self.formatter.format_start(),
            parse_mode=ParseMode.HTML,
        )
    
    async def help_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /help command."""
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
        exchanges = ExchangeRegistry.get_all_names()
        await update.message.reply_text(
            self.formatter.format_exchanges_list(exchanges),
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
        args = context.args or []
        
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
        args = context.args or []
        
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
            
            # Analyze for arbitrage (pass ExchangeFundingRates list)
            config = AnalyzerConfig(
                min_funding_spread=0.01,
                max_price_spread=1.0,
                min_volume_24h=100000,
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

