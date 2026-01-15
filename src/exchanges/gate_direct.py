"""Direct Gate.io API connector for funding rate data."""

import aiohttp
from datetime import datetime, timedelta
from typing import Optional

from src.models import FundingRateData, ExchangeFundingRates
from src.exchanges.base import BaseExchange
from src.utils import get_logger


def calculate_next_funding_time(interval_hours: int = 8) -> datetime:
    """Calculate next funding time based on standard schedule."""
    now = datetime.utcnow()
    
    if interval_hours == 8:
        funding_hours = [0, 8, 16]
    elif interval_hours == 4:
        funding_hours = [0, 4, 8, 12, 16, 20]
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


class GateDirectExchange(BaseExchange):
    """
    Gate.io exchange connector using direct API.
    
    Uses Gate.io futures API directly instead of CCXT to avoid
    issues with spot/currencies endpoint that may be blocked in some regions.
    
    API Docs: https://www.gate.io/docs/developers/apiv4/
    """
    
    name = "gate"
    display_name = "Gate.io"
    
    BASE_URL = "https://api.gateio.ws/api/v4"
    FUTURES_URL = f"{BASE_URL}/futures/usdt"
    
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
            self._session = aiohttp.ClientSession(
                headers={"Accept": "application/json"}
            )
        return self._session
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Gate.io futures API."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            session = await self._get_session()
            
            # Fetch all USDT perpetual contracts
            url = f"{self.FUTURES_URL}/contracts"
            
            async with session.get(url) as resp:
                if resp.status != 200:
                    result.error = f"Gate.io API error: {resp.status}"
                    self._logger.error(f"[bold red]{self.display_name}[/]: {result.error}")
                    return result
                
                contracts = await resp.json()
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(contracts)} perpetual markets"
            )
            
            for contract in contracts:
                try:
                    name = contract.get("name", "")
                    if not name:
                        continue
                    
                    # Convert Gate.io symbol format (BTC_USDT) to unified format (BTC/USDT:USDT)
                    base = name.replace("_USDT", "")
                    symbol = f"{base}/USDT:USDT"
                    
                    funding_rate = float(contract.get("funding_rate", 0) or 0)
                    mark_price = float(contract.get("mark_price", 0) or 0) or None
                    index_price = float(contract.get("index_price", 0) or 0) or None
                    
                    # Funding interval in seconds, convert to hours
                    funding_interval = int(contract.get("funding_interval", 28800))
                    interval_hours = funding_interval // 3600
                    
                    # Next funding time - Gate.io provides funding_next_apply timestamp
                    next_funding_time = None
                    funding_next = contract.get("funding_next_apply")
                    if funding_next:
                        try:
                            next_funding_time = datetime.utcfromtimestamp(float(funding_next))
                        except (ValueError, TypeError):
                            pass
                    
                    # If no funding time, calculate based on interval
                    if next_funding_time is None:
                        next_funding_time = calculate_next_funding_time(interval_hours)
                    
                    rate = FundingRateData(
                        symbol=symbol,
                        exchange=self.name,
                        funding_rate=funding_rate,
                        funding_rate_percent=funding_rate * 100,
                        next_funding_time=next_funding_time,
                        mark_price=mark_price,
                        index_price=index_price,
                        interval_hours=interval_hours,
                    )
                    result.rates.append(rate)
                    
                except Exception as e:
                    self._logger.debug(f"Failed to parse contract {contract.get('name')}: {e}")
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result
    
    async def fetch_funding_rate(self, symbol: str) -> Optional[ExchangeFundingRates]:
        """Fetch funding rate for a specific symbol."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            session = await self._get_session()
            
            # Convert unified format (BTC/USDT:USDT) to Gate.io format (BTC_USDT)
            gate_symbol = symbol.replace("/USDT:USDT", "_USDT").replace("/USDT", "_USDT")
            
            url = f"{self.FUTURES_URL}/contracts/{gate_symbol}"
            
            async with session.get(url) as resp:
                if resp.status != 200:
                    result.error = f"Symbol {symbol} not found"
                    return result
                
                contract = await resp.json()
            
            funding_rate = float(contract.get("funding_rate", 0) or 0)
            mark_price = float(contract.get("mark_price", 0) or 0) or None
            index_price = float(contract.get("index_price", 0) or 0) or None
            
            funding_interval = int(contract.get("funding_interval", 28800))
            interval_hours = funding_interval // 3600
            
            # Next funding time
            next_funding_time = None
            funding_next = contract.get("funding_next_apply")
            if funding_next:
                try:
                    next_funding_time = datetime.utcfromtimestamp(float(funding_next))
                except (ValueError, TypeError):
                    pass
            
            if next_funding_time is None:
                next_funding_time = calculate_next_funding_time(interval_hours)
            
            rate = FundingRateData(
                symbol=symbol,
                exchange=self.name,
                funding_rate=funding_rate,
                funding_rate_percent=funding_rate * 100,
                next_funding_time=next_funding_time,
                mark_price=mark_price,
                index_price=index_price,
                interval_hours=interval_hours,
            )
            result.rates.append(rate)
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error fetching {symbol} - {e}")
        finally:
            await self.close()
        
        return result

