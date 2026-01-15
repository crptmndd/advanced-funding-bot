#!/usr/bin/env python3
"""
Quick start script for the Telegram bot.

Usage:
    python run_bot.py YOUR_BOT_TOKEN
    
Or set environment variable:
    export TELEGRAM_BOT_TOKEN=YOUR_TOKEN
    python run_bot.py
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.bot_main import main

if __name__ == "__main__":
    main()

