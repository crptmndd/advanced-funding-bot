# Funding Rate Arbitrage Bot

A powerful tool for collecting and analyzing funding rates across multiple cryptocurrency exchanges to find arbitrage opportunities. Built with Python using direct native API integrations for maximum data coverage.

## 🚀 Features

- **13 Supported Exchanges**: Binance, Bybit, OKX, Bitget, BingX, MEXC, Gate.io, Hyperliquid, Hibachi, Pacifica, Lighter, Backpack, Drift
- **Direct API Integration**: Uses native exchange APIs instead of CCXT for maximum data coverage
- **Arbitrage Analysis**: Finds funding rate arbitrage opportunities between exchanges
- **Volume Filtering**: Filters out illiquid markets based on 24h trading volume
- **Price Spread Analysis**: Excludes opportunities with high price differences between exchanges
- **Real-time Funding Rates**: Get current funding rates with mark prices
- **Annualized Rate Calculation**: Automatically calculates annualized funding rates
- **CLI Interface**: Easy-to-use command-line interface with rich formatting
- **Verbose Mode**: Detailed logging for debugging (`-v` flag)

## 📊 Data Coverage

| Exchange | Markets | Funding Rates | Volume Data | Prices | Max Order | API Type |
|----------|---------|---------------|-------------|--------|-----------|----------|
| Binance | 667 | 620 | ✅ | ✅ | ✅ | Direct |
| Bybit | 645 | 557 | ✅ | ✅ | ✅ | Direct |
| OKX | 257 | 257 | ✅ | ✅ | ✅ | Direct |
| Bitget | 532 | 532 | ✅ | ✅ | ✅ | Direct |
| BingX | 613 | 553 | ✅ | ✅ | ❌ | Direct |
| MEXC | 837 | 750 | ✅ | ✅ | ✅ | Direct |
| Gate.io | 601 | 601 | ✅ | ✅ | ✅ | Direct |
| Hyperliquid | 225 | 225 | ✅ | ✅ | ❌ | Direct |
| Hibachi | 14 | 14 | ❌ | ❌ | ❌ | CCXT |
| **Pacifica** | 49 | 49 | ✅ | ✅ | ✅ | Direct |
| **Lighter** | 125 | 125 | ❌ | ❌ | ❌ | Direct |
| **Backpack** | 72 | 72 | ✅ | ✅ | ✅ | Direct |
| **Drift** | 85 | 70 | ✅ | ✅ | ❌ | Direct |
| **Total** | **4722** | **4425** | **92%** | **92%** | **69%** | - |

## 📦 Installation

```bash
# Clone the repository
git clone <repository-url>
cd funding-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## 🔧 Usage

### List Available Exchanges

```bash
python -m src.main --list-exchanges
```

### Fetch All Funding Rates

```bash
python -m src.main
```

### Fetch from Specific Exchanges

```bash
# Single exchange
python -m src.main --exchanges binance

# Multiple exchanges
python -m src.main --exchanges binance bybit okx
```

### 🎯 Arbitrage Analysis (NEW!)

Find funding rate arbitrage opportunities between exchanges:

```bash
# Basic arbitrage analysis
python -m src.main --arbitrage

# Show top 20 opportunities
python -m src.main --arbitrage --top 20

# Custom filters
python -m src.main --arbitrage --min-spread 0.05 --max-price-spread 0.5 --min-volume 500000

# With verbose output
python -m src.main --arbitrage -v
```

### Arbitrage Options

| Option | Default | Description |
|--------|---------|-------------|
| `--min-spread` | 0.01% | Minimum funding spread to consider |
| `--max-price-spread` | 1.0% | Maximum price difference between exchanges |
| `--min-volume` | $100,000 | Minimum 24h trading volume |

### Verbose Mode

Enable detailed logging for debugging:

```bash
python -m src.main -v
python -m src.main --arbitrage -v
```

### Export to JSON

```bash
python -m src.main --output funding_rates.json
```

## 💰 Arbitrage Strategy

The arbitrage analyzer finds opportunities to profit from funding rate differences:

1. **Long Position** on exchange with **lower/negative** funding rate (receive funding)
2. **Short Position** on exchange with **higher/positive** funding rate (receive funding)

Example output:
```
🎯 Top Funding Rate Arbitrage Opportunities
┌──────────┬──────────────────┬──────────────────┬────────┬─────────┐
│ Symbol   │ Long (Receive)   │ Short (Receive)  │ Spread │ Annual  │
├──────────┼──────────────────┼──────────────────┼────────┼─────────┤
│ KAITO    │ gate -1.4078%    │ binance -0.1561% │ 1.25%  │ 1827.4% │
│ ICNT     │ bybit -0.6322%   │ gate +0.0012%    │ 0.63%  │ 1232.9% │
└──────────┴──────────────────┴──────────────────┴────────┴─────────┘
```

## 📁 Project Structure

```
funding-bot/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py                 # CLI entry point
│   ├── models/
│   │   ├── __init__.py
│   │   └── funding_rate.py     # Data models (FundingRateData, ArbitrageOpportunity)
│   ├── services/
│   │   ├── __init__.py
│   │   └── arbitrage_analyzer.py  # Arbitrage analysis service
│   ├── exchanges/
│   │   ├── __init__.py
│   │   ├── base.py             # Base exchange class
│   │   ├── registry.py         # Exchange registry
│   │   ├── ccxt_exchange.py    # CCXT-based connectors
│   │   └── direct/             # Direct API connectors
│   │       ├── __init__.py
│   │       ├── base.py         # Base direct API class
│   │       ├── binance.py      # Binance Futures API
│   │       ├── bybit.py        # Bybit V5 API
│   │       ├── okx.py          # OKX API
│   │       ├── bitget.py       # Bitget API
│   │       ├── bingx.py        # BingX API
│   │       ├── mexc.py         # MEXC Futures API
│   │       ├── gate.py         # Gate.io API
│   │       └── hyperliquid.py  # Hyperliquid DEX API
│   └── utils/
│       ├── __init__.py
│       └── logger.py           # Logging utilities
├── requirements.txt
├── .gitignore
└── README.md
```

## 🔄 Funding Rate Intervals

Different exchanges use different funding intervals:

| Exchange | Interval | Times per Day | Annualized Multiplier |
|----------|----------|---------------|----------------------|
| Binance | 8 hours | 3x | 1095x |
| Bybit | 8 hours | 3x | 1095x |
| OKX | 8 hours | 3x | 1095x |
| Bitget | 8 hours | 3x | 1095x |
| BingX | 8 hours | 3x | 1095x |
| MEXC | 8 hours | 3x | 1095x |
| Gate.io | 4-8 hours | 3-6x | 1095-2190x |
| Hyperliquid | 1 hour | 24x | 8760x |
| Hibachi | 8 hours | 3x | 1095x |

## 🛠️ Architecture

The project uses a hybrid approach:
- **Direct API connectors** for maximum data coverage (preferred)
- **CCXT as fallback** for exchanges without direct implementation

Benefits of direct API:
- More markets and funding rates
- Better price and volume data coverage
- Faster response times
- Full control over request parameters

## 📈 Future Plans

- [ ] Telegram bot interface with subscription system
- [ ] Internal EVM wallet for automated arbitrage
- [ ] Automated position opening/closing
- [ ] Historical funding rate analysis
- [ ] Real-time WebSocket updates
- [ ] Risk management and position sizing

## 📄 License

MIT License
