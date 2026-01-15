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
import argparse

from dotenv import load_dotenv

from src.bot import FundingBot


def main():
    """Main entry point for the Telegram bot."""
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
    print("🤖 Funding Rate Arbitrage Bot")
    print("=" * 60)
    print()
    print("Starting bot...")
    print("Press Ctrl+C to stop")
    print()
    
    # Run the bot
    bot = FundingBot(token)
    bot.run()


if __name__ == "__main__":
    main()

