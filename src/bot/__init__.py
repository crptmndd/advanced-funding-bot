"""Telegram bot for funding rate arbitrage."""

from .aiogram_bot import FundingBot
from .formatters import TelegramFormatter

__all__ = ["FundingBot", "TelegramFormatter"]
