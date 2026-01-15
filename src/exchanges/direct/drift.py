"""Drift Protocol direct API connector."""

from datetime import datetime
from typing import Optional, Dict, Any, List

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class DriftDirectExchange(DirectAPIExchange):
    """
    Drift Protocol direct API connector.
    
    API Docs: https://drift-labs.github.io/v2-teacher/
    
    Drift is a Solana-based perpetuals DEX.
    
    Endpoints:
    - GET /contracts - All contract data including prices, funding rates, volumes
    
    Note: Drift funding rates in API are already in percentage format (not decimal).
    Example: -0.019488 means -0.019488% hourly rate
    """
    
    name = "drift"
    display_name = "Drift"
    base_url = "https://data.api.drift.trade"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Drift."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get all contracts - this endpoint has everything!
            contracts_url = f"{self.base_url}/contracts"
            data = await self._request("GET", contracts_url)
            
            if not data or "contracts" not in data:
                result.error = "Failed to fetch contracts from Drift"
                return result
            
            contracts = data.get("contracts", [])
            
            # Filter for PERP markets only
            perp_contracts = [c for c in contracts if c.get("product_type") == "PERP"]
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(perp_contracts)} perpetual markets"
            )
            
            for contract in perp_contracts:
                try:
                    ticker_id = contract.get("ticker_id", "")
                    if not ticker_id or "-PERP" not in ticker_id:
                        continue
                    
                    # Convert SOL-PERP to SOL/USDT:USDT
                    base = ticker_id.replace("-PERP", "")
                    # Normalize 1M prefixed tokens (1MBONK -> 1000BONK)
                    if base.startswith("1M"):
                        base = "1000" + base[2:]
                    # Keep 1K prefix as is (1KPUMP stays 1KPUMP for consistency)
                    symbol = f"{base}/USDT:USDT"
                    
                    # Get funding rate - use next_funding_rate as it's the current expected rate
                    # IMPORTANT: Drift API returns funding rate ALREADY in percentage format!
                    # Example: -0.019488 means -0.019488% (not -1.9488%)
                    next_rate_str = contract.get("next_funding_rate")
                    if next_rate_str and next_rate_str != "N/A":
                        try:
                            # Value is already in percentage format
                            funding_rate_percent = float(next_rate_str)
                            # Convert to decimal for internal calculations
                            funding_rate = funding_rate_percent / 100
                        except:
                            funding_rate = 0.0
                            funding_rate_percent = 0.0
                    else:
                        # Fallback to funding_rate if next_funding_rate not available
                        fr = contract.get("funding_rate")
                        if fr and fr != "N/A":
                            try:
                                funding_rate_percent = float(fr)
                                funding_rate = funding_rate_percent / 100
                            except:
                                funding_rate = 0.0
                                funding_rate_percent = 0.0
                        else:
                            continue  # Skip if no funding rate available
                    
                    # Drift has 1-hour funding
                    interval_hours = 1
                    
                    # Get prices
                    mark_price = None
                    last_price = contract.get("last_price")
                    if last_price:
                        try:
                            mark_price = float(last_price)
                        except:
                            pass
                    
                    index_price = None
                    idx_price = contract.get("index_price")
                    if idx_price:
                        try:
                            index_price = float(idx_price)
                        except:
                            pass
                    
                    # Get 24h volume (quote volume in USDC)
                    volume_24h = None
                    quote_vol = contract.get("quote_volume")
                    if quote_vol:
                        try:
                            volume_24h = float(quote_vol)
                        except:
                            pass
                    
                    # Get open interest
                    open_interest = None
                    oi = contract.get("open_interest")
                    if oi and mark_price:
                        try:
                            # Convert base amount to USD
                            oi_val = float(oi)
                            if oi_val > 0:
                                open_interest = oi_val * mark_price
                        except:
                            pass
                    
                    # Get next funding time
                    next_funding_time = None
                    next_ts = contract.get("next_funding_rate_timestamp")
                    if next_ts:
                        next_funding_time = self._parse_timestamp(next_ts)
                    if next_funding_time is None:
                        next_funding_time = calculate_next_funding_time(interval_hours)
                    
                    rate = FundingRateData(
                        symbol=symbol,
                        exchange=self.name,
                        funding_rate=funding_rate,
                        funding_rate_percent=funding_rate_percent,
                        next_funding_time=next_funding_time,
                        mark_price=mark_price,
                        index_price=index_price,
                        interval_hours=interval_hours,
                        volume_24h=volume_24h,
                        open_interest=open_interest,
                        max_order_value=None,
                        max_leverage=None,
                    )
                    result.rates.append(rate)
                    
                except Exception as e:
                    self._logger.debug(f"Failed to parse contract {contract.get('ticker_id')}: {e}")
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result
