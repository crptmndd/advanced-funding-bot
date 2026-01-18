"""Hyperliquid exchange connector using CCXT."""

import ccxt.async_support as ccxt

from src.exchanges.ccxt_exchange import CCXTExchange


class HyperliquidExchange(CCXTExchange):
    """
    Hyperliquid DEX connector.
    
    Hyperliquid is a decentralized perpetual exchange that supports
    funding rates. It's supported by CCXT library.
    """
    
    ccxt_class = ccxt.hyperliquid
    name = "hyperliquid"
    display_name = "Hyperliquid"
    default_options = {"defaultType": "swap"}

