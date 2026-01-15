"""OKX direct API connector."""

import asyncio
from datetime import datetime
from typing import Optional, List, Dict

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class OKXDirectExchange(DirectAPIExchange):
    """
    OKX API direct connector.
    
    API Docs: https://www.okx.com/docs-v5/en/
    
    Endpoints used:
    - GET /api/v5/public/instruments - Get all instruments
    - GET /api/v5/public/funding-rate - Get funding rate
    - GET /api/v5/market/tickers - Get all tickers for prices and volumes
    """
    
    name = "okx"
    display_name = "OKX"
    base_url = "https://www.okx.com"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from OKX."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Step 1: Get all SWAP instruments
            instruments_url = f"{self.base_url}/api/v5/public/instruments"
            instruments_data = await self._request(
                "GET", instruments_url, 
                params={"instType": "SWAP"}
            )
            
            if not instruments_data or instruments_data.get("code") != "0":
                result.error = "Failed to fetch instruments from OKX"
                return result
            
            instruments = instruments_data.get("data", [])
            
            # Filter USDT-margined swaps
            usdt_swaps = [
                inst for inst in instruments 
                if inst.get("settleCcy") == "USDT" and inst.get("state") == "live"
            ]
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(usdt_swaps)} perpetual markets"
            )
            
            # Step 2: Get all tickers for prices and volumes
            tickers_url = f"{self.base_url}/api/v5/market/tickers"
            tickers_data = await self._request(
                "GET", tickers_url,
                params={"instType": "SWAP"}
            )
            
            tickers_map = {}
            if tickers_data and tickers_data.get("code") == "0":
                for ticker in tickers_data.get("data", []):
                    inst_id = ticker.get("instId", "")
                    tickers_map[inst_id] = ticker
            
            # Step 3: Fetch funding rates in batches
            semaphore = asyncio.Semaphore(20)
            
            async def fetch_single_funding(inst_id: str) -> Optional[Dict]:
                async with semaphore:
                    url = f"{self.base_url}/api/v5/public/funding-rate"
                    data = await self._request("GET", url, params={"instId": inst_id})
                    if data and data.get("code") == "0" and data.get("data"):
                        return data["data"][0]
                    return None
            
            tasks = [
                fetch_single_funding(inst.get("instId"))
                for inst in usdt_swaps
            ]
            
            funding_results = await asyncio.gather(*tasks)
            
            # Process results
            for inst, funding_data in zip(usdt_swaps, funding_results):
                try:
                    inst_id = inst.get("instId", "")
                    
                    # Parse symbol - OKX uses BTC-USDT-SWAP format
                    parts = inst_id.split("-")
                    if len(parts) >= 2:
                        base = parts[0]
                        symbol = f"{base}/USDT:USDT"
                    else:
                        continue
                    
                    # Get funding rate
                    funding_rate = 0
                    next_funding_time = None
                    
                    if funding_data:
                        funding_rate = float(funding_data.get("fundingRate", 0) or 0)
                        next_funding_ts = funding_data.get("nextFundingTime")
                        next_funding_time = self._parse_timestamp(next_funding_ts)
                    
                    if next_funding_time is None:
                        next_funding_time = calculate_next_funding_time(8)
                    
                    # Get prices and volume from tickers
                    ticker = tickers_map.get(inst_id, {})
                    mark_price = None
                    index_price = None
                    volume_24h = None
                    open_interest = None
                    
                    if ticker:
                        mark_price = float(ticker.get("last", 0) or 0) or None
                        # volCcy24h is volume in quote currency
                        volume_24h = float(ticker.get("volCcy24h", 0) or 0) or None
                    
                    # OKX uses 8-hour funding interval
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
                    self._logger.debug(f"Failed to parse {inst.get('instId')}: {e}")
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result
