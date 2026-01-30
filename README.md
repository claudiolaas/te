# Trading System

An async trading system with a minute-based heartbeat that fetches price data from Binance, stores it in SQLite, and provides a foundation for future strategy execution.

## Features

- **Heartbeat Engine**: Runs every 60 seconds, 5 seconds after the minute closes (5s buffer) to fetch prices
- **Price Data Storage**: SQLite database with OHLCV candle data
- **Symbol Management**: REST API for registering symbols with automatic backfill
- **Resilient API Client**: Exponential backoff retry logic for Binance API
- **Per-Strategy Logging**: Structured logging for system observability

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

5. **Create required directories**:
   ```bash
   mkdir -p data logs
   ```

## Running the System

```bash
python -m trading_system.main
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

See [planning.md](planning.md) and [backlog.md](backlog.md) for detailed specifications.

## License

MIT
