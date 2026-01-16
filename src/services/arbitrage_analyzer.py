"""
Arbitrage Analyzer Service

Analyzes funding rates across exchanges to find arbitrage opportunities.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from src.models import FundingRateData, ExchangeFundingRates, ArbitrageOpportunity
from src.utils import get_logger


@dataclass
class AnalyzerConfig:
    """Configuration for arbitrage analysis."""
    
    # Minimum funding spread to consider (in percent)
    min_funding_spread: float = 0.01  # 0.01%
    
    # Maximum price spread allowed (in percent)
    max_price_spread: float = 1.0  # 1%
    
    # Minimum 24h volume required (in USDT)
    min_volume_24h: float = 100_000  # $100k
    
    # Minimum exchanges required for a symbol
    min_exchanges: int = 2
    
    # Whether to include symbols without volume data
    include_no_volume: bool = False
    
    # Maximum time to next funding to consider (hours)
    max_time_to_funding: float = 24.0  # 24 hours


class ArbitrageAnalyzer:
    """
    Analyzes funding rates across multiple exchanges to find arbitrage opportunities.
    
    Strategy:
    - Find symbols listed on multiple exchanges
    - Calculate funding rate spread between exchanges
    - Filter by price spread, volume, and other quality metrics
    - Rank opportunities by profitability and quality
    """
    
    def __init__(self, config: Optional[AnalyzerConfig] = None):
        self.config = config or AnalyzerConfig()
        self._logger = get_logger()
    
    def find_opportunities(
        self,
        exchange_rates: List[ExchangeFundingRates],
        limit: int = 10,
        verbose: bool = False,
    ) -> List[ArbitrageOpportunity]:
        """
        Find arbitrage opportunities (convenience method).
        
        Args:
            exchange_rates: List of funding rates from each exchange
            limit: Maximum number of opportunities to return
            verbose: Enable verbose logging
            
        Returns:
            List of top arbitrage opportunities
        """
        all_opportunities = self.analyze(exchange_rates, verbose)
        return all_opportunities[:limit]
    
    def analyze(
        self,
        exchange_rates: List[ExchangeFundingRates],
        verbose: bool = False,
    ) -> List[ArbitrageOpportunity]:
        """
        Analyze funding rates and find arbitrage opportunities.
        
        Args:
            exchange_rates: List of funding rates from each exchange
            verbose: Enable verbose logging
            
        Returns:
            List of arbitrage opportunities sorted by quality score
        """
        # Step 1: Group rates by normalized symbol
        symbol_rates = self._group_by_symbol(exchange_rates)
        
        if verbose:
            self._logger.info(
                f"[dim]Analyzer: Found {len(symbol_rates)} unique symbols across exchanges[/]"
            )
        
        # Step 2: Find opportunities for each symbol
        opportunities = []
        
        for symbol, rates in symbol_rates.items():
            # Need at least 2 exchanges
            if len(rates) < self.config.min_exchanges:
                continue
            
            # Find best opportunity for this symbol
            opps = self._find_opportunities_for_symbol(symbol, rates, verbose)
            opportunities.extend(opps)
        
        if verbose:
            self._logger.info(
                f"[dim]Analyzer: Found {len(opportunities)} raw opportunities[/]"
            )
        
        # Step 3: Filter opportunities
        filtered = self._filter_opportunities(opportunities, verbose)
        
        if verbose:
            self._logger.info(
                f"[dim]Analyzer: {len(filtered)} opportunities after filtering[/]"
            )
        
        # Step 4: Sort by quality score
        sorted_opportunities = sorted(
            filtered,
            key=lambda x: x.quality_score,
            reverse=True,
        )
        
        return sorted_opportunities
    
    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol for cross-exchange matching."""
        # Remove :USDT or :USD suffix and standardize
        symbol = symbol.upper()
        
        # Handle different formats
        # BTC/USDT:USDT -> BTC
        # BTC/USD:USD -> BTC
        if "/" in symbol:
            base = symbol.split("/")[0]
        else:
            base = symbol.replace("USDT", "").replace("USD", "").replace("_", "")
        
        return base.strip()
    
    def _group_by_symbol(
        self,
        exchange_rates: List[ExchangeFundingRates],
    ) -> Dict[str, List[FundingRateData]]:
        """Group funding rates by normalized symbol."""
        symbol_rates: Dict[str, List[FundingRateData]] = defaultdict(list)
        
        for ex_rates in exchange_rates:
            if not ex_rates.success:
                continue
            
            for rate in ex_rates.rates:
                normalized = self._normalize_symbol(rate.symbol)
                symbol_rates[normalized].append(rate)
        
        return dict(symbol_rates)
    
    def _find_opportunities_for_symbol(
        self,
        symbol: str,
        rates: List[FundingRateData],
        verbose: bool = False,
    ) -> List[ArbitrageOpportunity]:
        """Find all arbitrage opportunities for a single symbol."""
        opportunities = []
        
        # Compare all pairs of exchanges
        for i, rate_a in enumerate(rates):
            for rate_b in rates[i + 1:]:
                # Skip same exchange
                if rate_a.exchange == rate_b.exchange:
                    continue
                
                # Determine long and short positions
                # Long on lower funding, short on higher funding
                if rate_a.funding_rate_percent < rate_b.funding_rate_percent:
                    long_rate = rate_a
                    short_rate = rate_b
                else:
                    long_rate = rate_b
                    short_rate = rate_a
                
                # Calculate funding spread
                funding_spread = short_rate.funding_rate_percent - long_rate.funding_rate_percent
                
                # Skip if spread is too small
                if funding_spread < self.config.min_funding_spread:
                    continue
                
                # Calculate price spread
                price_spread = self._calculate_price_spread(
                    long_rate.mark_price,
                    short_rate.mark_price,
                )
                
                # Calculate minimum volume
                min_volume = self._calculate_min_volume(
                    long_rate.volume_24h,
                    short_rate.volume_24h,
                )
                
                # Calculate time to funding
                time_to_funding = self._calculate_time_to_funding(
                    long_rate.next_funding_time,
                    short_rate.next_funding_time,
                )
                
                opportunity = ArbitrageOpportunity(
                    symbol=symbol,
                    long_exchange=long_rate.exchange,
                    long_funding_rate=long_rate.funding_rate_percent,
                    long_mark_price=long_rate.mark_price,
                    long_volume_24h=long_rate.volume_24h,
                    long_next_funding=long_rate.next_funding_time,
                    long_interval_hours=long_rate.interval_hours,
                    short_exchange=short_rate.exchange,
                    short_funding_rate=short_rate.funding_rate_percent,
                    short_mark_price=short_rate.mark_price,
                    short_volume_24h=short_rate.volume_24h,
                    short_next_funding=short_rate.next_funding_time,
                    short_interval_hours=short_rate.interval_hours,
                    long_max_order=long_rate.max_order_value,
                    short_max_order=short_rate.max_order_value,
                    funding_spread=funding_spread,
                    price_spread_percent=price_spread,
                    min_volume_24h=min_volume,
                    time_to_funding_hours=time_to_funding,
                )
                
                opportunities.append(opportunity)
        
        return opportunities
    
    def _calculate_price_spread(
        self,
        price_a: Optional[float],
        price_b: Optional[float],
    ) -> float:
        """Calculate price spread between two prices as percentage."""
        if price_a is None or price_b is None:
            return 0.0
        
        if price_a == 0 or price_b == 0:
            return 0.0
        
        avg_price = (price_a + price_b) / 2
        diff = abs(price_a - price_b)
        
        return (diff / avg_price) * 100
    
    def _calculate_min_volume(
        self,
        volume_a: Optional[float],
        volume_b: Optional[float],
    ) -> float:
        """Calculate minimum volume across both exchanges."""
        volumes = [v for v in [volume_a, volume_b] if v is not None and v > 0]
        
        if not volumes:
            return 0.0
        
        return min(volumes)
    
    def _calculate_time_to_funding(
        self,
        time_a: Optional[datetime],
        time_b: Optional[datetime],
    ) -> float:
        """Calculate minimum time to next funding in hours."""
        now = datetime.utcnow()
        times = []
        
        for t in [time_a, time_b]:
            if t is not None:
                diff = (t - now).total_seconds() / 3600
                if diff > 0:
                    times.append(diff)
        
        if not times:
            return 8.0  # Default to 8 hours
        
        return min(times)
    
    def _filter_opportunities(
        self,
        opportunities: List[ArbitrageOpportunity],
        verbose: bool = False,
    ) -> List[ArbitrageOpportunity]:
        """Filter opportunities based on configuration."""
        filtered = []
        
        for opp in opportunities:
            # Check price spread
            if opp.price_spread_percent > self.config.max_price_spread:
                if verbose:
                    self._logger.debug(
                        f"[dim]Filtered {opp.symbol}: price spread {opp.price_spread_percent:.2f}% > {self.config.max_price_spread}%[/]"
                    )
                continue
            
            # Check volume
            if not self.config.include_no_volume:
                if opp.min_volume_24h < self.config.min_volume_24h:
                    if verbose:
                        self._logger.debug(
                            f"[dim]Filtered {opp.symbol}: volume ${opp.min_volume_24h:,.0f} < ${self.config.min_volume_24h:,.0f}[/]"
                        )
                    continue
            
            # Check time to funding
            if opp.time_to_funding_hours > self.config.max_time_to_funding:
                if verbose:
                    self._logger.debug(
                        f"[dim]Filtered {opp.symbol}: time to funding {opp.time_to_funding_hours:.1f}h > {self.config.max_time_to_funding}h[/]"
                    )
                continue
            
            filtered.append(opp)
        
        return filtered
    
    def get_stats(
        self,
        exchange_rates: List[ExchangeFundingRates],
    ) -> Dict:
        """Get statistics about the data."""
        total_rates = 0
        exchanges_count = 0
        symbols_set = set()
        
        for ex_rates in exchange_rates:
            if ex_rates.success:
                exchanges_count += 1
                total_rates += len(ex_rates.rates)
                for rate in ex_rates.rates:
                    symbols_set.add(self._normalize_symbol(rate.symbol))
        
        # Count symbols on multiple exchanges
        symbol_rates = self._group_by_symbol(exchange_rates)
        multi_exchange = sum(1 for rates in symbol_rates.values() if len(rates) >= 2)
        
        return {
            "total_rates": total_rates,
            "exchanges": exchanges_count,
            "unique_symbols": len(symbols_set),
            "multi_exchange_symbols": multi_exchange,
        }

