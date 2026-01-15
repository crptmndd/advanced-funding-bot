"""Gate.io direct API connector."""

from datetime import datetime
from typing import Optional

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class GateDirectExchange(DirectAPIExchange):
    """
    Gate.io Futures API direct connector.
    
    API Docs: https://www.gate.io/docs/developers/apiv4/
    
    Endpoints used:
    - GET /api/v4/futures/usdt/contracts - All USDT contracts with funding and volumes
    """
    
    name = "gate"
    display_name = "Gate.io"
    base_url = "https://api.gateio.ws/api/v4"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Gate.io."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Get all USDT perpetual contracts
            url = f"{self.base_url}/futures/usdt/contracts"
            contracts = await self._request("GET", url)
            
            if not contracts:
                result.error = "Failed to fetch contracts from Gate.io"
                return result
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(contracts)} perpetual markets"
            )
            
            for contract in contracts:
                try:
                    name = contract.get("name", "")
                    if not name:
                        continue
                    
                    # Convert Gate.io format (BTC_USDT) to unified format
                    base = name.replace("_USDT", "")
                    symbol = f"{base}/USDT:USDT"
                    
                    # Get funding rate
                    funding_rate = float(contract.get("funding_rate", 0) or 0)
                    
                    # Get prices
                    mark_price = float(contract.get("mark_price", 0) or 0) or None
                    index_price = float(contract.get("index_price", 0) or 0) or None
                    
                    # Get 24h volume
                    # volume_24h_usd or trade_size * mark_price
                    volume_24h = float(contract.get("volume_24h_usd", 0) or 0) or None
                    if not volume_24h:
                        # Fallback: calculate from trade_size (in base) and mark_price
                        trade_size = float(contract.get("trade_size", 0) or 0)
                        if trade_size and mark_price:
                            volume_24h = trade_size * mark_price
                    
                    # Get open interest in quote currency
                    open_interest = float(contract.get("position_size", 0) or 0) or None
                    
                    # Funding interval in seconds, convert to hours
                    funding_interval = int(contract.get("funding_interval", 28800))
                    interval_hours = funding_interval // 3600
                    
                    # Next funding time
                    next_funding_time = None
                    funding_next = contract.get("funding_next_apply")
                    if funding_next:
                        next_funding_time = self._parse_timestamp(float(funding_next))
                    
                    if next_funding_time is None:
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
                    )
                    result.rates.append(rate)
                    
                except Exception as e:
                    self._logger.debug(f"Failed to parse {contract.get('name')}: {e}")
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result
