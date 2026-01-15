"""CCXT-based exchange connector for funding rate data."""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Type, Dict

import ccxt.async_support as ccxt

from src.models import FundingRateData, ExchangeFundingRates
from src.exchanges.base import BaseExchange
from src.utils import get_logger


def calculate_next_funding_time(interval_hours: int = 8) -> datetime:
    """
    Calculate next funding time based on standard funding schedule.
    Most exchanges use 00:00, 08:00, 16:00 UTC for 8h intervals.
    
    Args:
        interval_hours: Funding interval in hours (default 8)
        
    Returns:
        Next funding datetime in UTC
    """
    now = datetime.utcnow()
    
    # Standard funding times for 8h interval: 00:00, 08:00, 16:00 UTC
    if interval_hours == 8:
        funding_hours = [0, 8, 16]
    elif interval_hours == 4:
        funding_hours = [0, 4, 8, 12, 16, 20]
    elif interval_hours == 1:
        funding_hours = list(range(24))
    else:
        # Default to 8h schedule
        funding_hours = [0, 8, 16]
    
    current_hour = now.hour
    
    # Find next funding hour
    next_hour = None
    for h in funding_hours:
        if h > current_hour or (h == current_hour and now.minute < 1):
            next_hour = h
            break
    
    if next_hour is None:
        # Next funding is tomorrow at first funding hour
        next_hour = funding_hours[0]
        next_date = now.date() + timedelta(days=1)
    else:
        next_date = now.date()
    
    return datetime(next_date.year, next_date.month, next_date.day, next_hour, 0, 0)


