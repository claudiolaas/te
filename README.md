# Trading System

An async trading system with a minute-based heartbeat that fetches price data from Binance, stores it in SQLite, and provides a foundation for future strategy execution.

## Features

- **Heartbeat Engine**: Runs every 60 seconds, 5 seconds after the minute closes (5s buffer) to fetch prices
- **Price Data Storage**: SQLite database with OHLCV candle data
- **Symbol Management**: Programmatic API for registering symbols with backfill support (REST API planned - see [backlog.md](backlog.md))
- **Retry Configuration**: Exponential backoff retry policy configured for Binance API calls
- **Per-Component Logging**: Separate log files for heartbeat, API, Binance client, and strategies

## Prerequisites

- Python 3.11+
- Binance API key (get from [Binance API Management](https://www.binance.com/en/my/settings/api-management))

## Setup

1. **Clone the repository**:
   ```bash
   git clone <repo-url>
   cd trading-system
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your Binance API credentials
   ```

   The `data/` and `logs/` directories will be created automatically on first run.

## Running the System

> ⚠️ **Note**: The main entry point is currently under development (see [backlog.md](backlog.md) TASK-17).
> 
> To run the system components programmatically:

```python
import asyncio
from trading_system import create_trading_system

async def main():
    system = await create_trading_system()
    await system.start()

if __name__ == "__main__":
    asyncio.run(main())
```

## Usage

### Registering a Symbol

```python
from trading_system.database import DatabaseManager
from trading_system.repositories import SymbolRepository
from trading_system.services import BackfillService

async with DatabaseManager() as db:
    symbol_repo = SymbolRepository(db)
    
    # Register a new symbol
    symbol = await symbol_repo.register("BTC/USDT")
    
    # Trigger backfill manually
    backfill = BackfillService(db)
    await backfill.backfill_symbol("BTC/USDT", minutes=60)
```

## Development

### Running Tests

```bash
pytest
```

With coverage:
```bash
pytest --cov=trading_system --cov-report=html
```

### Code Quality

```bash
# Linting
ruff check .
ruff check . --fix

# Type checking
mypy trading_system
```

## Architecture

See [planning.md](planning.md) and [backlog.md](backlog.md) for detailed specifications and roadmap.

## License

MIT
