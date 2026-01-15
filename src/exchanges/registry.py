"""Exchange registry for managing available exchange connectors."""

from typing import Dict, List, Optional, Type

from src.exchanges.base import BaseExchange

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


# Convenience functions
def get_exchange(name: str, **kwargs) -> Optional[BaseExchange]:
    """Get exchange instance by name."""
    return ExchangeRegistry.get_exchange(name, **kwargs)


def get_all_exchanges(only_available: bool = True) -> Dict[str, BaseExchange]:
    """Get all registered exchange instances."""
    return ExchangeRegistry.get_all_exchanges(only_available=only_available)