class CCXTExchange(BaseExchange):
    """
    Exchange connector using CCXT library.
    Supports: Bybit, Gate, MEXC, OKX, Bitget, BingX, Binance, Hibachi, Hyperliquid
    """
    
    ccxt_class: Type[ccxt.Exchange] = ccxt.Exchange
    name: str = "ccxt"
    display_name: str = "CCXT Exchange"
    
    # Default options for CCXT exchange
    default_options: dict = {}
    
    # Whether to fetch tickers for price data (if funding rate doesn't include it)
    fetch_prices_separately: bool = False
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        password: Optional[str] = None,  # For OKX
        sandbox: bool = False,
    ):
        super().__init__(api_key, secret)
        self.password = password
        self.sandbox = sandbox
        self._exchange: Optional[ccxt.Exchange] = None
        self._logger = get_logger()
        self._tickers_cache: Dict[str, dict] = {}
    
    def _create_exchange(self) -> ccxt.Exchange:
        """Create and configure CCXT exchange instance."""
        config = {
            "enableRateLimit": True,
            "options": self.default_options.copy(),
        }
        
        if self.api_key and self.secret:
            config["apiKey"] = self.api_key
            config["secret"] = self.secret
        
        if self.password:
            config["password"] = self.password
        
        exchange = self.ccxt_class(config)
        
        if self.sandbox:
            exchange.set_sandbox_mode(True)
        
        return exchange
    
    async def _get_exchange(self) -> ccxt.Exchange:
        """Get or create exchange instance."""
        if self._exchange is None:
            self._exchange = self._create_exchange()
        return self._exchange
    
    async def close(self):
        """Close exchange connection."""
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
    
    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol to unified format."""
        return symbol
    
    async def _fetch_tickers_for_prices(self, exchange: ccxt.Exchange, symbols: list) -> None:
        """Fetch tickers to get mark prices for all symbols at once."""
        try:
            if exchange.has.get("fetchTickers"):
                # Batch fetch all tickers at once (most efficient)
                tickers = await exchange.fetch_tickers(symbols)
                self._tickers_cache = tickers
            else:
                self._tickers_cache = {}
        except Exception as e:
            self._logger.debug(f"Failed to fetch tickers: {e}")
            self._tickers_cache = {}
    
    def _get_price_from_ticker(self, symbol: str) -> Optional[float]:
        """Get mark price from cached ticker data."""
        ticker = self._tickers_cache.get(symbol, {})
        # Try different price fields
        return (
            ticker.get("last") or 
            ticker.get("close") or 
            ticker.get("mark") or
            ticker.get("info", {}).get("markPrice") or
            ticker.get("info", {}).get("lastPrice")
        )
    
    def _parse_funding_rate(self, data: dict, symbol: str) -> FundingRateData:
        """Parse CCXT funding rate response into FundingRateData."""
        funding_rate = data.get("fundingRate", 0) or 0
        
        # Handle next funding timestamp - try multiple fields
        next_funding_time = None
        
        # Try fundingTimestamp first (most common)
        funding_ts = data.get("fundingTimestamp") or data.get("nextFundingTimestamp")
        if funding_ts:
            try:
                next_funding_time = datetime.utcfromtimestamp(funding_ts / 1000)
            except (ValueError, TypeError):
                pass
        
        # Try fundingDatetime if timestamp not available
        if next_funding_time is None:
            funding_dt = data.get("fundingDatetime") or data.get("nextFundingDatetime")
            if funding_dt:
                try:
                    if isinstance(funding_dt, str):
                        # Try parsing ISO format
                        next_funding_time = datetime.fromisoformat(
                            funding_dt.replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                    elif isinstance(funding_dt, datetime):
                        next_funding_time = funding_dt
                except (ValueError, TypeError):
                    pass
        
        # Try info dict for exchange-specific fields
        if next_funding_time is None and data.get("info"):
            info = data["info"]
            for key in ["nextFundingTime", "next_funding_time", "fundingTime", 
                       "nextFundTime", "nextSettleTime", "next_funding_datetime"]:
                if info.get(key):
                    try:
                        ts = info[key]
                        if isinstance(ts, (int, float)):
                            # Timestamp - check if seconds or milliseconds
                            if ts > 10000000000:  # milliseconds
                                next_funding_time = datetime.utcfromtimestamp(ts / 1000)
                            else:  # seconds
                                next_funding_time = datetime.utcfromtimestamp(ts)
                        elif isinstance(ts, str):
                            next_funding_time = datetime.fromisoformat(
                                ts.replace("Z", "+00:00")
                            ).replace(tzinfo=None)
                        if next_funding_time:
                            break
                    except (ValueError, TypeError):
                        continue
        
        # Get prices - try from funding data first, then from ticker cache
        mark_price = data.get("markPrice")
        index_price = data.get("indexPrice")
        
        if mark_price is None:
            mark_price = self._get_price_from_ticker(symbol)
        
        # Try to get interval from exchange data or use default
        interval_hours = 8
        if data.get("info"):
            info = data["info"]
            # Try to get funding interval
            for key in ["fundingInterval", "funding_interval", "settleCycle"]:
                if info.get(key):
                    try:
                        interval = int(info[key])
                        # Convert to hours if in seconds
                        if interval > 100:  # seconds
                            interval_hours = interval // 3600
                        else:  # already hours
                            interval_hours = interval
                        break
                    except (ValueError, TypeError):
                        pass
        
        # If no funding time found, calculate based on standard schedule
        if next_funding_time is None:
            next_funding_time = calculate_next_funding_time(interval_hours)
        
        return FundingRateData(
            symbol=symbol,
            exchange=self.name,
            funding_rate=funding_rate,
            funding_rate_percent=funding_rate * 100,
            next_funding_time=next_funding_time,
            previous_funding_rate=data.get("previousFundingRate"),
            mark_price=mark_price,
            index_price=index_price,
            interval_hours=interval_hours,
        )
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Fetch all funding rates from the exchange."""
        exchange = await self._get_exchange()
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Load markets
            await exchange.load_markets()
            
            # Get all perpetual swap markets (linear USDT perpetuals preferred)
            swap_markets = []
            for symbol, market in exchange.markets.items():
                is_swap = market.get("swap") or market.get("type") == "swap"
                is_linear = market.get("linear", True)  # Prefer linear (USDT-margined)
                is_active = market.get("active", True)
                
                if is_swap and is_linear and is_active:
                    swap_markets.append(symbol)
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(swap_markets)} perpetual markets"
            )
            
            if not swap_markets:
                self._logger.warning(
                    f"[bold yellow]{self.display_name}[/]: No perpetual markets found"
                )
                return result
            
            # Fetch tickers for price data if needed
            if self.fetch_prices_separately and swap_markets:
                await self._fetch_tickers_for_prices(exchange, swap_markets[:200])
            
            # Try to use batch fetch if available (most efficient)
            if exchange.has.get("fetchFundingRates"):
                try:
                    rates_data = await exchange.fetch_funding_rates()
                    
                    # If we don't have price data from funding rates, fetch tickers
                    if rates_data and not self._tickers_cache:
                        sample = list(rates_data.values())[0] if rates_data else {}
                        if sample.get("markPrice") is None:
                            await self._fetch_tickers_for_prices(exchange, list(rates_data.keys())[:200])
                    
                    for symbol, data in rates_data.items():
                        try:
                            rate = self._parse_funding_rate(data, symbol)
                            result.rates.append(rate)
                        except Exception as e:
                            self._logger.debug(f"Failed to parse {symbol}: {e}")
                    
                    self._logger.info(
                        f"[bold green]{self.display_name}[/]: "
                        f"Fetched {len(result.rates)} funding rates (batch)"
                    )
                    return result
                except Exception as e:
                    self._logger.warning(
                        f"{self.display_name}: Batch fetch failed, trying individual: {e}"
                    )
            
            # Fallback to individual fetches if batch not available
            if exchange.has.get("fetchFundingRate"):
                # Fetch tickers first if not already done
                if not self._tickers_cache:
                    await self._fetch_tickers_for_prices(exchange, swap_markets[:200])
                
                # Limit concurrent requests to avoid rate limits
                semaphore = asyncio.Semaphore(5)
                
                async def fetch_single(symbol: str):
                    async with semaphore:
                        try:
                            data = await exchange.fetch_funding_rate(symbol)
                            return self._parse_funding_rate(data, symbol)
                        except Exception as e:
                            self._logger.debug(f"Failed to fetch {symbol}: {e}")
                            return None
                
                # Limit to first 100 to avoid timeouts
                tasks = [fetch_single(symbol) for symbol in swap_markets[:100]]
                rates = await asyncio.gather(*tasks)
                result.rates = [r for r in rates if r is not None]
                
                self._logger.info(
                    f"[bold green]{self.display_name}[/]: "
                    f"Fetched {len(result.rates)} funding rates (individual)"
                )
            else:
                result.error = f"{self.display_name} does not support funding rate fetching"
                self._logger.error(result.error)
                
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            # Always close connection to avoid resource leaks
            await self.close()
        
        return result
    
    async def fetch_funding_rate(self, symbol: str) -> Optional[ExchangeFundingRates]:
        """Fetch funding rate for a specific symbol."""
        exchange = await self._get_exchange()
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            await exchange.load_markets()
            
            if not exchange.has.get("fetchFundingRate"):
                result.error = f"{self.display_name} does not support fetchFundingRate"
                return result
            
            data = await exchange.fetch_funding_rate(symbol)
            
            # Fetch ticker if no price
            if data.get("markPrice") is None:
                try:
                    ticker = await exchange.fetch_ticker(symbol)
                    self._tickers_cache[symbol] = ticker
                except Exception:
                    pass
            
            rate = self._parse_funding_rate(data, symbol)
            result.rates.append(rate)
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error fetching {symbol} - {e}")
        finally:
            await self.close()
        
        return result


