"""Models for funding rate data."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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

