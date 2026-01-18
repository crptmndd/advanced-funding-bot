"""Binance Futures direct API connector."""

from datetime import datetime
from typing import Optional, Dict

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class BinanceDirectExchange(DirectAPIExchange):
    """
    Binance USDT-M Futures direct API connector.
    
    API Docs: https://binance-docs.github.io/apidocs/futures/en/
    
    Endpoints used:
    - GET /fapi/v1/premiumIndex - All mark prices and funding rates
    - GET /fapi/v1/ticker/24hr - 24h ticker data with volumes
    - GET /fapi/v1/exchangeInfo - Exchange info with order limits
    """
    
    name = "binance"
    display_name = "Binance"
    base_url = "https://fapi.binance.com"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Binance Futures."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get all premium index data (includes funding rates and mark prices)
            premium_url = f"{self.base_url}/fapi/v1/premiumIndex"
            premium_data = await self._request("GET", premium_url)
            
            if not premium_data:
                result.error = "Failed to fetch data from Binance API"
                return result
            
            # Get 24h ticker data for volumes
            ticker_url = f"{self.base_url}/fapi/v1/ticker/24hr"
            ticker_data = await self._request("GET", ticker_url)
            
            # Get exchange info for order limits
            exchange_info_url = f"{self.base_url}/fapi/v1/exchangeInfo"
            exchange_info = await self._request("GET", exchange_info_url)
            
            # Create volume map
            volume_map: Dict[str, Dict] = {}
            if ticker_data:
                for ticker in ticker_data:
                    symbol = ticker.get("symbol", "")
                    volume_map[symbol] = ticker
            
            # Create limits map from exchange info
            limits_map: Dict[str, Dict] = {}
            if exchange_info and exchange_info.get("symbols"):
                for sym_info in exchange_info["symbols"]:
                    symbol = sym_info.get("symbol", "")
                    limits_map[symbol] = sym_info
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(premium_data)} perpetual markets"
            )
            
            for item in premium_data:
                try:
                    # Parse symbol - Binance uses BTCUSDT format
                    raw_symbol = item.get("symbol", "")
                    if not raw_symbol.endswith("USDT"):
                        continue
                    
                    base = raw_symbol.replace("USDT", "")
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
                    
                    # Get order limits from exchange info filters
                    sym_limits = limits_map.get(raw_symbol, {})
                    max_order_value = None
                    max_leverage = None
                    
                    # Parse filters for limits
                    for f in sym_limits.get("filters", []):
                        filter_type = f.get("filterType")
                        
                        # LOT_SIZE contains maxQty (max order quantity in base)
                        if filter_type == "LOT_SIZE":
                            max_qty = float(f.get("maxQty", 0) or 0)
                            if max_qty and mark_price:
                                max_order_value = max_qty * mark_price
                        
                        # MARKET_LOT_SIZE for market orders (usually smaller)
                        # We use LOT_SIZE as it's for limit orders which is more relevant
                    
                    # Binance uses 8-hour funding interval
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
