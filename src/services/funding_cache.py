"""
Background funding rate caching service.

Periodically fetches funding rates from all exchanges and caches them
for instant access, reducing API load and latency.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from src.models import ExchangeFundingRates, FundingRateData
from src.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class CachedRates:
    """Cached funding rates with metadata."""
    rates: List[ExchangeFundingRates]
    fetched_at: datetime
    expires_at: datetime
    
    @property
    def is_expired(self) -> bool:
        """Check if cache is expired."""
        return datetime.utcnow() > self.expires_at
    
    @property
    def age_seconds(self) -> float:
        """Get cache age in seconds."""
        return (datetime.utcnow() - self.fetched_at).total_seconds()


class FundingRateCache:
    """
    Background service for caching funding rates.
    
    Features:
    - Periodic background refresh
    - Instant access to cached data
    - TTL-based cache expiration
    - Per-exchange caching
    """
    
    def __init__(
        self,
        ttl_seconds: Optional[int] = None,
        refresh_interval: Optional[int] = None,
    ):
        """
        Initialize funding rate cache.
        
        Args:
            ttl_seconds: Cache time-to-live in seconds
            refresh_interval: Background refresh interval in seconds
        """
        config = get_config()
        
        self._ttl = ttl_seconds or config.funding.cache_ttl_seconds
        self._refresh_interval = refresh_interval or config.funding.background_refresh_interval
        
        self._cache: Optional[CachedRates] = None
        self._per_exchange_cache: Dict[str, CachedRates] = {}
        self._refresh_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()
        
        logger.info(f"[Funding Cache] Initialized (TTL: {self._ttl}s, Refresh: {self._refresh_interval}s)")
    
    async def start(self) -> None:
        """Start background refresh task."""
        if self._running:
            return
        
        self._running = True
        self._refresh_task = asyncio.create_task(self._background_refresh())
        logger.info("[Funding Cache] Background refresh started")
    
    async def stop(self) -> None:
        """Stop background refresh task."""
        self._running = False
        
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
        
        logger.info("[Funding Cache] Background refresh stopped")
    
    async def _background_refresh(self) -> None:
        """Background task to periodically refresh cache."""
        # Import here to avoid circular imports
        from src.exchanges.registry import ExchangeRegistry
        
        while self._running:
            try:
                logger.debug("[Funding Cache] Refreshing cache...")
                
                # Fetch all rates using cached exchange instances
                rates = await ExchangeRegistry.fetch_all_funding_rates(
                    use_cache=True,
                    auto_close=False,  # Keep sessions alive for reuse
                )
                
                # Update cache
                async with self._lock:
                    now = datetime.utcnow()
                    self._cache = CachedRates(
                        rates=rates,
                        fetched_at=now,
                        expires_at=now + timedelta(seconds=self._ttl),
                    )
                    
                    # Also update per-exchange cache
                    for exchange_rates in rates:
                        self._per_exchange_cache[exchange_rates.exchange] = CachedRates(
                            rates=[exchange_rates],
                            fetched_at=now,
                            expires_at=now + timedelta(seconds=self._ttl),
                        )
                
                total_rates = sum(len(r.rates) for r in rates)
                logger.info(
                    f"[Funding Cache] Refreshed: {total_rates} rates from {len(rates)} exchanges"
                )
                
            except Exception as e:
                logger.error(f"[Funding Cache] Refresh error: {e}")
            
            # Wait for next refresh
            await asyncio.sleep(self._refresh_interval)
    
    async def get_all_rates(
        self,
        exchanges: Optional[List[str]] = None,
        force_refresh: bool = False,
    ) -> List[ExchangeFundingRates]:
        """
        Get cached funding rates.
        
        Args:
            exchanges: Optional list of exchanges to filter
            force_refresh: Force a fresh fetch instead of using cache
            
        Returns:
            List of ExchangeFundingRates
        """
        # Force refresh if requested or cache is empty/expired
        if force_refresh or self._cache is None or self._cache.is_expired:
            await self._refresh_now(exchanges)
        
        async with self._lock:
            if self._cache is None:
                return []
            
            rates = self._cache.rates
            
            # Filter by exchanges if specified
            if exchanges:
                exchanges_lower = [e.lower() for e in exchanges]
                rates = [r for r in rates if r.exchange.lower() in exchanges_lower]
            
            return rates
    
    async def get_exchange_rates(
        self,
        exchange: str,
        force_refresh: bool = False,
    ) -> Optional[ExchangeFundingRates]:
        """
        Get cached rates for a specific exchange.
        
        Args:
            exchange: Exchange name
            force_refresh: Force a fresh fetch
            
        Returns:
            ExchangeFundingRates or None
        """
        exchange_lower = exchange.lower()
        
        # Check per-exchange cache
        if not force_refresh and exchange_lower in self._per_exchange_cache:
            cached = self._per_exchange_cache[exchange_lower]
            if not cached.is_expired:
                return cached.rates[0] if cached.rates else None
        
        # Fall back to full cache
        all_rates = await self.get_all_rates(exchanges=[exchange], force_refresh=force_refresh)
        return all_rates[0] if all_rates else None
    
    async def _refresh_now(self, exchanges: Optional[List[str]] = None) -> None:
        """Immediately refresh cache."""
        from src.exchanges.registry import ExchangeRegistry
        
        try:
            rates = await ExchangeRegistry.fetch_all_funding_rates(
                exchanges=exchanges,
                use_cache=True,
                auto_close=False,
            )
            
            async with self._lock:
                now = datetime.utcnow()
                self._cache = CachedRates(
                    rates=rates,
                    fetched_at=now,
                    expires_at=now + timedelta(seconds=self._ttl),
                )
                
                for exchange_rates in rates:
                    self._per_exchange_cache[exchange_rates.exchange] = CachedRates(
                        rates=[exchange_rates],
                        fetched_at=now,
                        expires_at=now + timedelta(seconds=self._ttl),
                    )
        except Exception as e:
            logger.error(f"[Funding Cache] Refresh error: {e}")
    
    @property
    def is_cached(self) -> bool:
        """Check if data is cached and valid."""
        return self._cache is not None and not self._cache.is_expired
    
    @property
    def cache_age(self) -> Optional[float]:
        """Get cache age in seconds, or None if not cached."""
        if self._cache is None:
            return None
        return self._cache.age_seconds
    
    def get_cache_info(self) -> dict:
        """Get cache status information."""
        if self._cache is None:
            return {
                "cached": False,
                "age_seconds": None,
                "expires_in_seconds": None,
                "exchanges_cached": 0,
                "total_rates": 0,
            }
        
        return {
            "cached": True,
            "age_seconds": self._cache.age_seconds,
            "expires_in_seconds": max(0, (self._cache.expires_at - datetime.utcnow()).total_seconds()),
            "exchanges_cached": len(self._cache.rates),
            "total_rates": sum(len(r.rates) for r in self._cache.rates),
        }


# Global cache instance
_cache: Optional[FundingRateCache] = None


def get_funding_cache() -> FundingRateCache:
    """Get or create global funding cache instance."""
    global _cache
    if _cache is None:
        _cache = FundingRateCache()
    return _cache


async def start_funding_cache() -> FundingRateCache:
    """Start the global funding cache background task."""
    cache = get_funding_cache()
    await cache.start()
    return cache


async def stop_funding_cache() -> None:
    """Stop the global funding cache background task."""
    global _cache
    if _cache is not None:
        await _cache.stop()

