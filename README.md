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
- **Telegram Bot**: Interactive bot for funding rates and arbitrage analysis
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
| Hibachi | 14 | 14 | ✅ | ✅ | ❌ | CCXT |
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

## 🤖 Telegram Bot

Run the interactive Telegram bot to get funding rates and arbitrage opportunities directly in Telegram.

### Setup

1. **Get Bot Token from @BotFather:**
   - Open Telegram and search for `@BotFather`
   - Send `/newbot` command
   - Follow instructions to create your bot
   - Copy the bot token

2. **Set Token:**
   ```bash
   # Option 1: Environment variable
   export TELEGRAM_BOT_TOKEN=your_token_here
   
   # Option 2: Create .env file
   echo "TELEGRAM_BOT_TOKEN=your_token_here" > .env
   ```

3. **Run the Bot:**
   ```bash
   python -m src.bot_main
   
   # Or with token as argument
   python -m src.bot_main YOUR_BOT_TOKEN
   ```

### Bot Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Welcome message | `/start` |
| `/help` | Show all commands | `/help` |
| `/rates` | Get funding rates | `/rates`, `/rates binance`, `/rates 20` |
| `/arbitrage` | Find arbitrage opportunities | `/arbitrage`, `/arbitrage 15` |
| `/exchanges` | List available exchanges | `/exchanges` |

### Examples

```
/rates              # All exchanges, top 10
/rates binance      # Only Binance
/rates binance 20   # Binance, top 20
/rates binance bybit okx  # Multiple exchanges

/arbitrage          # Find opportunities, top 10
/arbitrage 20       # Find opportunities, top 20
```

### Bot Features

- 📊 **Funding Rates**: View top positive/negative rates
- 💰 **Arbitrage**: Find spread opportunities between exchanges
- 📈 **Mark Price & Volume**: See prices and 24h volumes
- 🎯 **Max Order Limits**: Know position size limits
- ⏰ **Next Funding Time**: Countdown to next funding
- 💳 **Auto Wallets**: EVM + Solana wallets created automatically
- ⚙️ **Custom Settings**: Configure trade amounts and filters

### Wallet & Settings Commands

| Command | Description |
|---------|-------------|
| `/wallet` | View your EVM & Solana wallet addresses |
| `/settings` | View your trading settings |
| `/set amount 500` | Set trade amount to $500 USDT |
| `/set leverage 20` | Set max leverage to 20x |
| `/set spread 0.05` | Set minimum funding spread |
| `/set volume 50000` | Set minimum 24h volume filter |

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
│   ├── bot_main.py             # Telegram bot entry point
│   ├── bot/                    # Telegram bot module
│   │   ├── __init__.py
│   │   ├── bot.py              # Bot handlers and logic
│   │   └── formatters.py       # Message formatting
│   ├── database/               # Database & wallet management
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite database service
│   │   ├── models.py           # User, Wallet, Settings models
│   │   ├── encryption.py       # Private key encryption
│   │   └── wallet_generator.py # EVM & Solana wallet generation
│   ├── models/
│   │   └── funding_rate.py     # Funding rate data models
│   ├── services/
│   │   └── arbitrage_analyzer.py  # Arbitrage analysis
│   ├── exchanges/
│   │   ├── base.py             # Base exchange class
│   │   ├── registry.py         # Exchange registry
│   │   ├── ccxt_exchange.py    # CCXT-based connectors
│   │   └── direct/             # Direct API connectors (13 exchanges)
│   └── utils/
│       └── logger.py           # Logging utilities
├── data/
│   └── funding_bot.db          # SQLite database (auto-created)
├── requirements.txt
└── README.md
```

## 💾 Database

The bot uses SQLite to store user data:

- **Users**: Telegram ID, subscription status, timestamps
- **Wallets**: Auto-generated EVM & Solana wallets (encrypted private keys)
- **Settings**: Trade amounts, leverage, filters per user

### Security

Private keys are encrypted using Fernet (AES-128-CBC) with PBKDF2 key derivation.

Set secure encryption in production:
```bash
# Generate encryption key
python -c "from src.database.encryption import generate_encryption_key; print(generate_encryption_key())"

# Set in environment
export WALLET_ENCRYPTION_KEY=your_generated_key
export MASTER_PASSWORD=your_secure_password
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

- [x] ~~Telegram bot interface~~ ✅ Implemented!
- [x] ~~Internal EVM & Solana wallets~~ ✅ Implemented!
- [x] ~~User settings for trade amounts~~ ✅ Implemented!
- [ ] Subscription system for premium features
- [ ] Automated position opening/closing
- [ ] Historical funding rate analysis
- [ ] Real-time WebSocket updates
- [ ] Risk management and position sizing

## 📄 License

MIT License
