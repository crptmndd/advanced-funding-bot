"""Lighter direct API connector."""

from datetime import datetime
from typing import Optional, Dict, Any, List

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class LighterDirectExchange(DirectAPIExchange):
    """
    Lighter exchange direct API connector.
    
    API Docs: https://apidocs.lighter.xyz/reference/funding-rates
    GitHub: https://github.com/elliottech/lighter-python
    
    Lighter is a zkSync-based perps exchange.
    
    Endpoints used:
    - GET /api/v1/funding-rates - Funding rates for all markets
    - GET /api/v1/orderBooks - Market info with order limits
    """
    
    name = "lighter"
    display_name = "Lighter"
    base_url = "https://mainnet.zklighter.elliot.ai"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Lighter."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get order books for market info and order limits
            orderbooks_url = f"{self.base_url}/api/v1/orderBooks"
            orderbooks_data = await self._request("GET", orderbooks_url)
            
            # Build market info mapping by market_id
            market_info: Dict[int, Dict[str, Any]] = {}
            symbol_to_market_id: Dict[str, int] = {}
            
            if orderbooks_data and orderbooks_data.get("code") == 200:
                order_books = orderbooks_data.get("order_books", [])
                for ob in order_books:
                    if ob.get("market_type") == "perp":
                        market_id = ob.get("market_id")
                        symbol = ob.get("symbol")
                        if market_id is not None:
                            market_info[market_id] = ob
                            if symbol:
                                symbol_to_market_id[symbol] = market_id
            
            # Get funding rates
            funding_url = f"{self.base_url}/api/v1/funding-rates"
            funding_data = await self._request("GET", funding_url)
            
            if not funding_data or funding_data.get("code") != 200:
                result.error = "Failed to fetch funding rates from Lighter"
                return result
            
            rates_list = funding_data.get("funding_rates", [])
            
            if not rates_list:
                result.error = "No funding rates returned from Lighter"
                return result
            
            # Filter for unique symbols (Lighter aggregates rates from multiple exchanges)
            seen_symbols = set()
            lighter_rates = []
            
            for rate_data in rates_list:
                symbol = rate_data.get("symbol")
                
                # Skip if already seen
                if symbol in seen_symbols:
                    continue
                
                seen_symbols.add(symbol)
                lighter_rates.append(rate_data)
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(lighter_rates)} perpetual markets"
            )
            
            for rate_data in lighter_rates:
                try:
                    symbol_raw = rate_data.get("symbol", "")
                    if not symbol_raw:
                        continue
                    
                    # Convert to unified format
                    symbol = f"{symbol_raw}/USDT:USDT"
                    
                    # Get funding rate
                    funding_rate = float(rate_data.get("rate", 0) or 0)
                    
                    # Lighter has 1-hour funding interval
                    interval_hours = 1
                    
                    # Get market info if available
                    market_id = rate_data.get("market_id") or symbol_to_market_id.get(symbol_raw)
                    mkt = market_info.get(market_id, {}) if market_id else {}
                    
                    # Get max order value from market info
                    max_order_value = None
                    max_leverage = None
                    
                    if mkt:
                        order_limit = mkt.get("order_quote_limit")
                        if order_limit:
                            try:
                                max_order_value = float(order_limit)
                                # Cap unrealistic values (>$100M is usually a technical limit)
                                if max_order_value > 100_000_000:
                                    max_order_value = None
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
                        mark_price=None,  # Not available without auth
                        index_price=None,
                        interval_hours=interval_hours,
                        volume_24h=None,
                        open_interest=None,
                        max_order_value=max_order_value,
                        max_leverage=max_leverage,
                    )
                    result.rates.append(rate)
                    
                except Exception as e:
                    self._logger.debug(f"Failed to parse funding rate: {e}")
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result
