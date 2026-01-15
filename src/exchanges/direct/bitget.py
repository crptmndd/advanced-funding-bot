"""Bitget direct API connector."""

from datetime import datetime
from typing import Optional

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class BitgetDirectExchange(DirectAPIExchange):
    """
    Bitget API direct connector.
    
    API Docs: https://www.bitget.com/api-doc/
    
    Endpoints used:
    - GET /api/v2/mix/market/tickers - All tickers with volumes
    - GET /api/v2/mix/market/current-fund-rate - Current funding rates
    """
    
    name = "bitget"
    display_name = "Bitget"
    base_url = "https://api.bitget.com"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Bitget."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get all USDT-M tickers
            tickers_url = f"{self.base_url}/api/v2/mix/market/tickers"
            tickers_data = await self._request(
                "GET", tickers_url,
                params={"productType": "USDT-FUTURES"}
            )
            
            if not tickers_data or tickers_data.get("code") != "00000":
                result.error = f"Bitget API error: {tickers_data.get('msg', 'Unknown') if tickers_data else 'No response'}"
                return result
            
            tickers = tickers_data.get("data", [])
            
            # Get funding rates
            funding_url = f"{self.base_url}/api/v2/mix/market/current-fund-rate"
            funding_data = await self._request(
                "GET", funding_url,
                params={"productType": "USDT-FUTURES"}
            )
            
            # Create funding rate map
            funding_map = {}
            if funding_data and funding_data.get("code") == "00000":
                for item in funding_data.get("data", []):
                    symbol = item.get("symbol", "")
                    funding_map[symbol] = item
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(tickers)} perpetual markets"
            )
            
            for ticker in tickers:
                try:
                    raw_symbol = ticker.get("symbol", "")
                    if not raw_symbol.endswith("USDT"):
                        continue
                    
                    base = raw_symbol.replace("USDT", "")
                    symbol = f"{base}/USDT:USDT"
                    
                    # Get funding rate from funding data
                    funding_info = funding_map.get(raw_symbol, {})
                    funding_rate = float(funding_info.get("fundingRate", 0) or 0)
                    
                    # Get prices from ticker
                    mark_price = float(ticker.get("markPrice", 0) or 0) or None
                    index_price = float(ticker.get("indexPrice", 0) or 0) or None
                    last_price = float(ticker.get("lastPr", 0) or 0) or None
                    
                    if mark_price is None:
                        mark_price = last_price
                    
                    # Get 24h volume (usdtVolume is in USDT)
                    volume_24h = float(ticker.get("usdtVolume", 0) or 0) or None
                    
                    # Get open interest
                    open_interest = float(ticker.get("openInterestUsd", 0) or 0) or None
                    
                    # Get next funding time
                    next_funding_time = calculate_next_funding_time(8)
                    
                    # Bitget uses 8-hour funding interval
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
                    self._logger.debug(f"Failed to parse {ticker.get('symbol')}: {e}")
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result
