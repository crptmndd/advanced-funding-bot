"""
Funding Rate Fetcher - Main Entry Point

This module provides CLI interface for fetching funding rates from various exchanges.

Usage:
    # Fetch from all available exchanges
    python -m src.main
    
    # Fetch from specific exchanges
    python -m src.main --exchanges bybit okx gate
    
    # Show only top N rates
    python -m src.main --top 20
    
    # Analyze arbitrage opportunities
    python -m src.main --arbitrage
    
    # List available exchanges
    python -m src.main --list-exchanges
    
    # Verbose output for debugging
    python -m src.main -v
"""

import argparse
import asyncio
import sys
from datetime import datetime
from typing import List, Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.exchanges import ExchangeRegistry, get_exchange, get_all_exchanges
from src.models import FundingRateData, ExchangeFundingRates, ArbitrageOpportunity
from src.services import ArbitrageAnalyzer
from src.services.arbitrage_analyzer import AnalyzerConfig
from src.utils import setup_logger, get_logger


def format_time_until(dt: Optional[datetime]) -> str:
    """Format time until next funding as human-readable string."""
    if dt is None:
        return "N/A"
    
    now = datetime.utcnow()
    diff = dt - now
    
    if diff.total_seconds() < 0:
        return "Now"
    
    hours = int(diff.total_seconds() // 3600)
    minutes = int((diff.total_seconds() % 3600) // 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def format_funding_time(dt: Optional[datetime]) -> str:
    """Format funding time as HH:MM UTC."""
    if dt is None:
        return "N/A"
    return dt.strftime("%H:%M UTC")


def format_price(price: Optional[float]) -> str:
    """
    Format price with appropriate precision.
    
    Shows significant digits based on price magnitude:
    - >= 10000: no decimals ($12,345)
    - >= 1000: 1 decimal ($1,234.5)
    - >= 100: 2 decimals ($123.45)
    - >= 1: 2-4 decimals ($1.23, $12.34)
    - >= 0.01: 4 decimals ($0.0123)
    - < 0.01: up to 8 significant digits ($0.00001234)
    """
    if price is None or price == 0:
        return "N/A"
    
    abs_price = abs(price)
    
    if abs_price >= 10000:
        return f"${price:,.0f}"
    elif abs_price >= 1000:
        return f"${price:,.1f}"
    elif abs_price >= 100:
        return f"${price:,.2f}"
    elif abs_price >= 10:
        return f"${price:,.3f}"
    elif abs_price >= 1:
        return f"${price:,.4f}"
    elif abs_price >= 0.01:
        return f"${price:.4f}"
    elif abs_price >= 0.0001:
        return f"${price:.6f}"
    elif abs_price >= 0.000001:
        return f"${price:.8f}"
    else:
        # Very small prices - show in scientific notation or full
        return f"${price:.10f}".rstrip('0').rstrip('.')


def format_volume(volume: Optional[float]) -> str:
    """Format volume in human-readable format."""
    if volume is None or volume == 0:
        return "N/A"
    
    if volume >= 1_000_000_000:
        return f"${volume / 1_000_000_000:.1f}B"
    elif volume >= 1_000_000:
        return f"${volume / 1_000_000:.1f}M"
    elif volume >= 1_000:
        return f"${volume / 1_000:.0f}K"
    else:
        return f"${volume:.0f}"


console = Console()


def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Fetch funding rates from cryptocurrency exchanges and find arbitrage opportunities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Fetch from all exchanges
  %(prog)s -e bybit okx             # Fetch from Bybit and OKX only
  %(prog)s --exchanges gate mexc    # Fetch from Gate.io and MEXC
  %(prog)s --top 10                 # Show top 10 positive and negative rates
  %(prog)s --arbitrage              # Show arbitrage opportunities
  %(prog)s --arbitrage --top 20     # Show top 20 arbitrage opportunities
  %(prog)s --list-exchanges         # List all available exchanges
  %(prog)s -v                       # Verbose output for debugging
        """
    )
    
    parser.add_argument(
        "-e", "--exchanges",
        nargs="+",
        metavar="EXCHANGE",
        help="List of exchanges to fetch data from (default: all available)",
    )
    
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        metavar="N",
        help="Number of top results to display (default: 10)",
    )
    
    parser.add_argument(
        "--list-exchanges",
        action="store_true",
        help="List all available exchanges and exit",
    )
    
    parser.add_argument(
        "--all-exchanges",
        action="store_true",
        help="Include unavailable exchanges (will show errors)",
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output for debugging",
    )
    
    parser.add_argument(
        "--symbol",
        type=str,
        metavar="SYMBOL",
        help="Fetch funding rate for specific symbol only (e.g., BTC/USDT:USDT)",
    )
    
    # Arbitrage options
    parser.add_argument(
        "--arbitrage", "-a",
        action="store_true",
        help="Show arbitrage opportunities between exchanges",
    )
    
    parser.add_argument(
        "--min-spread",
        type=float,
        default=0.01,
        metavar="PERCENT",
        help="Minimum funding spread for arbitrage (default: 0.01%%)",
    )
    
    parser.add_argument(
        "--max-price-spread",
        type=float,
        default=1.0,
        metavar="PERCENT",
        help="Maximum price spread between exchanges (default: 1.0%%)",
    )
    
    parser.add_argument(
        "--min-volume",
        type=float,
        default=100000,
        metavar="USD",
        help="Minimum 24h volume required (default: $100,000)",
    )
    
    return parser


def list_exchanges() -> None:
    """Display list of available exchanges."""
    table = Table(title="Available Exchanges", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan")
    table.add_column("Display Name", style="green")
    table.add_column("Status", style="yellow")
    
    all_names = ExchangeRegistry.get_all_names()
    available_names = ExchangeRegistry.get_available_names()
    
    for name in sorted(all_names):
        exchange = get_exchange(name)
        if exchange:
            status = "[green]✓ Available[/]" if name in available_names else "[red]✗ Not Available[/]"
            table.add_row(name, exchange.display_name, status)
    
    console.print(table)
    console.print(f"\n[dim]Total: {len(all_names)} exchanges, {len(available_names)} available[/]")


def display_funding_rates(
    all_rates: List[ExchangeFundingRates],
    top_n: int = 10,
    verbose: bool = False,
) -> None:
    """Display funding rates in a formatted table."""
    # Collect all rates
    combined_rates: List[FundingRateData] = []
    for exchange_rates in all_rates:
        if exchange_rates.success:
            combined_rates.extend(exchange_rates.rates)
    
    if not combined_rates:
        console.print("[yellow]No funding rates fetched.[/]")
        return
    
    # Calculate stats for verbose output
    if verbose:
        rates_with_volume = sum(1 for r in combined_rates if r.volume_24h and r.volume_24h > 0)
        rates_with_price = sum(1 for r in combined_rates if r.mark_price and r.mark_price > 0)
        console.print(f"[dim]Stats: {rates_with_volume}/{len(combined_rates)} rates with volume, {rates_with_price}/{len(combined_rates)} with price[/]")
    
    # Summary panel
    summary = Panel(
        f"[bold]Total rates collected:[/] {len(combined_rates)} from {len(all_rates)} exchanges",
        title="Summary",
        border_style="cyan",
    )
    console.print(summary)
    
    # Top positive rates
    positive = sorted(
        [r for r in combined_rates if r.funding_rate > 0],
        key=lambda x: x.funding_rate,
        reverse=True,
    )[:top_n]
    
    if positive:
        table_positive = Table(
            title=f"🔺 Top {len(positive)} Positive Funding Rates (Long pays Short)",
            show_header=True,
            header_style="bold red",
        )
        table_positive.add_column("Symbol", style="cyan", min_width=15)
        table_positive.add_column("Exchange", style="green", min_width=10)
        table_positive.add_column("Rate (%)", justify="right", style="red")
        table_positive.add_column("Annualized", justify="right", style="red")
        table_positive.add_column("Next Funding", justify="right", style="yellow")
        table_positive.add_column("Mark Price", justify="right")
        table_positive.add_column("Max Order", justify="right", style="cyan")
        if verbose:
            table_positive.add_column("24h Volume", justify="right", style="dim")
        
        for rate in positive:
            next_funding = format_time_until(rate.next_funding_time)
            row = [
                rate.symbol,
                rate.exchange,
                f"{rate.funding_rate_percent:+.4f}%",
                f"{rate.annualized_rate:+.1f}%",
                next_funding,
                format_price(rate.mark_price),
                format_volume(rate.max_order_value) if rate.max_order_value else "N/A",
            ]
            if verbose:
                row.append(format_volume(rate.volume_24h))
            table_positive.add_row(*row)
        
        console.print(table_positive)
    
    # Top negative rates
    negative = sorted(
        [r for r in combined_rates if r.funding_rate < 0],
        key=lambda x: x.funding_rate,
    )[:top_n]
    
    if negative:
        table_negative = Table(
            title=f"🔻 Top {len(negative)} Negative Funding Rates (Short pays Long)",
            show_header=True,
            header_style="bold green",
        )
        table_negative.add_column("Symbol", style="cyan", min_width=15)
        table_negative.add_column("Exchange", style="green", min_width=10)
        table_negative.add_column("Rate (%)", justify="right", style="green")
        table_negative.add_column("Annualized", justify="right", style="green")
        table_negative.add_column("Next Funding", justify="right", style="yellow")
        table_negative.add_column("Mark Price", justify="right")
        table_negative.add_column("Max Order", justify="right", style="cyan")
        if verbose:
            table_negative.add_column("24h Volume", justify="right", style="dim")
        
        for rate in negative:
            next_funding = format_time_until(rate.next_funding_time)
            row = [
                rate.symbol,
                rate.exchange,
                f"{rate.funding_rate_percent:+.4f}%",
                f"{rate.annualized_rate:+.1f}%",
                next_funding,
                format_price(rate.mark_price),
                format_volume(rate.max_order_value) if rate.max_order_value else "N/A",
            ]
            if verbose:
                row.append(format_volume(rate.volume_24h))
            table_negative.add_row(*row)
        
        console.print(table_negative)


def display_arbitrage_opportunities(
    opportunities: List[ArbitrageOpportunity],
    top_n: int = 10,
    verbose: bool = False,
) -> None:
    """Display arbitrage opportunities in a formatted table."""
    if not opportunities:
        console.print("[yellow]No arbitrage opportunities found matching criteria.[/]")
        return
    
    # Take top N
    top_opportunities = opportunities[:top_n]
    
    # Summary
    summary = Panel(
        f"[bold]Found {len(opportunities)} arbitrage opportunities[/]\n"
        f"Showing top {len(top_opportunities)} by quality score",
        title="💰 Arbitrage Analysis",
        border_style="green",
    )
    console.print(summary)
    
    # Main opportunities table
    table = Table(
        title=f"🎯 Top {len(top_opportunities)} Funding Rate Arbitrage Opportunities",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Symbol", style="cyan", min_width=8)
    table.add_column("Long Exchange", style="green", min_width=14)
    table.add_column("Short Exchange", style="red", min_width=14)
    table.add_column("Spread", justify="right", style="bold yellow")
    table.add_column("Annual", justify="right", style="yellow")
    table.add_column("Price Δ", justify="right")
    table.add_column("Max Order", justify="right", style="cyan")
    table.add_column("Time", justify="right", style="dim")
    
    for opp in top_opportunities:
        # Format long position with max order
        long_max = format_volume(opp.long_max_order) if opp.long_max_order else "N/A"
        long_info = f"{opp.long_exchange}\n{opp.long_funding_rate:+.4f}%\n{long_max}"
        
        # Format short position with max order
        short_max = format_volume(opp.short_max_order) if opp.short_max_order else "N/A"
        short_info = f"{opp.short_exchange}\n{opp.short_funding_rate:+.4f}%\n{short_max}"
        
        # Price spread color based on value
        if opp.price_spread_percent < 0.1:
            price_color = "green"
        elif opp.price_spread_percent < 0.5:
            price_color = "yellow"
        else:
            price_color = "red"
        
        # Max position size (minimum of both exchanges)
        max_pos = opp.max_position_size
        max_pos_str = format_volume(max_pos) if max_pos else "N/A"
        
        row = [
            opp.symbol,
            long_info,
            short_info,
            f"{opp.funding_spread:.4f}%",
            f"{opp.annualized_spread:.1f}%",
            f"[{price_color}]{opp.price_spread_percent:.3f}%[/]",
            max_pos_str,
            f"{opp.time_to_funding_hours:.1f}h",
        ]
        
        table.add_row(*row)
    
    console.print(table)
    
    # Legend
    console.print("\n[dim]Strategy: Long on first exchange (lower funding), Short on second exchange (higher funding)[/]")
    console.print("[dim]Spread = Short funding - Long funding (profit per funding period)[/]")
    console.print("[dim]Max Order = Maximum position size limited by both exchanges[/]")
    
    if verbose and opportunities:
        # Show detailed breakdown of top opportunity
        top = opportunities[0]
        console.print(f"\n[bold]Top Opportunity Details ({top.symbol}):[/]")
        console.print(f"  Long {top.long_exchange}: {top.long_funding_rate:+.4f}% @ {format_price(top.long_mark_price)}")
        console.print(f"    Max Order: {format_volume(top.long_max_order) if top.long_max_order else 'N/A'}")
        console.print(f"  Short {top.short_exchange}: {top.short_funding_rate:+.4f}% @ {format_price(top.short_mark_price)}")
        console.print(f"    Max Order: {format_volume(top.short_max_order) if top.short_max_order else 'N/A'}")
        console.print(f"  Funding Spread: {top.funding_spread:.4f}% per period")
        console.print(f"  Daily Profit: ~{top.daily_spread:.4f}%")
        console.print(f"  Annualized: ~{top.annualized_spread:.1f}%")
        if top.max_position_size:
            console.print(f"  Max Position: {format_volume(top.max_position_size)}")


def display_errors(all_rates: List[ExchangeFundingRates]) -> None:
    """Display any errors that occurred during fetching."""
    errors = [r for r in all_rates if not r.success]
    
    if errors:
        console.print("\n[bold red]Errors:[/]")
        for rate in errors:
            console.print(f"  [red]• {rate.exchange}:[/] {rate.error}")


async def fetch_from_exchanges(
    exchange_names: Optional[List[str]] = None,
    include_unavailable: bool = False,
    symbol: Optional[str] = None,
    verbose: bool = False,
) -> List[ExchangeFundingRates]:
    """
    Fetch funding rates from specified exchanges.
    
    Args:
        exchange_names: List of exchange names, or None for all
        include_unavailable: Include exchanges without working API
        symbol: Specific symbol to fetch, or None for all
        verbose: Enable verbose logging
        
    Returns:
        List of ExchangeFundingRates for each exchange
    """
    logger = get_logger()
    
    # Determine which exchanges to fetch from
    if exchange_names:
        exchanges = {}
        for name in exchange_names:
            exchange = get_exchange(name)
            if exchange:
                exchanges[name] = exchange
            else:
                logger.warning(f"[yellow]Unknown exchange: {name}[/]")
    else:
        exchanges = get_all_exchanges(only_available=not include_unavailable)
    
    if not exchanges:
        logger.error("[red]No exchanges available to fetch from[/]")
        return []
    
    logger.info(f"[bold]Fetching funding rates from {len(exchanges)} exchanges...[/]")
    
    if verbose:
        logger.info(f"[dim]Exchanges: {', '.join(exchanges.keys())}[/]")
    
    # Fetch from all exchanges concurrently
    async def fetch_single(name: str, exchange):
        try:
            if verbose:
                logger.debug(f"[dim]Starting fetch from {name}...[/]")
            
            if symbol:
                result = await exchange.fetch_funding_rate(symbol)
            else:
                result = await exchange.fetch_funding_rates()
            
            if verbose and result.success:
                rates_with_vol = sum(1 for r in result.rates if r.volume_24h)
                logger.debug(f"[dim]{name}: {len(result.rates)} rates, {rates_with_vol} with volume[/]")
            
            return result
        except Exception as e:
            logger.error(f"[red]{name}:[/] {e}")
            return ExchangeFundingRates(exchange=name, error=str(e))
    
    tasks = [fetch_single(name, exchange) for name, exchange in exchanges.items()]
    results = await asyncio.gather(*tasks)
    
    # Close all connections
    await ExchangeRegistry.close_all()
    
    return results


async def main_async(args: argparse.Namespace) -> int:
    """Async main function."""
    # Setup logger
    import logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logger(level=log_level)
    
    logger = get_logger()
    
    # List exchanges and exit if requested
    if args.list_exchanges:
        list_exchanges()
        return 0
    
    # Fetch funding rates
    results = await fetch_from_exchanges(
        exchange_names=args.exchanges,
        include_unavailable=args.all_exchanges,
        symbol=args.symbol,
        verbose=args.verbose,
    )
    
    if not results:
        return 1
    
    # Analyze arbitrage if requested
    if args.arbitrage:
        if args.verbose:
            logger.info("[dim]Running arbitrage analysis...[/]")
        
        config = AnalyzerConfig(
            min_funding_spread=args.min_spread,
            max_price_spread=args.max_price_spread,
            min_volume_24h=args.min_volume,
        )
        
        analyzer = ArbitrageAnalyzer(config)
        
        # Get stats
        if args.verbose:
            stats = analyzer.get_stats(results)
            logger.info(
                f"[dim]Analysis stats: {stats['total_rates']} rates, "
                f"{stats['unique_symbols']} symbols, "
                f"{stats['multi_exchange_symbols']} on 2+ exchanges[/]"
            )
        
        # Find opportunities
        opportunities = analyzer.analyze(results, verbose=args.verbose)
        
        # Display opportunities
        display_arbitrage_opportunities(opportunities, top_n=args.top, verbose=args.verbose)
    else:
        # Display regular funding rates
        display_funding_rates(results, top_n=args.top, verbose=args.verbose)
    
    display_errors(results)
    
    return 0


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