# ============================================================================
# Specific Exchange Implementations
# ============================================================================


class BybitExchange(CCXTExchange):
    """Bybit exchange connector."""
    
    ccxt_class = ccxt.bybit
    name = "bybit"
    display_name = "Bybit"
    default_options = {
        "defaultType": "linear",
        "fetchMarkets": {"types": ["linear"]},  # Only load linear markets
    }
    fetch_prices_separately = True  # Bybit funding rates don't include prices
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """
        Bybit-specific implementation.
        Uses fetchFundingRate per symbol since fetchFundingRates doesn't work for linear.
        """
        exchange = await self._get_exchange()
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            await exchange.load_markets()
            
            # Get linear swap markets
            swap_markets = [
                symbol for symbol, market in exchange.markets.items()
                if market.get("swap") and market.get("linear") and market.get("active", True)
            ]
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(swap_markets)} perpetual markets"
            )
            
            if not swap_markets:
                return result
            
            # Fetch all tickers at once for prices
            await self._fetch_tickers_for_prices(exchange, swap_markets[:300])
            
            # Use fetchFundingRate for each symbol (batch doesn't work for linear)
            semaphore = asyncio.Semaphore(10)
            
            async def fetch_single(symbol: str):
                async with semaphore:
                    try:
                        data = await exchange.fetch_funding_rate(symbol)
                        return self._parse_funding_rate(data, symbol)
                    except Exception as e:
                        self._logger.debug(f"Failed to fetch {symbol}: {e}")
                        return None
            
            # Fetch more symbols for Bybit
            tasks = [fetch_single(symbol) for symbol in swap_markets[:150]]
            rates = await asyncio.gather(*tasks)
            result.rates = [r for r in rates if r is not None]
            
            self._logger.info(
                f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates"
            )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result


