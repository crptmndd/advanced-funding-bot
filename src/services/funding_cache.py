"""
Funding Rate Cache Service.

Provides background fetching and caching of funding rates from all exchanges.
This improves response times and reduces API load.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from src.models import ExchangeFundingRates, FundingRateData
from src.exchanges.registry import ExchangeRegistry
from src.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class CachedFundingRates:
    """Cached funding rate data with metadata."""
    rates: List[ExchangeFundingRates] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int = 300  # 5 minutes default
    
    @property
    def is_expired(self) -> bool:
        """Check if cache has expired."""
        age = (datetime.utcnow() - self.fetched_at).total_seconds()
        return age > self.ttl_seconds
    
    @property
    def age_seconds(self) -> float:
        """Get cache age in seconds."""
        return (datetime.utcnow() - self.fetched_at).total_seconds()
    
    @property
    def total_rates(self) -> int:
        """Get total number of cached rates."""
        return sum(len(r.rates) for r in self.rates)
    
    @property
    def exchanges_count(self) -> int:
        """Get number of exchanges with data."""
        return len([r for r in self.rates if r.rates])


class FundingRateCache:
    """
    Manages funding rate caching with background updates.
    
    Features:
    - Background periodic fetching from all exchanges
    - TTL-based cache invalidation
    - Instant access to cached data
    - Fallback to fresh fetch if cache is empty/expired
    """
    
    def __init__(
        self,
        ttl_seconds: Optional[int] = None,
        fetch_interval: Optional[int] = None,
        enable_background: Optional[bool] = None,
    ):
        """
        Initialize the cache.
        
        Args:
            ttl_seconds: Cache TTL in seconds (default from config)
            fetch_interval: Background fetch interval in seconds
            enable_background: Whether to enable background fetching
        """
        config = get_config()
        
        self._ttl_seconds = ttl_seconds or config.exchange.funding_rate_cache_ttl
        self._fetch_interval = fetch_interval or config.exchange.background_fetch_interval
        self._enable_background = enable_background if enable_background is not None else config.exchange.enable_background_fetch
        
        self._cache: Optional[CachedFundingRates] = None
        self._background_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()
        
        # Statistics
        self._fetch_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        
        logger.info(f"[Funding Cache] Initialized (TTL={self._ttl_seconds}s, interval={self._fetch_interval}s)")
    
    async def start(self) -> None:
        """Start the background fetching task."""
        if self._running:
            return
        
        self._running = True
        
        if self._enable_background:
            # Initial fetch
            logger.info("[Funding Cache] Starting background fetch service...")
            await self._fetch_and_cache()
            
            # Start background task
            self._background_task = asyncio.create_task(self._background_fetch_loop())
            logger.info("[Funding Cache] Background fetch service started")
        else:
            logger.info("[Funding Cache] Background fetching disabled, using on-demand mode")
    
    async def stop(self) -> None:
        """Stop the background fetching task."""
        self._running = False
        
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
            self._background_task = None
        
        # Close all exchange sessions
        await ExchangeRegistry.close_all()
        
        logger.info("[Funding Cache] Stopped")
    
    async def get_rates(
        self,
        exchanges: Optional[List[str]] = None,
        force_refresh: bool = False,
    ) -> List[ExchangeFundingRates]:
        """
        Get funding rates, using cache if available.
        
        Args:
            exchanges: Optional list of exchanges to filter
            force_refresh: Force fetching fresh data
            
        Returns:
            List of ExchangeFundingRates
        """
        # Check if we need to refresh
        if force_refresh or self._cache is None or self._cache.is_expired:
            self._cache_misses += 1
            await self._fetch_and_cache()
        else:
            self._cache_hits += 1
        
        if self._cache is None:
            return []
        
        # Filter by exchanges if specified
        if exchanges:
            exchanges_lower = [e.lower() for e in exchanges]
            return [r for r in self._cache.rates if r.exchange.lower() in exchanges_lower]
        
        return self._cache.rates
    
    async def get_rate(
        self,
        symbol: str,
        exchange: Optional[str] = None,
    ) -> Optional[FundingRateData]:
        """
        Get funding rate for a specific symbol.
        
        Args:
            symbol: Symbol to look up (e.g., "BTC/USDT:USDT")
            exchange: Optional exchange to filter by
            
        Returns:
            FundingRateData or None
        """
        rates = await self.get_rates(exchanges=[exchange] if exchange else None)
        
        symbol_normalized = symbol.upper().replace("-", "/")
        
        for exchange_rates in rates:
            for rate in exchange_rates.rates:
                if rate.symbol.upper() == symbol_normalized:
                    return rate
        
        return None
    
    async def get_rates_by_symbol(self, symbol: str) -> Dict[str, FundingRateData]:
        """
        Get funding rates for a symbol across all exchanges.
        
        Args:
            symbol: Symbol to look up
            
        Returns:
            Dictionary mapping exchange name to FundingRateData
        """
        rates = await self.get_rates()
        result = {}
        
        symbol_normalized = symbol.upper().replace("-", "/")
        
        for exchange_rates in rates:
            for rate in exchange_rates.rates:
                if rate.symbol.upper() == symbol_normalized:
                    result[exchange_rates.exchange] = rate
                    break
        
        return result
    
    def get_cache_info(self) -> dict:
        """Get cache statistics and info."""
        return {
            "has_data": self._cache is not None and bool(self._cache.rates),
            "is_expired": self._cache.is_expired if self._cache else True,
            "age_seconds": self._cache.age_seconds if self._cache else None,
            "total_rates": self._cache.total_rates if self._cache else 0,
            "exchanges_count": self._cache.exchanges_count if self._cache else 0,
            "fetch_count": self._fetch_count,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_rate": self._cache_hits / max(1, self._cache_hits + self._cache_misses),
            "ttl_seconds": self._ttl_seconds,
            "background_enabled": self._enable_background,
            "is_running": self._running,
        }
    
    async def _fetch_and_cache(self) -> None:
        """Fetch funding rates from all exchanges and cache."""
        async with self._lock:
            try:
                logger.debug("[Funding Cache] Fetching funding rates from all exchanges...")
                
                rates = await ExchangeRegistry.fetch_all_funding_rates(
                    use_cache=True,  # Reuse exchange instances
                    close_sessions=False,  # Keep sessions open for next fetch
                )
                
                self._cache = CachedFundingRates(
                    rates=rates,
                    fetched_at=datetime.utcnow(),
                    ttl_seconds=self._ttl_seconds,
                )
                
                self._fetch_count += 1
                
                logger.info(
                    f"[Funding Cache] Cached {self._cache.total_rates} rates "
                    f"from {self._cache.exchanges_count} exchanges"
                )
                
            except Exception as e:
                logger.error(f"[Funding Cache] Error fetching rates: {e}")
    
    async def _background_fetch_loop(self) -> None:
        """Background loop for periodic fetching."""
        while self._running:
            try:
                await asyncio.sleep(self._fetch_interval)
                
                if not self._running:
                    break
                
                await self._fetch_and_cache()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Funding Cache] Background fetch error: {e}")
                await asyncio.sleep(30)  # Wait before retry


# =====================================================================
# Global instance
# =====================================================================

_cache: Optional[FundingRateCache] = None


def get_funding_cache() -> FundingRateCache:
    """Get or create global funding cache instance."""
    global _cache
    if _cache is None:
        _cache = FundingRateCache()
    return _cache


async def start_funding_cache() -> FundingRateCache:
    """Start the funding cache service."""
    cache = get_funding_cache()
    await cache.start()
    return cache


async def stop_funding_cache() -> None:
    """Stop the funding cache service."""
    global _cache
    if _cache is not None:
        await _cache.stop()
        _cache = None

