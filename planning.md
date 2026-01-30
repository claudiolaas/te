

Core driver of the system is a "heartbeat" that beats every minute+5seconds. The 5-second delay is a buffer to ensure minute candles are closed on Binance before fetching.

On every beat:
    - fetch current close price for all registered symbols from binance.
    - fetch sub-wallet snapshots for all registered strategies.
    - fetch exchange wallet snapshot.
    - for all registered strategies, check if the current beat matches the frequency of the strategy. If so, trigger the run() method of the strategy


# Register new symbol/currency pair
This mean we want to fetch data for this symbol. If a new symbol gets registered we perform a backfill operation on the database.
Example: 
New symbol gets registered at HH:MM:SS, .env specifies a backfill of 5 then the following entries should be created:
HH:MM-4:00
HH:MM-3:00
HH:MM-2:00
HH:MM-1:00
HH:MM:00
On the next beat of the system we would start fetching continously at HH:MM+1:00

Backfill data is fetched from the Binance REST API `/klines` endpoint. If backfill fails due to network issues or rate limits, retry logic should be applied.

Registered symbols are stored in-memory initially.

# Register new strategy
A strategy is specified by name, symbol and frequency. Strategies can be registered and unregistered at runtime via a REST API (details TBD). When registering a new strategy it is checked if the corresponding symbol is already registered, if not err out.
On every beat we check if we are 'at the frequency' of the strategy via epoch time(rounded to minute) and modulo operation, ie for a strategy with a frequency of 60 (minutes), every 60th beat would trigger the  run() method of the strategy. 

# The run() method of the strategy
This method is roughly described as 'historical data -> trading position'. The method takes no parameters and handles everything internally. It returns the predicted position (0 = all cash, 1 = fully invested) to a central executor that handles order placement.

Simple strategy example:
Increase position by 0.1 evertime the slope of the last 10 prices is positive.
The run method then would do the following:
- fetch historical minute data
- downsample according to the strategies frequency
- calculate the slope over the last 10 prices
- determine target position (0-1)
- return position signal to central executor

The strategies state (current position, base and quote amounts) are captured in the database. Unrealized PnL is not stored.

If a strategy throws an exception, it is logged and skipped. A crashing strategy should not crash the heartbeat as they are decoupled.

# Trading & Execution
There is no paper trading mode - only live trading with small amounts. Strategies return signals to a central executor rather than making direct Binance API calls.

Binance API keys are managed via environment variables in a `.env` file.

# Subwallets
See new section #Subwallets (to be documented).

# Restart
See new section #Restart (to be documented).

# Error Handling & Reliability
If the Binance API is unreachable on a heartbeat, retry with exponential backoff should be applied.

# Logging & Monitoring
Logging is per-strategy. Basic logging to begin with - no health checks, metrics, or alerting needed for MVP.

# General
- sqlite as a database
- python asyncio for Queing messages
- MVP scope: just heartbeat and price fetching (no strategy execution yet)
- Binance only for now (single exchange support)


# TBD

Questions deferred for later discussion:

## Architecture & Data Flow
- **Q2: Strategy execution**: Are strategies run sequentially or in parallel? What happens if a strategy's `run()` method takes longer than the heartbeat interval? - TBD
- **Q3: Database schema**: What tables/entities do you envision? (symbols, price_data, strategies, trades, wallet_snapshots, etc.) - TBD

## Error Handling & Reliability
- **Q17: Duplicate runs**: How do you prevent a strategy from running twice on the same minute if the system restarts mid-beat? - TBD (edge case)

## Configuration & Operations
- **Q18: Registration mechanism**: REST API details TBD