class GateExchange(CCXTExchange):
    """Gate.io exchange connector."""
    
    ccxt_class = ccxt.gate  # Use 'gate' class (alias that may work better)
    name = "gate"
    display_name = "Gate.io"
    default_options = {
        "defaultType": "swap",
        "defaultSettle": "usdt",
    }
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Gate.io-specific implementation."""
        exchange = await self._get_exchange()
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            # Set type before loading markets
            exchange.options["defaultType"] = "swap"
            exchange.options["defaultSettle"] = "usdt"
            
            # Load markets - may fail on spot/currencies endpoint in some regions
            try:
                await exchange.load_markets()
            except Exception as market_err:
                self._logger.warning(f"{self.display_name}: Market load issue: {market_err}")
                # Try to continue anyway if we have some markets
                if not exchange.markets:
                    raise market_err
            
            # Filter for swap markets
            swap_markets = [
                symbol for symbol, market in exchange.markets.items()
                if market.get("swap") and market.get("linear") and market.get("active", True)
            ]
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(swap_markets)} perpetual markets"
            )
            
            if not swap_markets:
                return result
            
            # Gate.io supports fetchFundingRates for swap markets
            if exchange.has.get("fetchFundingRates"):
                # Fetch funding rates for swap markets
                rates_data = await exchange.fetch_funding_rates(swap_markets)
                
                # Fetch tickers for prices if needed
                if rates_data:
                    sample = list(rates_data.values())[0] if rates_data else {}
                    if sample.get("markPrice") is None:
                        await self._fetch_tickers_for_prices(exchange, list(rates_data.keys())[:200])
                
                for symbol, data in rates_data.items():
                    try:
                        rate = self._parse_funding_rate(data, symbol)
                        result.rates.append(rate)
                    except Exception as e:
                        self._logger.debug(f"Failed to parse {symbol}: {e}")
                
                self._logger.info(
                    f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates (batch)"
                )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result


class MexcExchange(CCXTExchange):
    """MEXC exchange connector."""
    
    ccxt_class = ccxt.mexc
    name = "mexc"
    display_name = "MEXC"
    default_options = {
        "defaultType": "swap",
        "fetchMarkets": {"types": ["swap"]},
    }
    fetch_prices_separately = True


class OKXExchange(CCXTExchange):
    """OKX exchange connector."""
    
    ccxt_class = ccxt.okx
    name = "okx"
    display_name = "OKX"
    default_options = {
        "defaultType": "swap",
    }
    fetch_prices_separately = True  # OKX funding rates often don't include prices


class BitgetExchange(CCXTExchange):
    """Bitget exchange connector."""
    
    ccxt_class = ccxt.bitget
    name = "bitget"
    display_name = "Bitget"
    default_options = {
        "defaultType": "swap",
        "defaultSubType": "linear",
    }


class BingXExchange(CCXTExchange):
    """BingX exchange connector."""
    
    ccxt_class = ccxt.bingx
    name = "bingx"
    display_name = "BingX"
    default_options = {
        "defaultType": "swap",
    }


class BinanceExchange(CCXTExchange):
    """Binance exchange connector for USDT-M futures (perpetual swaps)."""
    
    ccxt_class = ccxt.binance
    name = "binance"
    display_name = "Binance"
    default_options = {
        "defaultType": "swap",  # Perpetual swaps (USDT-M)
    }
    
    async def fetch_funding_rates(self) -> ExchangeFundingRates:
        """Binance-specific implementation for perpetual futures."""
        exchange = await self._get_exchange()
        result = ExchangeFundingRates(exchange=self.name)
        
        try:
            await exchange.load_markets()
            
            # Get perpetual swap markets (USDT-M)
            swap_markets = [
                symbol for symbol, market in exchange.markets.items()
                if market.get("swap") 
                and market.get("linear") 
                and market.get("active", True)
            ]
            
            self._logger.info(
                f"[bold blue]{self.display_name}[/]: Found {len(swap_markets)} perpetual markets"
            )
            
            if not swap_markets:
                return result
            
            # Binance supports fetchFundingRates for swaps
            if exchange.has.get("fetchFundingRates"):
                rates_data = await exchange.fetch_funding_rates(swap_markets)
                
                # Fetch tickers for prices if needed
                if rates_data:
                    sample = list(rates_data.values())[0] if rates_data else {}
                    if sample.get("markPrice") is None:
                        await self._fetch_tickers_for_prices(exchange, list(rates_data.keys())[:200])
                
                for symbol, data in rates_data.items():
                    try:
                        rate = self._parse_funding_rate(data, symbol)
                        result.rates.append(rate)
                    except Exception as e:
                        self._logger.debug(f"Failed to parse {symbol}: {e}")
                
                self._logger.info(
                    f"[bold green]{self.display_name}[/]: Fetched {len(result.rates)} funding rates (batch)"
                )
            
        except Exception as e:
            result.error = str(e)
            self._logger.error(f"[bold red]{self.display_name}[/]: Error - {e}")
        finally:
            await self.close()
        
        return result


class HibachiExchange(CCXTExchange):
    """
    Hibachi DEX connector.
    Hibachi is a decentralized perpetual exchange supported by CCXT.
    See: https://docs.ccxt.com/exchanges/hibachi
    """
    
    ccxt_class = ccxt.hibachi
    name = "hibachi"
    display_name = "Hibachi"
    default_options = {
        "defaultType": "swap",
    }
