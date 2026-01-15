"""Base class for direct API exchange connectors."""

import asyncio
import aiohttp
from abc import abstractmethod
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from src.models import FundingRateData, ExchangeFundingRates
from src.exchanges.base import BaseExchange
from src.utils import get_logger


def calculate_next_funding_time(interval_hours: int = 8) -> datetime:
    """
    Calculate next funding time based on standard funding schedule.
    
    Args:
        interval_hours: Funding interval in hours
        
    Returns:
        Next funding datetime in UTC
    """
    now = datetime.utcnow()
    
    if interval_hours == 8:
        funding_hours = [0, 8, 16]
    elif interval_hours == 4:
        funding_hours = [0, 4, 8, 12, 16, 20]
    elif interval_hours == 1:
        funding_hours = list(range(24))
    else:
        funding_hours = [0, 8, 16]
    
    current_hour = now.hour
    next_hour = None
    
    for h in funding_hours:
        if h > current_hour or (h == current_hour and now.minute < 1):
            next_hour = h
            break
    
    if next_hour is None:
        next_hour = funding_hours[0]
        next_date = now.date() + timedelta(days=1)
    else:
        next_date = now.date()
    
    return datetime(next_date.year, next_date.month, next_date.day, next_hour, 0, 0)


class DirectAPIExchange(BaseExchange):
    """
    Base class for direct API exchange connectors.
    
    Uses native exchange REST APIs instead of CCXT for maximum
    data coverage and accuracy.
    """
    
    name: str = "direct"
    display_name: str = "Direct API Exchange"
    base_url: str = ""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(api_key, secret)
        self._logger = get_logger()
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60, connect=30)
            connector = aiohttp.TCPConnector(limit=10, force_close=True)
            self._session = aiohttp.ClientSession(
                headers={"Accept": "application/json"},
                timeout=timeout,
                connector=connector,
            )
        return self._session
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        retries: int = 3,
    ) -> Optional[Dict]:
        """Make HTTP request to API with retry logic."""
        session = await self._get_session()
        
        for attempt in range(retries):
            try:
                async with session.request(method, url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:  # Rate limit
                        await asyncio.sleep(1 * (attempt + 1))
                        continue
                    else:
                        self._logger.warning(
                            f"{self.display_name}: API error {resp.status} for {url}"
                        )
                        return None
            except asyncio.TimeoutError:
                if attempt < retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                self._logger.warning(f"{self.display_name}: Request timeout - {url}")
                return None
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                self._logger.warning(f"{self.display_name}: Request failed - {e}")
                return None
        
        return None
    
    def _parse_timestamp(self, ts: Any) -> Optional[datetime]:
        """Parse timestamp from various formats to datetime."""
        if ts is None:
            return None
        
        try:
            if isinstance(ts, (int, float)):
                # Check if milliseconds or seconds
                if ts > 10000000000:
                    return datetime.utcfromtimestamp(ts / 1000)
                else:
                    return datetime.utcfromtimestamp(ts)
            elif isinstance(ts, str):
                # Try parsing ISO format
                return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, TypeError):
            pass
        
        return None
    
    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol to unified format: BASE/QUOTE:SETTLE
        Example: BTC/USDT:USDT
        """
        return symbol
    
    @abstractmethod
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from the exchange."""
        pass
    
    async def fetch_funding_rate(self, symbol: str) -> Optional[ExchangeFundingRates]:
        """Fetch funding rate for a specific symbol."""
        # Default implementation - fetch all and filter
        all_rates = await self.fetch_funding_rates()
        if not all_rates.success:
            return all_rates
        
        result = ExchangeFundingRates(exchange=self.name)
        for rate in all_rates.rates:
            if rate.symbol == symbol:
                result.rates.append(rate)
                break
        
        return result

