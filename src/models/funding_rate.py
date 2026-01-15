"""Models for funding rate data."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict


@dataclass
class FundingRateData:
    """Represents funding rate data for a single trading pair."""
    
    symbol: str
    exchange: str
    funding_rate: float  # Current funding rate as decimal (e.g., 0.0001 = 0.01%)
    funding_rate_percent: float  # Funding rate as percentage (e.g., 0.01)
    next_funding_time: Optional[datetime] = None
    previous_funding_rate: Optional[float] = None
    mark_price: Optional[float] = None
    index_price: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    interval_hours: int = 8  # Funding interval in hours (typically 8h)
    volume_24h: Optional[float] = None  # 24h trading volume in quote currency (USDT)
    open_interest: Optional[float] = None  # Open interest in quote currency
    max_order_value: Optional[float] = None  # Maximum order value in USDT
    max_leverage: Optional[int] = None  # Maximum leverage allowed
    
    @property
    def annualized_rate(self) -> float:
        """Calculate annualized funding rate based on interval."""
        fundings_per_year = (365 * 24) / self.interval_hours
        return self.funding_rate_percent * fundings_per_year
    
    @property
    def daily_rate(self) -> float:
        """Calculate daily funding rate."""
        fundings_per_day = 24 / self.interval_hours
        return self.funding_rate_percent * fundings_per_day
    
    def __repr__(self) -> str:
        return (
            f"FundingRateData(symbol={self.symbol}, exchange={self.exchange}, "
            f"rate={self.funding_rate_percent:.4f}%, annualized={self.annualized_rate:.2f}%)"
        )


@dataclass
class ExchangeFundingRates:
    """Collection of funding rates from a single exchange."""
    
    exchange: str
    rates: list[FundingRateData] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None
    
    @property
    def success(self) -> bool:
        """Check if data was fetched successfully."""
        return self.error is None
    
    @property
    def count(self) -> int:
        """Number of funding rates fetched."""
        return len(self.rates)
    
    def get_by_symbol(self, symbol: str) -> Optional[FundingRateData]:
        """Get funding rate for a specific symbol."""
        for rate in self.rates:
            if rate.symbol == symbol:
                return rate
        return None
    
    def get_top_positive(self, n: int = 10) -> list[FundingRateData]:
        """Get top N positive funding rates."""
        positive = [r for r in self.rates if r.funding_rate > 0]
        return sorted(positive, key=lambda x: x.funding_rate, reverse=True)[:n]
    
    def get_top_negative(self, n: int = 10) -> list[FundingRateData]:
        """Get top N negative funding rates (most negative first)."""
        negative = [r for r in self.rates if r.funding_rate < 0]
        return sorted(negative, key=lambda x: x.funding_rate)[:n]


@dataclass
class ArbitrageOpportunity:
    """
    Represents a funding rate arbitrage opportunity between two exchanges.
    
    Strategy: Long on exchange with negative funding (receive funding)
              Short on exchange with positive funding (receive funding)
    
    Or: Long on lower funding, Short on higher funding to capture the spread.
    """
    
    symbol: str  # Base symbol (e.g., BTC/USDT:USDT)
    
    # Long position (exchange with lower/negative funding)
    long_exchange: str
    long_funding_rate: float  # Funding rate percent
    long_mark_price: Optional[float]
    long_volume_24h: Optional[float]
    long_next_funding: Optional[datetime]
    long_interval_hours: int
    
    # Short position (exchange with higher/positive funding)
    short_exchange: str
    short_funding_rate: float  # Funding rate percent
    short_mark_price: Optional[float]
    short_volume_24h: Optional[float]
    short_next_funding: Optional[datetime]
    short_interval_hours: int
    
    # Order limits
    long_max_order: Optional[float] = None  # Max order value on long exchange (USDT)
    short_max_order: Optional[float] = None  # Max order value on short exchange (USDT)
    
    # Calculated metrics
    funding_spread: float = 0  # Difference in funding rates (short - long)
    price_spread_percent: float = 0  # Price difference between exchanges
    
    # Quality metrics
    min_volume_24h: float = 0  # Minimum volume across both exchanges
    time_to_funding_hours: float = 8  # Time until next funding (min of both)
    
    @property
    def max_position_size(self) -> Optional[float]:
        """Maximum position size limited by both exchanges."""
        limits = [l for l in [self.long_max_order, self.short_max_order] if l and l > 0]
        return min(limits) if limits else None
    
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def annualized_spread(self) -> float:
        """Calculate annualized funding spread based on average interval."""
        avg_interval = (self.long_interval_hours + self.short_interval_hours) / 2
        fundings_per_year = (365 * 24) / avg_interval
        return self.funding_spread * fundings_per_year
    
    @property
    def daily_spread(self) -> float:
        """Calculate daily funding spread."""
        avg_interval = (self.long_interval_hours + self.short_interval_hours) / 2
        fundings_per_day = 24 / avg_interval
        return self.funding_spread * fundings_per_day
    
    @property
    def next_funding_profit(self) -> float:
        """Expected profit from next funding payment (as %)."""
        return self.funding_spread
    
    @property
    def is_profitable(self) -> bool:
        """Check if opportunity is profitable after considering price spread."""
        # Need at least more funding spread than price spread to be profitable
        return self.funding_spread > abs(self.price_spread_percent)
    
    @property
    def quality_score(self) -> float:
        """
        Calculate quality score for ranking opportunities.
        
        Considers:
        - Funding spread (higher is better)
        - Volume (higher is better for liquidity)
        - Price spread (lower is better)
        - Time to funding (sooner is better for quick profits)
        """
        # Base score from funding spread
        score = self.funding_spread * 100
        
        # Volume bonus (log scale, max 50 points)
        if self.min_volume_24h and self.min_volume_24h > 0:
            import math
            volume_score = min(50, math.log10(self.min_volume_24h + 1) * 5)
            score += volume_score
        
        # Price spread penalty (up to -30 points)
        price_penalty = min(30, abs(self.price_spread_percent) * 10)
        score -= price_penalty
        
        # Time bonus (sooner funding = bonus, up to 20 points)
        if self.time_to_funding_hours < 8:
            time_bonus = (8 - self.time_to_funding_hours) * 2.5
            score += time_bonus
        
        return score
    
    def __repr__(self) -> str:
        return (
            f"ArbitrageOpportunity({self.symbol}: "
            f"Long {self.long_exchange} {self.long_funding_rate:+.4f}%, "
            f"Short {self.short_exchange} {self.short_funding_rate:+.4f}%, "
            f"Spread={self.funding_spread:.4f}%)"
        )

