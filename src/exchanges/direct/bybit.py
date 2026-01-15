"""Bybit direct API connector."""

from datetime import datetime
from typing import Optional, Dict

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class BybitDirectExchange(DirectAPIExchange):
    """
    Bybit V5 API direct connector.
    
    API Docs: https://bybit-exchange.github.io/docs/v5/intro
    
    Endpoints used:
    - GET /v5/market/tickers - All tickers with funding rates and volumes
    - GET /v5/market/instruments-info - Instruments info with order limits
    """
    
    name = "bybit"
    display_name = "Bybit"
    base_url = "https://api.bybit.com"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Bybit."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get all linear perpetual tickers
            tickers_url = f"{self.base_url}/v5/market/tickers"
            tickers_params = {"category": "linear"}
            tickers_data = await self._request("GET", tickers_url, params=tickers_params)
            
            if not tickers_data or tickers_data.get("retCode") != 0:
                result.error = f"Bybit API error: {tickers_data.get('retMsg', 'Unknown error') if tickers_data else 'No response'}"
                return result
            
            tickers = tickers_data.get("result", {}).get("list", [])
            
            # Get instruments info for order limits
            instruments_url = f"{self.base_url}/v5/market/instruments-info"
            instruments_params = {"category": "linear"}
            instruments_data = await self._request("GET", instruments_url, params=instruments_params)
            
            # Create limits map
            limits_map: Dict[str, Dict] = {}
            if instruments_data and instruments_data.get("retCode") == 0:
                for inst in instruments_data.get("result", {}).get("list", []):
                    symbol = inst.get("symbol", "")
                    limits_map[symbol] = inst
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(tickers)} perpetual markets"
            )
            
            for item in tickers:
                try:
                    raw_symbol = item.get("symbol", "")
                    if not raw_symbol.endswith("USDT"):
                        continue
                    
                    base = raw_symbol.replace("USDT", "")
                    symbol = f"{base}/USDT:USDT"
                    
                    # Get funding rate
                    funding_rate_str = item.get("fundingRate", "0")
                    funding_rate = float(funding_rate_str) if funding_rate_str else 0
                    
                    # Get prices
                    mark_price = float(item.get("markPrice", 0) or 0) or None
                    index_price = float(item.get("indexPrice", 0) or 0) or None
                    
                    # Get next funding time
                    next_funding_ts = item.get("nextFundingTime")
                    next_funding_time = self._parse_timestamp(next_funding_ts)
                    
                    if next_funding_time is None:
                        next_funding_time = calculate_next_funding_time(8)
                    
                    # Get 24h volume (turnover24h is in quote currency)
                    volume_24h = float(item.get("turnover24h", 0) or 0) or None
                    
                    # Get open interest
                    open_interest = float(item.get("openInterestValue", 0) or 0) or None
                    
                    # Get order limits from instruments info
                    inst_info = limits_map.get(raw_symbol, {})
                    max_order_value = None
                    max_leverage = None
                    
                    # Get lot size filter for max order qty
                    lot_filter = inst_info.get("lotSizeFilter", {})
                    max_order_qty = float(lot_filter.get("maxOrderQty", 0) or 0)
                    
                    # Calculate max order value
                    if max_order_qty and mark_price:
                        max_order_value = max_order_qty * mark_price
                    
                    # Get leverage
                    leverage_filter = inst_info.get("leverageFilter", {})
                    max_leverage_str = leverage_filter.get("maxLeverage", "")
                    if max_leverage_str:
                        try:
                            max_leverage = int(float(max_leverage_str))
                        except:
                            pass
                    
                    # Bybit uses 8-hour funding interval
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
