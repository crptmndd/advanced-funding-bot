"""Hyperliquid DEX direct API connector."""

from datetime import datetime
from typing import Optional

from src.models import FundingRateData, ExchangeFundingRates
from .base import DirectAPIExchange, calculate_next_funding_time


class HyperliquidDirectExchange(DirectAPIExchange):
    """
    Hyperliquid DEX API direct connector.
    
    API Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/
    
    Endpoints used:
    - POST /info - Meta and asset contexts with funding rates and volumes
    
    Note: Hyperliquid is a DEX, order limits may be dynamic or based on liquidity
    """
    
    name = "hyperliquid"
    display_name = "Hyperliquid"
    base_url = "https://api.hyperliquid.xyz"
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from Hyperliquid."""
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            session = await self._get_session()
            
            # Hyperliquid uses POST for info endpoint
            url = f"{self.base_url}/info"
            
            # Get meta info (includes funding rates)
            async with session.post(
                url,
                json={"type": "metaAndAssetCtxs"},
                headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status != 200:
                    result.error = f"Hyperliquid API error: {resp.status}"
                    return result
                
                data = await resp.json()
            
            # data[0] contains meta info with universe
            # data[1] contains asset contexts with funding rates
            meta = data[0] if len(data) > 0 else {}
            asset_ctxs = data[1] if len(data) > 1 else []
            
            universe = meta.get("universe", [])
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(universe)} perpetual markets"
            )
            
            for i, asset in enumerate(universe):
                try:
                    coin_name = asset.get("name", "")
                    if not coin_name:
                        continue
                    
                    symbol = f"{coin_name}/USD:USD"
                    
                    # Get asset context
                    ctx = asset_ctxs[i] if i < len(asset_ctxs) else {}
                    
                    # Get funding rate (Hyperliquid returns as decimal)
                    funding_rate = float(ctx.get("funding", 0) or 0)
                    
                    # Get mark price
                    mark_price = float(ctx.get("markPx", 0) or 0) or None
                    
                    # Get oracle price as index
                    oracle_price = float(ctx.get("oraclePx", 0) or 0) or None
                    
                    # Get 24h volume (dayNtlVlm is notional volume)
                    volume_24h = float(ctx.get("dayNtlVlm", 0) or 0) or None
                    
                    # Get open interest
                    open_interest = float(ctx.get("openInterest", 0) or 0) or None
                    
                    # Get order limits from asset info
                    max_order_value = None
                    max_leverage = None
                    
                    # maxTradeSz in contracts - multiply by mark price for value
                    max_trade_sz = asset.get("maxTradeSz")
                    sz_decimals = asset.get("szDecimals", 0)
                    
                    if max_trade_sz and mark_price:
                        try:
                            max_order_value = float(max_trade_sz) * mark_price
                        except:
                            pass
                    
                    # Get max leverage from asset
                    max_lev = asset.get("maxLeverage")
                    if max_lev:
                        try:
                            max_leverage = int(float(max_lev))
                        except:
                            pass
                    
                    # Hyperliquid uses hourly funding
                    interval_hours = 1
                    next_funding_time = calculate_next_funding_time(interval_hours)
                    
                    rate = FundingRateData(
                        symbol=symbol,
                        exchange=self.name,
                        funding_rate=funding_rate,
                        funding_rate_percent=funding_rate * 100,
                        next_funding_time=next_funding_time,
                        mark_price=mark_price,
                        index_price=oracle_price,
                        interval_hours=interval_hours,
                        volume_24h=volume_24h,
                        open_interest=open_interest,
                        max_order_value=max_order_value,
                        max_leverage=max_leverage,
                    )
                    result.rates.append(rate)
                    
                except Exception as e:
                    self._logger.debug(f"Failed to parse asset {i}: {e}")
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result
