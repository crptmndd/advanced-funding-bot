"""Base class for exchange connectors."""

from abc import ABC, abstractmethod
from typing import Optional

from src.models import ExchangeFundingRates


class BaseExchange(ABC):
    """Abstract base class for all exchange connectors."""
    
    name: str = "base"
    display_name: str = "Base Exchange"
    
    def __init__(self, api_key: Optional[str] = None, secret: Optional[str] = None):
        """
        Initialize exchange connector.
        
        Args:
            api_key: Optional API key for authenticated requests
            secret: Optional API secret
        """
        self.api_key = api_key
        self.secret = secret
    
    @abstractmethod
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """
        Fetch all available funding rates from the exchange.
        
        Returns:
            ExchangeFundingRates object containing all funding rate data
        """
        pass
    
    @abstractmethod
    async def fetch_funding_rate(self, symbol: str) -> Optional[ExchangeFundingRates]:
        """
        Fetch funding rate for a specific symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC/USDT:USDT")
            
        Returns:
            ExchangeFundingRates with single rate or None if not found
        """
        pass
    
    @property
    def is_available(self) -> bool:
        """Check if exchange connector is properly configured and available."""
        return True
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name}>"

