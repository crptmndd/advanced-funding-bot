"""Exchange registry for managing available exchange connectors."""

import asyncio
import logging
from typing import Dict, List, Optional, Type

from src.exchanges.base import BaseExchange
from src.models import ExchangeFundingRates
from src.config import get_config

logger = logging.getLogger(__name__)

# Direct API exchanges (native API, maximum data)
from src.exchanges.direct import (
    BinanceDirectExchange,
    BybitDirectExchange,
    OKXDirectExchange,
    BitgetDirectExchange,
    BingXDirectExchange,
    MEXCDirectExchange,
    HyperliquidDirectExchange,
    GateDirectExchange,
    PacificaDirectExchange,
    LighterDirectExchange,
    BackpackDirectExchange,
    DriftDirectExchange,
)

# CCXT-based exchanges (for exchanges without direct API implementation)
from src.exchanges.ccxt_exchange import HibachiExchange


class ExchangeRegistry:
    """
    Registry of all available exchange connectors.
    
    Provides centralized access to exchange classes and instances.
    
    Uses direct API implementations where available for maximum
    data coverage, with CCXT as fallback for other exchanges.
    """
    
    # All registered exchange classes
    # Direct API implementations (native APIs - more data)
    _exchanges: Dict[str, Type[BaseExchange]] = {
        "binance": BinanceDirectExchange,
        "bybit": BybitDirectExchange,
        "okx": OKXDirectExchange,
        "bitget": BitgetDirectExchange,
        "bingx": BingXDirectExchange,
        "mexc": MEXCDirectExchange,
        "gate": GateDirectExchange,
        "hyperliquid": HyperliquidDirectExchange,
        "pacifica": PacificaDirectExchange,
        "lighter": LighterDirectExchange,
        "backpack": BackpackDirectExchange,
        "drift": DriftDirectExchange,
        # CCXT-based (no direct API implementation yet)
        "hibachi": HibachiExchange,
    }
    
    # Exchange instances cache
    _instances: Dict[str, BaseExchange] = {}
    
    @classmethod
    def get_exchange_class(cls, name: str) -> Optional[Type[BaseExchange]]:
        """Get exchange class by name."""
        return cls._exchanges.get(name.lower())
    
    @classmethod
    def get_exchange(
        cls,
        name: str,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        use_cache: bool = False,
        **kwargs,
    ) -> Optional[BaseExchange]:
        """
        Get or create exchange instance by name.
        
        Args:
            name: Exchange name (e.g., 'bybit', 'okx')
            api_key: Optional API key
            secret: Optional API secret
            use_cache: Whether to use cached instance
            **kwargs: Additional exchange-specific parameters
            
        Returns:
            Exchange instance or None if not found
        """
        name = name.lower()
        
        # Return cached instance if requested and exists
        cache_key = f"{name}:{api_key or 'public'}"
        if use_cache and cache_key in cls._instances:
            return cls._instances[cache_key]
        
        exchange_class = cls._exchanges.get(name)
        if exchange_class is None:
            return None
        
        instance = exchange_class(api_key=api_key, secret=secret, **kwargs)
        if use_cache:
            cls._instances[cache_key] = instance
        return instance
    
    @classmethod
    def get_all_names(cls) -> List[str]:
        """Get list of all registered exchange names."""
        return list(cls._exchanges.keys())
    
    @classmethod
    def get_available_names(cls) -> List[str]:
        """Get list of exchange names that are currently available (have working API)."""
        available = []
        for name, exchange_class in cls._exchanges.items():
            instance = exchange_class()
            if instance.is_available:
                available.append(name)
        return available
    
    @classmethod
    def get_all_exchanges(
        cls,
        only_available: bool = True,
    ) -> Dict[str, BaseExchange]:
        """
        Get instances of all registered exchanges.
        
        Args:
            only_available: If True, only return exchanges with working API
            
        Returns:
            Dictionary mapping exchange names to instances
        """
        exchanges = {}
        for name, exchange_class in cls._exchanges.items():
            instance = cls.get_exchange(name)
            if instance:
                if only_available and not instance.is_available:
                    continue
                exchanges[name] = instance
        return exchanges
    
    @classmethod
    def register(cls, name: str, exchange_class: Type[BaseExchange]) -> None:
        """
        Register a new exchange class.
        
        Args:
            name: Exchange name
            exchange_class: Exchange class to register
        """
        cls._exchanges[name.lower()] = exchange_class
    
    @classmethod
    async def close_all(cls) -> None:
        """Close all cached exchange connections."""
        for instance in cls._instances.values():
            if hasattr(instance, 'close'):
                await instance.close()
        cls._instances.clear()
    
    @classmethod
    async def fetch_all_funding_rates(
        cls,
        exchanges: Optional[List[str]] = None,
        timeout: Optional[float] = None,
        use_cache: Optional[bool] = None,
        auto_close: Optional[bool] = None,
    ) -> List[ExchangeFundingRates]:
        """
        Fetch funding rates from all exchanges in parallel.
        
        Args:
            exchanges: Optional list of exchange names to fetch from.
                       If None, fetches from all available exchanges.
            timeout: Timeout in seconds for each exchange request.
            use_cache: Whether to use cached exchange instances (default from config).
            auto_close: Whether to close sessions after fetching (default from config).
            
        Returns:
            List of ExchangeFundingRates objects, one per exchange.
        """
        config = get_config()
        
        # Use config defaults if not specified
        if timeout is None:
            timeout = config.funding.fetch_timeout
        if use_cache is None:
            use_cache = config.exchange.use_cache
        if auto_close is None:
            auto_close = config.exchange.auto_close_sessions
        
        # Get exchange instances (using cache if enabled)
        instances_to_close = []
        
        if exchanges:
            exchange_instances = {}
            for name in exchanges:
                name_lower = name.lower()
                instance = cls.get_exchange(name_lower, use_cache=use_cache)
                if instance and instance.is_available:
                    exchange_instances[name_lower] = instance
                    if not use_cache:
                        instances_to_close.append(instance)
        else:
            exchange_instances = {}
            for name in cls._exchanges.keys():
                # Skip disabled exchanges
                if config.exchange.disabled_exchanges and name in config.exchange.disabled_exchanges:
                    continue
                # Only use enabled if specified
                if config.exchange.enabled_exchanges and name not in config.exchange.enabled_exchanges:
                    continue
                    
                instance = cls.get_exchange(name, use_cache=use_cache)
                if instance and instance.is_available:
                    exchange_instances[name] = instance
                    if not use_cache:
                        instances_to_close.append(instance)
        
        if not exchange_instances:
            logger.warning("No available exchanges to fetch funding rates from")
            return []
        
        logger.info(f"Fetching funding rates from {len(exchange_instances)} exchanges: {list(exchange_instances.keys())}")
        
        async def fetch_with_timeout(name: str, exchange: BaseExchange) -> ExchangeFundingRates:
            """Fetch funding rates with timeout and error handling."""
            try:
                result = await asyncio.wait_for(
                    exchange.fetch_funding_rates(),
                    timeout=timeout
                )
                logger.info(f"[{name}] Fetched {len(result.rates)} funding rates")
                return result
            except asyncio.TimeoutError:
                logger.warning(f"[{name}] Timeout fetching funding rates")
                return ExchangeFundingRates(
                    exchange=name,
                    rates=[],
                    error=f"Timeout after {timeout}s"
                )
            except Exception as e:
                logger.error(f"[{name}] Error fetching funding rates: {e}")
                return ExchangeFundingRates(
                    exchange=name,
                    rates=[],
                    error=str(e)
                )
        
        try:
            # Fetch from all exchanges in parallel
            tasks = [
                fetch_with_timeout(name, exchange)
                for name, exchange in exchange_instances.items()
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions and return valid results
            valid_results = []
            for result in results:
                if isinstance(result, ExchangeFundingRates):
                    valid_results.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"Unexpected exception in fetch_all_funding_rates: {result}")
            
            total_rates = sum(len(r.rates) for r in valid_results)
            logger.info(f"Fetched total of {total_rates} funding rates from {len(valid_results)} exchanges")
            
            return valid_results
        
        finally:
            # Close sessions if auto_close is enabled and not using cache
            if auto_close and instances_to_close:
                for instance in instances_to_close:
                    try:
                        if hasattr(instance, 'close'):
                            await instance.close()
                    except Exception as e:
                        logger.debug(f"Error closing exchange {instance.name}: {e}")
    
    @classmethod
    def get_available_exchanges(cls) -> List[str]:
        """Get list of available exchange names."""
        return cls.get_available_names()


# Convenience functions
def get_exchange(name: str, **kwargs) -> Optional[BaseExchange]:
    """Get exchange instance by name."""
    return ExchangeRegistry.get_exchange(name, **kwargs)


def get_all_exchanges(only_available: bool = True) -> Dict[str, BaseExchange]:
    """Get all registered exchange instances."""
    return ExchangeRegistry.get_all_exchanges(only_available=only_available)
