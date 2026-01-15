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
    
    # List available exchanges
    python -m src.main --list-exchanges
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
from src.models import FundingRateData, ExchangeFundingRates
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


console = Console()


def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Fetch funding rates from cryptocurrency exchanges",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Fetch from all exchanges
  %(prog)s -e bybit okx             # Fetch from Bybit and OKX only
  %(prog)s --exchanges gate mexc    # Fetch from Gate.io and MEXC
  %(prog)s --top 10                 # Show top 10 positive and negative rates
  %(prog)s --list-exchanges         # List all available exchanges
  %(prog)s -v                       # Verbose output
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
        help="Number of top positive/negative rates to display (default: 10)",
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
        help="Enable verbose output",
    )
    
    parser.add_argument(
        "--symbol",
        type=str,
        metavar="SYMBOL",
        help="Fetch funding rate for specific symbol only (e.g., BTC/USDT:USDT)",
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
        
        for rate in positive:
            mark_price = f"${rate.mark_price:,.2f}" if rate.mark_price else "N/A"
            next_funding = format_time_until(rate.next_funding_time)
            table_positive.add_row(
                rate.symbol,
                rate.exchange,
                f"{rate.funding_rate_percent:+.4f}%",
                f"{rate.annualized_rate:+.1f}%",
                next_funding,
                mark_price,
            )
        
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
        
        for rate in negative:
            mark_price = f"${rate.mark_price:,.2f}" if rate.mark_price else "N/A"
            next_funding = format_time_until(rate.next_funding_time)
            table_negative.add_row(
                rate.symbol,
                rate.exchange,
                f"{rate.funding_rate_percent:+.4f}%",
                f"{rate.annualized_rate:+.1f}%",
                next_funding,
                mark_price,
            )
        
        console.print(table_negative)


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
) -> List[ExchangeFundingRates]:
    """
    Fetch funding rates from specified exchanges.
    
    Args:
        exchange_names: List of exchange names, or None for all
        include_unavailable: Include exchanges without working API
        symbol: Specific symbol to fetch, or None for all
        
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
    
    # Fetch from all exchanges concurrently
    async def fetch_single(name: str, exchange):
        try:
            if symbol:
                return await exchange.fetch_funding_rate(symbol)
            else:
                return await exchange.fetch_funding_rates()
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
    
    # List exchanges and exit if requested
    if args.list_exchanges:
        list_exchanges()
        return 0
    
    # Fetch funding rates
    results = await fetch_from_exchanges(
        exchange_names=args.exchanges,
        include_unavailable=args.all_exchanges,
        symbol=args.symbol,
    )
    
    # Display results
    if results:
        display_funding_rates(results, top_n=args.top)
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

