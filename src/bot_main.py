#!/usr/bin/env python3
"""
Telegram Bot for Funding Rate Arbitrage.

Run this script to start the Telegram bot.

Usage:
    python -m src.bot_main
    
    Or with token as argument:
    python -m src.bot_main YOUR_BOT_TOKEN

Environment variables:
    TELEGRAM_BOT_TOKEN - Your bot token from @BotFather
"""

import os
import sys
import asyncio
import argparse
import logging

from dotenv import load_dotenv


def setup_logging():
    """Configure logging to show bot activity but hide noisy libraries."""
    # Set root logger
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO,
    )
    
    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("rlp.codec").setLevel(logging.WARNING)
    
    # Make sure our loggers are visible at INFO level
    logging.getLogger("src.bot").setLevel(logging.INFO)
    logging.getLogger("src.database").setLevel(logging.INFO)
    logging.getLogger("src.exchanges").setLevel(logging.INFO)
    logging.getLogger("src.services").setLevel(logging.INFO)


async def run_bot(token: str):
    """Run the bot asynchronously."""
    from src.bot.aiogram_bot import FundingBot
    
    bot = FundingBot(token)
    await bot.run()


def main():
    """Main entry point for the Telegram bot."""
    # Setup logging first
    setup_logging()
    
    # Load environment variables
    load_dotenv()
    
    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Funding Rate Arbitrage Telegram Bot",
    )
    parser.add_argument(
        "token",
        nargs="?",
        help="Telegram bot token (or set TELEGRAM_BOT_TOKEN env var)",
    )
    args = parser.parse_args()
    
    # Get token from argument or environment
    token = args.token or os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        print("Error: No bot token provided!")
        print()
        print("You can provide the token in two ways:")
        print("  1. As command argument: python -m src.bot_main YOUR_TOKEN")
        print("  2. As environment variable: export TELEGRAM_BOT_TOKEN=YOUR_TOKEN")
        print("  3. In .env file: TELEGRAM_BOT_TOKEN=YOUR_TOKEN")
        print()
        print("Get your bot token from @BotFather on Telegram:")
        print("  1. Open Telegram and search for @BotFather")
        print("  2. Send /newbot command")
        print("  3. Follow the instructions to create a new bot")
        print("  4. Copy the token and use it here")
        sys.exit(1)
    
    print("=" * 60)
    print("🤖 Funding Rate Arbitrage Bot (aiogram)")
    print("=" * 60)
    print()
    print("Starting bot...")
    print("Press Ctrl+C to stop")
    print()
    
    # Run the bot
    try:
        asyncio.run(run_bot(token))
    except KeyboardInterrupt:
        print("\n\nBot stopped.")


if __name__ == "__main__":
    main()
