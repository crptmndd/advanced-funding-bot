"""BingX direct API connector."""

from datetime import datetime
from typing import Optional

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class BingXDirectExchange(DirectAPIExchange):
    """
    BingX API direct connector.
    
    API Docs: https://bingx-api.github.io/docs/
    
    Endpoints used:
    - GET /openApi/swap/v2/quote/premiumIndex - Premium index with funding
    - GET /openApi/swap/v2/quote/ticker - Ticker data with volumes
    """
    
    name = "bingx"
    display_name = "BingX"
    base_url = "https://open-api.bingx.com"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from BingX."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get all contracts with funding rates
            premium_url = f"{self.base_url}/openApi/swap/v2/quote/premiumIndex"
            premium_data = await self._request("GET", premium_url)
            
            if not premium_data or premium_data.get("code") != 0:
                result.error = f"BingX API error: {premium_data.get('msg', 'Unknown') if premium_data else 'No response'}"
                return result
            
            contracts = premium_data.get("data", [])
            
            # Get ticker data for volumes
            ticker_url = f"{self.base_url}/openApi/swap/v2/quote/ticker"
            ticker_data = await self._request("GET", ticker_url)
            
            # Create volume map
            volume_map = {}
            if ticker_data and ticker_data.get("code") == 0:
                for ticker in ticker_data.get("data", []):
                    symbol = ticker.get("symbol", "")
                    volume_map[symbol] = ticker
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(contracts)} perpetual markets"
            )
            
            for item in contracts:
                try:
                    raw_symbol = item.get("symbol", "")
                    if not raw_symbol.endswith("-USDT"):
                        continue
                    
                    base = raw_symbol.replace("-USDT", "")
                    symbol = f"{base}/USDT:USDT"
                    
                    # Get funding rate
                    funding_rate = float(item.get("lastFundingRate", 0) or 0)
                    
                    # Get prices
                    mark_price = float(item.get("markPrice", 0) or 0) or None
                    index_price = float(item.get("indexPrice", 0) or 0) or None
                    
                    # Get next funding time
                    next_funding_ts = item.get("nextFundingTime")
                    next_funding_time = self._parse_timestamp(next_funding_ts)
                    
                    if next_funding_time is None:
                        next_funding_time = calculate_next_funding_time(8)
                    
                    # Get volume from ticker data
                    ticker = volume_map.get(raw_symbol, {})
                    volume_24h = float(ticker.get("quoteVolume", 0) or 0) or None
                    open_interest = float(ticker.get("openInterest", 0) or 0) or None
                    
                    # BingX uses 8-hour funding interval
                    interval_hours = 8
                    
                    rate = FundingRateData(
                        symbol=symbol,
                        exchange=self.name,
                        funding_rate=funding_rate,
                        funding_rate_percent=funding_rate * 100,
                        next_funding_time=next_funding_time,
                        mark_price=mark_price,
                        index_price=index_price,
                        interval_hours=interval_hours,
                        volume_24h=volume_24h,
                        open_interest=open_interest,
                    )
                    result.rates.append(rate)
                    
                except Exception as e:
                    self._logger.debug(f"Failed to parse {item.get('symbol')}: {e}")
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result
