"""Formatters for Telegram bot messages."""

from typing import List, Optional
from datetime import datetime

from src.models import FundingRateData, ExchangeFundingRates, ArbitrageOpportunity


class TelegramFormatter:
    """Format funding rate data for Telegram messages."""
    
    # Emoji constants
    EMOJI_UP = "🔺"
    EMOJI_DOWN = "🔻"
    EMOJI_MONEY = "💰"
    EMOJI_CHART = "📊"
    EMOJI_EXCHANGE = "🏦"
    EMOJI_TIME = "⏰"
    EMOJI_TARGET = "🎯"
    EMOJI_WARNING = "⚠️"
    EMOJI_CHECK = "✅"
    EMOJI_CROSS = "❌"
    EMOJI_FIRE = "🔥"
    EMOJI_STAR = "⭐"
    
    @staticmethod
    def format_price(price: Optional[float]) -> str:
        """Format price with appropriate precision."""
        if price is None:
            return "N/A"
        
        if price >= 10000:
            return f"${price:,.0f}"
        elif price >= 100:
            return f"${price:,.2f}"
        elif price >= 1:
            return f"${price:.4f}"
        elif price >= 0.01:
            return f"${price:.5f}"
        elif price >= 0.0001:
            return f"${price:.6f}"
        else:
            return f"${price:.8f}"
    
    @staticmethod
    def format_volume(volume: Optional[float]) -> str:
        """Format volume in human-readable format."""
        if volume is None:
            return "N/A"
        
        if volume >= 1_000_000_000:
            return f"${volume / 1_000_000_000:.1f}B"
        elif volume >= 1_000_000:
            return f"${volume / 1_000_000:.1f}M"
        elif volume >= 1_000:
            return f"${volume / 1_000:.0f}K"
        else:
            return f"${volume:.0f}"
    
    @staticmethod
    def format_time_until(target: Optional[datetime]) -> str:
        """Format time until next funding."""
        if target is None:
            return "N/A"
        
        now = datetime.utcnow()
        delta = target - now
        
        if delta.total_seconds() < 0:
            return "Now"
        
        hours = int(delta.total_seconds() // 3600)
        minutes = int((delta.total_seconds() % 3600) // 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    @classmethod
    def format_funding_rate(cls, rate: FundingRateData) -> str:
        """Format single funding rate entry."""
        emoji = cls.EMOJI_UP if rate.funding_rate > 0 else cls.EMOJI_DOWN
        sign = "+" if rate.funding_rate >= 0 else ""
        
        lines = [
            f"{emoji} <b>{rate.symbol}</b> @ {rate.exchange}",
            f"   Rate: <code>{sign}{rate.funding_rate_percent:.4f}%</code>",
            f"   Annual: <code>{sign}{rate.annualized_rate:.1f}%</code>",
            f"   Next: {cls.format_time_until(rate.next_funding_time)}",
        ]
        
        if rate.mark_price:
            lines.append(f"   Price: {cls.format_price(rate.mark_price)}")
        
        if rate.volume_24h:
            lines.append(f"   Volume: {cls.format_volume(rate.volume_24h)}")
        
        if rate.max_order_value:
            lines.append(f"   Max Order: {cls.format_volume(rate.max_order_value)}")
        
        return "\n".join(lines)
    
    @classmethod
    def format_funding_rates_table(
        cls,
        rates: List[FundingRateData],
        title: str,
        is_positive: bool = True,
    ) -> str:
        """Format funding rates as a compact table."""
        if not rates:
            return ""
        
        emoji = cls.EMOJI_UP if is_positive else cls.EMOJI_DOWN
        header_emoji = "🔴" if is_positive else "🟢"
        
        lines = [f"{emoji} <b>{title}</b>\n"]
        
        # Table header with Max Order
        lines.append("<pre>")
        lines.append(f"{'Symbol':<10} {'Rate':>8} {'Annual':>7} {'Price':>9} {'Vol':>6} {'Max':>6}")
        lines.append("-" * 50)
        
        for rate in rates:
            symbol = rate.symbol.split("/")[0][:9]
            rate_str = f"{rate.funding_rate_percent:+.4f}%"
            annual_str = f"{rate.annualized_rate:+.0f}%"
            price_str = cls.format_price(rate.mark_price).replace("$", "")[:9]
            volume_str = cls.format_volume(rate.volume_24h).replace("$", "")[:6]
            max_order_str = cls.format_volume(rate.max_order_value).replace("$", "")[:6] if rate.max_order_value else "N/A"
            
            lines.append(f"{symbol:<10} {rate_str:>8} {annual_str:>7} {price_str:>9} {volume_str:>6} {max_order_str:>6}")
        
        lines.append("</pre>")
        
        return "\n".join(lines)
    
    @classmethod
    def format_funding_summary(
        cls,
        exchange_results: List[ExchangeFundingRates],
        top_n: int = 10,
    ) -> str:
        """Format complete funding rates summary."""
        all_rates: List[FundingRateData] = []
        total_count = 0
        exchanges_ok = 0
        exchanges_error = 0
        
        for result in exchange_results:
            if result.error:
                exchanges_error += 1
            else:
                exchanges_ok += 1
                all_rates.extend(result.rates)
                total_count += len(result.rates)
        
        if not all_rates:
            return f"{cls.EMOJI_WARNING} No funding rates collected."
        
        # Sort for top positive and negative
        positive = sorted(
            [r for r in all_rates if r.funding_rate > 0],
            key=lambda x: x.funding_rate,
            reverse=True,
        )[:top_n]
        
        negative = sorted(
            [r for r in all_rates if r.funding_rate < 0],
            key=lambda x: x.funding_rate,
        )[:top_n]
        
        lines = [
            f"{cls.EMOJI_CHART} <b>Funding Rates Summary</b>",
            f"",
            f"📈 Total: <code>{total_count}</code> rates from <code>{exchanges_ok}</code> exchanges",
        ]
        
        if exchanges_error > 0:
            lines.append(f"{cls.EMOJI_WARNING} Errors: {exchanges_error} exchanges")
        
        lines.append("")
        
        # Add positive rates table
        if positive:
            lines.append(cls.format_funding_rates_table(
                positive, 
                f"Top {len(positive)} Positive (Long pays Short)",
                is_positive=True,
            ))
        
        lines.append("")
        
        # Add negative rates table
        if negative:
            lines.append(cls.format_funding_rates_table(
                negative,
                f"Top {len(negative)} Negative (Short pays Long)",
                is_positive=False,
            ))
        
        return "\n".join(lines)
    
    @classmethod
    def format_exchange_rates(
        cls,
        result: ExchangeFundingRates,
        top_n: int = 10,
    ) -> str:
        """Format rates for a single exchange."""
        if result.error:
            return f"{cls.EMOJI_CROSS} <b>{result.exchange}</b>: Error - {result.error}"
        
        if not result.rates:
            return f"{cls.EMOJI_WARNING} <b>{result.exchange}</b>: No rates found"
        
        rates = result.rates
        
        # Sort for top positive and negative
        positive = sorted(
            [r for r in rates if r.funding_rate > 0],
            key=lambda x: x.funding_rate,
            reverse=True,
        )[:top_n]
        
        negative = sorted(
            [r for r in rates if r.funding_rate < 0],
            key=lambda x: x.funding_rate,
        )[:top_n]
        
        lines = [
            f"{cls.EMOJI_EXCHANGE} <b>{result.exchange.upper()}</b>",
            f"📊 Total markets: <code>{len(rates)}</code>",
            "",
        ]
        
        if positive:
            lines.append(cls.format_funding_rates_table(
                positive,
                f"Top {len(positive)} Positive",
                is_positive=True,
            ))
            lines.append("")
        
        if negative:
            lines.append(cls.format_funding_rates_table(
                negative,
                f"Top {len(negative)} Negative",
                is_positive=False,
            ))
        
        return "\n".join(lines)
    
    @classmethod
    def format_arbitrage_opportunity(cls, opp: ArbitrageOpportunity) -> str:
        """Format single arbitrage opportunity."""
        symbol = opp.symbol.split("/")[0] if "/" in opp.symbol else opp.symbol
        
        # Determine quality emoji based on funding spread
        if opp.funding_spread >= 0.1:
            quality_emoji = cls.EMOJI_FIRE
        elif opp.funding_spread >= 0.05:
            quality_emoji = cls.EMOJI_STAR
        else:
            quality_emoji = cls.EMOJI_TARGET
        
        lines = [
            f"{quality_emoji} <b>{symbol}</b>",
            f"   Long: {opp.long_exchange} @ <code>{opp.long_funding_rate:+.4f}%</code>",
            f"   Short: {opp.short_exchange} @ <code>{opp.short_funding_rate:+.4f}%</code>",
            f"   Spread: <code>{opp.funding_spread:.4f}%</code> ({opp.annualized_spread:.1f}% annual)",
        ]
        
        if opp.price_spread_percent is not None:
            lines.append(f"   Price Δ: <code>{opp.price_spread_percent:.3f}%</code>")
        
        if opp.max_position_size:
            lines.append(f"   Max Size: {cls.format_volume(opp.max_position_size)}")
        
        return "\n".join(lines)
    
    @classmethod
    def format_arbitrage_table(
        cls,
        opportunities: List[ArbitrageOpportunity],
        top_n: int = 10,
    ) -> str:
        """Format arbitrage opportunities as a table."""
        if not opportunities:
            return f"{cls.EMOJI_WARNING} No arbitrage opportunities found."
        
        top_opps = opportunities[:top_n]
        
        lines = [
            f"{cls.EMOJI_MONEY} <b>Arbitrage Opportunities</b>",
            f"Found: <code>{len(opportunities)}</code> opportunities",
            "",
            "<pre>",
            f"{'Symbol':<8} {'Long':<10} {'Short':<10} {'Spread':>8} {'Annual':>8}",
            "-" * 48,
        ]
        
        for opp in top_opps:
            symbol = opp.symbol.split("/")[0][:8]
            spread_str = f"{opp.funding_spread:.4f}%"
            annual_str = f"{opp.annualized_spread:.0f}%"
            
            lines.append(
                f"{symbol:<8} {opp.long_exchange:<10} {opp.short_exchange:<10} {spread_str:>8} {annual_str:>8}"
            )
        
        lines.append("</pre>")
        
        # Add detailed view for top 3
        if len(top_opps) > 0:
            lines.append("")
            lines.append(f"{cls.EMOJI_TARGET} <b>Top Opportunities Details:</b>")
            lines.append("")
            
            for opp in top_opps[:3]:
                lines.append(cls.format_arbitrage_opportunity(opp))
                lines.append("")
        
        # Add strategy note
        lines.append("")
        lines.append("<i>Strategy: Long on first exchange (lower funding)")
        lines.append("Short on second exchange (higher funding)</i>")
        
        return "\n".join(lines)
    
    @classmethod
    def format_exchanges_list(cls, exchanges: List[str]) -> str:
        """Format list of available exchanges."""
        lines = [
            f"{cls.EMOJI_EXCHANGE} <b>Available Exchanges</b>",
            "",
        ]
        
        for i, name in enumerate(sorted(exchanges), 1):
            lines.append(f"  {i}. <code>{name}</code>")
        
        lines.append("")
        lines.append(f"Total: <code>{len(exchanges)}</code> exchanges")
        
        return "\n".join(lines)
    
    @classmethod
    def format_help(cls) -> str:
        """Format help message."""
        return f"""
{cls.EMOJI_CHART} <b>Funding Rate Arbitrage Bot</b>

<b>📊 Market Data:</b>
/rates - Get top funding rates
/rates binance - Rates from specific exchange
/arbitrage - Find arbitrage opportunities
/exchanges - List available exchanges

<b>💳 Account:</b>
/wallet - View your EVM & Solana wallets
/settings - View your trading settings
/set amount 500 - Set trade amount ($500)
/set leverage 20 - Set max leverage (20x)

<b>🟢 HyperLiquid Trading:</b>
/hl - Account status & balance
/hl_setup - Setup HyperLiquid (check balance & deposit)
/hl_create_api - Create API key (after deposit)
/hl_buy ETH 100 - Market buy $100 of ETH
/hl_buy BTC 50 97000 - Limit buy $50 of BTC at $97k
/hl_sell ETH 100 - Market sell $100 of ETH
/hl_positions - View positions
/hl_close BTC - Close position
/hl_orders - View open orders
/hl_cancel BTC 12345 - Cancel order
/hl_leverage BTC 10 - Set leverage

<b>🌉 Bridge:</b>
/bridge - Check balance & deposit USDC to HyperLiquid

<b>🔐 Security:</b>
/export_keys - Export your private keys

<i>⚠️ HyperLiquid requires deposit before API setup</i>

<b>⚙️ Settings:</b>
• <code>amount</code> - Trade amount (USDT)
• <code>maxamount</code> - Max trade amount
• <code>leverage</code> - Max leverage (1-100)
• <code>spread</code> - Min funding spread (%)
• <code>volume</code> - Min 24h volume

<b>🏦 13 Supported Exchanges:</b>
Binance, Bybit, OKX, Bitget, BingX, MEXC, 
Gate.io, Hyperliquid, Hibachi, Pacifica, 
Lighter, Backpack, Drift
"""
    
    @classmethod
    def format_start(cls) -> str:
        """Format start message."""
        return f"""
{cls.EMOJI_MONEY} <b>Welcome to Funding Rate Arbitrage Bot!</b>

This bot helps you find funding rate arbitrage opportunities across 13+ cryptocurrency exchanges.

{cls.EMOJI_TARGET} <b>Quick Start:</b>
• /rates - View top funding rates
• /arbitrage - Find arbitrage opportunities
• /hl - HyperLiquid account & trading
• /exchanges - See all supported exchanges
• /help - Full command list

{cls.EMOJI_FIRE} <b>Features:</b>
• Real-time funding rates from 13 exchanges
• Automatic arbitrage opportunity detection
• HyperLiquid DEX trading integration
• Auto-generated wallets (EVM + Solana)

Type /help for all available commands.
"""
    
    @classmethod
    def format_loading(cls, message: str = "Fetching data...") -> str:
        """Format loading message."""
        return f"⏳ <i>{message}</i>"
    
    @classmethod
    def format_error(cls, error: str) -> str:
        """Format error message."""
        return f"{cls.EMOJI_CROSS} <b>Error:</b> {error}"

