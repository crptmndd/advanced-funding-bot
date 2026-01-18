"""MEXC direct API connector."""

from datetime import datetime
from typing import Optional, Dict

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class MEXCDirectExchange(DirectAPIExchange):
    """
    MEXC Futures API direct connector.
    
    API Docs: https://mexcdevelop.github.io/apidocs/
    
    Endpoints used:
    - GET /api/v1/contract/ticker - All tickers with volumes
    - GET /api/v1/contract/funding_rate - All funding rates
    - GET /api/v1/contract/detail - Contract details with limits
    """
    
    name = "mexc"
    display_name = "MEXC"
    base_url = "https://contract.mexc.com"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from MEXC."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get all tickers
            ticker_url = f"{self.base_url}/api/v1/contract/ticker"
            ticker_data = await self._request("GET", ticker_url)
            
            if not ticker_data or not ticker_data.get("success"):
                result.error = "Failed to fetch tickers from MEXC"
                return result
            
            tickers = ticker_data.get("data", [])
            
            # Create ticker map for prices and volumes
            ticker_map = {}
            for t in tickers:
                symbol = t.get("symbol", "")
                ticker_map[symbol] = t
            
            # Get all funding rates
            funding_url = f"{self.base_url}/api/v1/contract/funding_rate"
            funding_data = await self._request("GET", funding_url)
            
            if not funding_data or not funding_data.get("success"):
                result.error = "Failed to fetch funding rates from MEXC"
                return result
            
            funding_list = funding_data.get("data", [])
            
            # Get contract details for limits
            detail_url = f"{self.base_url}/api/v1/contract/detail"
            detail_data = await self._request("GET", detail_url)
            
            # Create limits map
            limits_map: Dict[str, Dict] = {}
            if detail_data and detail_data.get("success"):
                for detail in detail_data.get("data", []):
                    symbol = detail.get("symbol", "")
                    limits_map[symbol] = detail
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(funding_list)} perpetual markets"
            )
            
            for item in funding_list:
                try:
                    raw_symbol = item.get("symbol", "")
                    if not raw_symbol.endswith("_USDT"):
                        continue
                    
                    base = raw_symbol.replace("_USDT", "")
                    symbol = f"{base}/USDT:USDT"
                    
                    # Get funding rate
                    funding_rate = float(item.get("fundingRate", 0) or 0)
                    
                    # Get prices and volume from ticker
                    ticker = ticker_map.get(raw_symbol, {})
                    mark_price = float(ticker.get("fairPrice", 0) or 0) or None
                    index_price = float(ticker.get("indexPrice", 0) or 0) or None
                    last_price = float(ticker.get("lastPrice", 0) or 0) or None
                    
                    if mark_price is None:
                        mark_price = last_price
                    
                    # Get 24h volume (volume24 is in quote currency)
                    volume_24h = float(ticker.get("volume24", 0) or 0) or None
                    
                    # Get open interest
                    open_interest = float(ticker.get("holdVol", 0) or 0) or None
                    
                    # Get order limits from contract details
                    contract_detail = limits_map.get(raw_symbol, {})
                    max_order_value = None
                    max_leverage = None
                    
                    # maxVol is max order volume in contracts
                    max_vol = contract_detail.get("maxVol")
                    if max_vol and mark_price:
                        try:
                            contract_size = float(contract_detail.get("contractSize", 1) or 1)
                            max_order_value = float(max_vol) * contract_size * mark_price
                        except:
                            pass
                    
                    # Get max leverage
                    max_lev = contract_detail.get("maxLeverage")
                    if max_lev:
                        try:
                            max_leverage = int(float(max_lev))
                        except:
                            pass
                    
                    # Get next funding time
                    next_funding_ts = item.get("nextSettleTime")
                    next_funding_time = self._parse_timestamp(next_funding_ts)
                    
                    if next_funding_time is None:
                        next_funding_time = calculate_next_funding_time(8)
                    
                    # MEXC uses 8-hour funding interval
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
                        max_order_value=max_order_value,
                        max_leverage=max_leverage,
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
