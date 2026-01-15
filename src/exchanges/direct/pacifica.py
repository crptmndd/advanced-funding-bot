"""Pacifica direct API connector."""

from datetime import datetime
from typing import Optional, Dict, Any

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class PacificaDirectExchange(DirectAPIExchange):
    """
    Pacifica exchange direct API connector.
    
    API Docs: https://docs.pacifica.fi/api-documentation/api/rest-api/markets/get-market-info
    
    Endpoints used:
    - GET /api/v1/info - Market info including max order limits
    - GET /api/v1/info/prices - Prices, funding rates, volumes
    """
    
    name = "pacifica"
    display_name = "Pacifica"
    base_url = "https://api.pacifica.fi"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Pacifica."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get market info for order limits and leverage
            info_url = f"{self.base_url}/api/v1/info"
            info_data = await self._request("GET", info_url)
            
            # Build market info mapping
            market_info: Dict[str, Dict[str, Any]] = {}
            if info_data and info_data.get("success"):
                markets = info_data.get("data", [])
                for m in markets:
                    symbol = m.get("symbol")
                    if symbol:
                        market_info[symbol] = m
            
            # Get prices and funding rates
            prices_url = f"{self.base_url}/api/v1/info/prices"
            prices_data = await self._request("GET", prices_url)
            
            if not prices_data or not prices_data.get("success"):
                result.error = "Failed to fetch prices from Pacifica"
                return result
            
            prices_list = prices_data.get("data", [])
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(prices_list)} perpetual markets"
            )
            
            for price_item in prices_list:
                try:
                    symbol_raw = price_item.get("symbol", "")
                    if not symbol_raw:
                        continue
                    
                    # Convert to unified format: BTC -> BTC/USDT:USDT
                    symbol = f"{symbol_raw}/USDT:USDT"
                    
                    # Get funding rate (hourly on Pacifica)
                    funding_rate = float(price_item.get("funding", 0) or 0)
                    
                    # Pacifica has 1-hour funding interval
                    interval_hours = 1
                    
                    # Get mark price
                    mark_price = None
                    mp = price_item.get("mark")
                    if mp:
                        try:
                            mark_price = float(mp)
                        except:
                            pass
                    
                    # Get oracle/index price
                    index_price = None
                    op = price_item.get("oracle")
                    if op:
                        try:
                            index_price = float(op)
                        except:
                            pass
                    
                    # Get 24h volume
                    volume_24h = None
                    vol = price_item.get("volume_24h")
                    if vol:
                        try:
                            volume_24h = float(vol)
                        except:
                            pass
                    
                    # Get open interest
                    open_interest = None
                    oi = price_item.get("open_interest")
                    if oi:
                        try:
                            open_interest = float(oi)
                            # Open interest is in base currency, convert to USD
                            if mark_price:
                                open_interest = open_interest * mark_price
                        except:
                            pass
                    
                    # Get max order size and leverage from market info
                    max_order_value = None
                    max_leverage = None
                    
                    mkt = market_info.get(symbol_raw, {})
                    if mkt:
                        max_order = mkt.get("max_order_size")
                        if max_order:
                            try:
                                max_order_value = float(max_order)
                            except:
                                pass
                        
                        leverage = mkt.get("max_leverage")
                        if leverage:
                            try:
                                max_leverage = int(leverage)
                            except:
                                pass
                    
                    # Calculate next funding time (hourly funding)
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
                        volume_24h=volume_24h,
                        open_interest=open_interest,
                        max_order_value=max_order_value,
                        max_leverage=max_leverage,
                    )
                    result.rates.append(rate)
                    
                except Exception as e:
                    self._logger.debug(f"Failed to parse {price_item.get('symbol')}: {e}")
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result
