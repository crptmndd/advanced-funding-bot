"""Backpack Exchange direct API connector."""

from datetime import datetime
from typing import Optional, Dict, Any, List

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class BackpackDirectExchange(DirectAPIExchange):
    """
    Backpack Exchange direct API connector.
    
    API Docs: https://docs.backpack.exchange/
    
    Endpoints used:
    - GET /api/v1/markets - Market info with filters and specs
    - GET /api/v1/tickers - Current prices and volumes
    - GET /api/v1/markPrices - All mark prices with funding rates
    """
    
    name = "backpack"
    display_name = "Backpack"
    base_url = "https://api.backpack.exchange"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Backpack."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get markets info for order limits
            markets_url = f"{self.base_url}/api/v1/markets"
            markets_data = await self._request("GET", markets_url)
            
            # Build market info mapping for perpetuals
            market_info: Dict[str, Dict[str, Any]] = {}
            if markets_data:
                for market in markets_data:
                    symbol = market.get("symbol", "")
                    if "_PERP" in symbol or market.get("marketType") == "PERP":
                        market_info[symbol] = market
            
            # Get mark prices - this contains funding rates too!
            mark_prices_url = f"{self.base_url}/api/v1/markPrices"
            mark_data = await self._request("GET", mark_prices_url)
            
            if not mark_data:
                result.error = "Failed to fetch mark prices from Backpack"
                return result
            
            # Filter for PERP markets only
            perp_data = [m for m in mark_data if "_PERP" in m.get("symbol", "")]
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(perp_data)} perpetual markets"
            )
            
            # Get tickers for volume
            tickers = await self._fetch_tickers()
            
            # Process each perpetual market
            for item in perp_data:
                try:
                    symbol = item.get("symbol", "")
                    if not symbol:
                        continue
                    
                    # Get base currency from symbol (e.g., SOL_USDC_PERP -> SOL)
                    base = symbol.split("_")[0]
                    unified_symbol = f"{base}/USDT:USDT"
                    
                    # Get funding rate
                    funding_rate = float(item.get("fundingRate", 0) or 0)
                    
                    # Backpack has 1-hour funding intervals
                    interval_hours = 1
                    
                    # Get mark price
                    mark_price = None
                    mp = item.get("markPrice")
                    if mp:
                        try:
                            mark_price = float(mp)
                        except:
                            pass
                    
                    # Get index price
                    index_price = None
                    ip = item.get("indexPrice")
                    if ip:
                        try:
                            index_price = float(ip)
                        except:
                            pass
                    
                    # Get next funding time
                    next_funding_time = None
                    nft = item.get("nextFundingTimestamp")
                    if nft:
                        next_funding_time = self._parse_timestamp(nft)
                    if next_funding_time is None:
                        next_funding_time = calculate_next_funding_time(interval_hours)
                    
                    # Get volume from tickers
                    volume_24h = None
                    ticker = tickers.get(symbol, {})
                    if ticker:
                        vol = ticker.get("quoteVolume") or ticker.get("volume")
                        if vol:
                            try:
                                volume_24h = float(vol)
                            except:
                                pass
                    
                    # Get order limits from market info
                    max_order_value = None
                    max_leverage = None
                    
                    market = market_info.get(symbol, {})
                    if market:
                        # Get open interest limit as max order proxy
                        oi_limit = market.get("openInterestLimit")
                        if oi_limit and mark_price:
                            try:
                                max_order_value = float(oi_limit) * mark_price
                            except:
                                pass
                        
                        # Try IMF function for leverage estimation
                        imf = market.get("imfFunction", {})
                        if imf:
                            base_imf = imf.get("base")
                            if base_imf:
                                try:
                                    # max_leverage ≈ 1 / IMF base
                                    max_leverage = int(1 / float(base_imf))
                                except:
                                    pass
                    
                    rate = FundingRateData(
                        symbol=unified_symbol,
                        exchange=self.name,
                        funding_rate=funding_rate,
                        funding_rate_percent=funding_rate * 100,
                        next_funding_time=next_funding_time,
                        mark_price=mark_price,
                        index_price=index_price,
                        interval_hours=interval_hours,
                        volume_24h=volume_24h,
                        open_interest=None,
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
    
    async def _fetch_tickers(self) -> Dict[str, Dict]:
        """Fetch tickers for volume data."""
        tickers = {}
        try:
            url = f"{self.base_url}/api/v1/tickers"
            data = await self._request("GET", url)
            
            if data:
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            symbol = item.get("symbol")
                            if symbol:
                                tickers[symbol] = item
                elif isinstance(data, dict):
                    tickers = data
                    
        except Exception as e:
            self._logger.debug(f"Failed to fetch tickers: {e}")
        
        return tickers
