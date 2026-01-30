-- Trading System Database Schema
-- SQLite with async access via aiosqlite

-- Enable foreign key support
PRAGMA foreign_keys = ON;

-- ============================================================
-- SYMBOLS
-- ============================================================
-- Registered trading pairs for price fetching and trading

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,           -- CCXT format: "BTC/USDT"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,           -- Soft delete support
    last_price REAL,                       -- Most recent price (optional cache)
    last_price_at TIMESTAMP                -- When last price was fetched
);

CREATE INDEX IF NOT EXISTS idx_symbols_active ON symbols(is_active);
CREATE INDEX IF NOT EXISTS idx_symbols_symbol ON symbols(symbol);

-- ============================================================
-- PRICE DATA (OHLCV)
-- ============================================================
-- Minute-level candle data from Binance

CREATE TABLE IF NOT EXISTS price_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL,
    timestamp INTEGER NOT NULL,            -- Unix timestamp in milliseconds, rounded to minute
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (symbol_id) REFERENCES symbols(id) ON DELETE CASCADE,
    UNIQUE(symbol_id, timestamp)           -- Prevent duplicate candles
);

-- Primary query pattern: get price range for symbol
CREATE INDEX IF NOT EXISTS idx_price_data_symbol_time 
    ON price_data(symbol_id, timestamp);

-- For getting latest price quickly
CREATE INDEX IF NOT EXISTS idx_price_data_symbol_time_desc 
    ON price_data(symbol_id, timestamp DESC);

-- ============================================================
-- STRATEGIES (Future Use)
-- ============================================================
-- Trading strategy configurations

CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,             -- Strategy identifier
    symbol_id INTEGER NOT NULL,            -- Trading pair
    frequency INTEGER NOT NULL,            -- Run every N minutes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    config TEXT,                           -- JSON configuration (optional)
    
    FOREIGN KEY (symbol_id) REFERENCES symbols(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_strategies_active ON strategies(is_active);
CREATE INDEX IF NOT EXISTS idx_strategies_symbol ON strategies(symbol_id);

-- ============================================================
-- STRATEGY STATES (Future Use)
-- ============================================================
-- Current position and state for each strategy

CREATE TABLE IF NOT EXISTS strategy_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL UNIQUE,
    position REAL DEFAULT 0.0,             -- Current position (0.0 to 1.0)
    base_amount REAL DEFAULT 0.0,          -- Amount of base currency held
    quote_amount REAL DEFAULT 0.0,         -- Amount of quote currency allocated
    last_run_at TIMESTAMP,                 -- Last time strategy was executed
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_strategy_states_strategy ON strategy_states(strategy_id);

-- ============================================================
-- TRADES (Future Use)
-- ============================================================
-- Order execution records

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER,                   -- NULL for manual trades
    symbol_id INTEGER NOT NULL,
    order_id TEXT,                         -- Exchange order ID
    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
    order_type TEXT NOT NULL CHECK(order_type IN ('market', 'limit')),
    amount REAL NOT NULL,                  -- Amount in base currency
    price REAL,                            -- Execution price (NULL for market orders until filled)
    cost REAL,                             -- Total cost in quote currency
    status TEXT NOT NULL CHECK(status IN ('pending', 'filled', 'partial', 'canceled', 'failed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filled_at TIMESTAMP,                   -- When order was completely filled
    error_message TEXT,                    -- If status is 'failed'
    
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE SET NULL,
    FOREIGN KEY (symbol_id) REFERENCES symbols(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol_id);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at);

-- ============================================================
-- WALLET SNAPSHOTS (Future Use)
-- ============================================================
-- Exchange wallet state captured on each heartbeat

CREATE TABLE IF NOT EXISTS wallet_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,            -- Unix timestamp in milliseconds
    total_value_usd REAL,                  -- Estimated total value (optional)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wallet_snapshots_time ON wallet_snapshots(timestamp);

-- Wallet balance details (one row per currency per snapshot)
CREATE TABLE IF NOT EXISTS wallet_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    currency TEXT NOT NULL,
    total REAL NOT NULL,
    free REAL NOT NULL,
    used REAL NOT NULL DEFAULT 0.0,
    
    FOREIGN KEY (snapshot_id) REFERENCES wallet_snapshots(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wallet_balances_snapshot ON wallet_balances(snapshot_id);

-- ============================================================
-- SYSTEM METADATA
-- ============================================================
-- For tracking system state, migrations, etc.

CREATE TABLE IF NOT EXISTS system_metadata (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Initialize schema version
INSERT OR REPLACE INTO system_metadata (key, value) VALUES ('schema_version', '1');
