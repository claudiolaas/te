# Trading System Backlog

## Overview

A trading system with a minute-based heartbeat that fetches price data from Binance, stores it in SQLite, and provides a foundation for future strategy execution.

**MVP Scope**: Heartbeat + price fetching only (no strategy execution)
**Architecture**: Python asyncio, SQLite database, Binance REST API

---

## Milestone 1: Project Foundation

**Goal**: Set up the project structure, configuration, and core dependencies.

### ✅ TASK-1: Project Setup and Configuration

**Description**: Initialize Python project with dependencies (ccxt, asyncio, pytest, python-dotenv) and basic folder structure.
use uv for dependency and venv management

**Acceptance Criteria**:
- [x] `pyproject.toml` with all dependencies
- [x] `.env.example` file with documented environment variables (BINANCE_API_KEY, BINANCE_SECRET_KEY, DB_PATH, BACKFILL_MINUTES)
- [x] `.gitignore` for Python projects
- [x] `README.md` with setup instructions

**Dependencies**: None

**Complexity**: S

**Status**: ✅ Complete

---

### ✅ TASK-2: Configuration Management

**Description**: Create a config module that loads settings from environment variables with sensible defaults.

**Acceptance Criteria**:
- [x] `config.py` module with pydantic Settings class
- [x] Unit test verifies config loads from env vars
- [x] Unit test verifies default values work
- [x] Validation errors raised for missing required fields
- [x] Additional tests for range validation and derived properties

**Dependencies**: TASK-1

**Complexity**: S

---

### ✅ TASK-3: Logging Infrastructure

**Description**: Set up per-strategy logging with structured output and log rotation.

**Acceptance Criteria**:
- [x] `logger.py` module with configurable loggers
- [x] Unit test verifies logger creates separate files per component
- [x] Log format includes timestamp, level, component name, message
- [x] Log level configurable via env var
- [x] Log directory created if not exists
- [x] Singleton pattern with proper test isolation

**Dependencies**: TASK-1

**Complexity**: S

---

## Milestone 2: Database Layer

**Goal**: Design and implement the SQLite schema for storing price data and system state.

### ✅ TASK-4: Database Schema Definition

**Description**: Create SQL schema for symbols and price_data tables.

**Acceptance Criteria**:
- [x] `schema.sql` with `symbols` table (id, symbol, created_at, is_active)
- [x] `schema.sql` with `price_data` table (id, symbol_id, timestamp, open, high, low, close, volume)
- [x] Appropriate indexes on symbol_id + timestamp for fast queries
- [x] Additional tables for future use (strategies, trades, wallet_snapshots)

**Dependencies**: TASK-1

**Complexity**: S

---

### ✅ TASK-5: Database Connection Manager

**Description**: Create async database connection pool with proper lifecycle management.

**Acceptance Criteria**:
- [x] `database.py` with `DatabaseManager` class using aiosqlite
- [x] Unit test verifies connection can be opened and closed
- [x] Unit test verifies connection context manager works
- [x] Handles concurrent access safely
- [x] Helper methods: execute(), fetch_one(), fetch_all()

**Dependencies**: TASK-4

**Complexity**: S

---

### ✅ TASK-6: Symbol Repository

**Description**: Implement CRUD operations for symbol management with in-memory caching.

**Acceptance Criteria**:
- [x] `SymbolRepository` class with `register()`, `get()`, `list_active()` methods
- [x] Unit test verifies symbol registration persists to DB and cache
- [x] Unit test verifies duplicate symbol registration is handled gracefully
- [x] Unit test verifies cache is invalidated on update
- [x] Additional methods: get_by_symbol(), deactivate(), update_last_price()

**Dependencies**: TASK-5

**Complexity**: M

---

### ✅ TASK-7: Price Data Repository

**Description**: Implement storage and retrieval of OHLCV price data.

**Acceptance Criteria**:
- [x] `PriceRepository` class with `save()`, `get_range()`, `get_latest()` methods
- [x] Unit test verifies price data can be saved and retrieved
- [x] Unit test verifies `get_range()` returns correct time window
- [x] Unit test verifies `get_latest()` returns most recent price
- [x] Additional methods: save_many(), get_before(), get_after(), count(), delete_range()

**Dependencies**: TASK-5, TASK-6

**Complexity**: M

---

## Milestone 3: Binance API Integration

**Goal**: Build a resilient Binance API client with retry logic and rate limiting.

### ✅ TASK-8: Binance Client Foundation

**Description**: Create Binance API client using CCXT with authentication.

**Acceptance Criteria**:
- [x] `binance_client.py` with `BinanceClient` class
- [x] Unit test verifies client initializes with API credentials
- [x] Unit test (mocked) verifies fetch_ticker returns price data
- [x] Proper error handling for authentication failures
- [x] Additional methods: fetch_tickers(), fetch_ohlcv(), fetch_balance()
- [x] Normalized data models: TickerData, OHLCVData

**Dependencies**: TASK-2

**Complexity**: M

---

### ✅ TASK-9: Retry Logic with Exponential Backoff

**Description**: Implement retry decorator/mechanism for transient API failures.

**Acceptance Criteria**:
- [x] `retry.py` module with exponential backoff decorator
- [x] Unit test verifies retry triggers on NetworkError
- [x] Unit test verifies retry stops after max attempts
- [x] Configurable retry count and backoff multiplier
- [x] Additional: RetryableOperation class, retry_operation() function
- [x] Support for both sync and async functions

**Dependencies**: TASK-8

**Complexity**: M

---

### ✅ TASK-10: Historical Data Backfill

**Description**: Implement backfill functionality using Binance `/klines` endpoint.

**Acceptance Criteria**:
- [x] `BackfillService` class with `backfill_symbol()` method
- [x] Unit test (mocked) verifies correct number of candles fetched
- [x] Unit test verifies data is stored in correct format
- [x] Timestamp normalization to minute boundaries
- [x] Retry integration for network failures
- [x] Backfill status tracking

**Dependencies**: TASK-8, TASK-7

**Complexity**: M

---

## Milestone 4: Heartbeat Engine

**Goal**: Implement the core heartbeat scheduler that drives the system.

### ✅ TASK-11: Heartbeat Scheduler

**Description**: Create an asyncio-based scheduler that triggers every minute+5seconds.

**Acceptance Criteria**:
- [x] `scheduler.py` with `HeartbeatScheduler` class
- [x] Unit test verifies heartbeat triggers at correct intervals
- [x] Unit test verifies 65-second interval (60s + 5s buffer)
- [x] Graceful shutdown on SIGINT/SIGTERM
- [x] Aligns to minute boundaries with configurable buffer delay
- [x] Statistics tracking (beats executed, failed, uptime)

**Dependencies**: TASK-3

**Complexity**: M

---

### ✅ TASK-12: Price Fetching Service

**Description**: Service that fetches current prices for all registered symbols on each beat.

**Acceptance Criteria**:
- [x] `PriceFetcher` class with `fetch_all()` method
- [x] Unit test verifies all registered symbols are fetched
- [x] Unit test verifies prices are saved to database
- [x] Per-symbol error handling (one failure doesn't block others)
- [x] Batch ticker fetching for efficiency
- [x] Timestamp normalization to minute boundaries
- [x] `fetch_single()` method for individual symbol fetching

**Dependencies**: TASK-11, TASK-6, TASK-8, TASK-7

**Complexity**: M

---

### ✅ TASK-13: Heartbeat Coordinator

**Description**: Main coordinator that orchestrates the heartbeat cycle.

**Acceptance Criteria**:
- [x] `coordinator.py` that wires heartbeat to price fetching
- [x] Integration test verifies end-to-end heartbeat cycle
- [x] Logs each beat with timestamp and status
- [x] Handles errors gracefully without stopping heartbeat
- [x] `run_once()` method for single cycle execution
- [x] Per-beat logging with success/failure counts

**Dependencies**: TASK-11, TASK-12

**Complexity**: M

---

## Milestone 5: Symbol Management API

**Goal**: Provide REST endpoints for symbol registration and backfill triggering.

### ✅ TASK-14: REST API Server Setup

**Description**: Set up FastAPI (or similar) async web server.

**Acceptance Criteria**:
- [x] `api.py` with FastAPI app instance
- [x] Health check endpoint `/health`
- [x] Unit test verifies server starts and responds
- [x] Async startup/shutdown lifecycle hooks

**Dependencies**: TASK-1

**Complexity**: S

**Status**: ✅ Complete

---

### ✅ TASK-15: Symbol Registration Endpoint

**Description**: POST endpoint to register new symbols with automatic backfill.

**Acceptance Criteria**:
- [x] `POST /symbols` endpoint accepting `{symbol: "BTC/USDT"}`
- [x] Unit test verifies symbol is registered and backfill triggered
- [x] Returns 400 if symbol already registered
- [x] Returns 201 with backfill status on success

**Dependencies**: TASK-14, TASK-6, TASK-10

**Complexity**: M

---

### ✅ TASK-16: List Symbols Endpoint

**Description**: GET endpoint to list all registered symbols.

**Acceptance Criteria**:
- [x] `GET /symbols` endpoint
- [x] Unit test returns list of active symbols
- [x] Optional query param for active/inactive filter

**Dependencies**: TASK-14, TASK-6

**Complexity**: S

---

## Milestone 6: System Integration

**Goal**: Wire all components together into a runnable system.

### ✅ TASK-17: Application Main Entry Point

**Description**: Main application that starts heartbeat and API server concurrently.

**Acceptance Criteria**:
- [x] `main.py` that starts both heartbeat and API
- [x] Graceful shutdown handling for both components
- [x] Proper dependency injection of services
- [x] Integration test verifies full startup/shutdown

**Dependencies**: TASK-13, TASK-14

**Complexity**: M

---

### ✅ TASK-18: End-to-End Testing

**Description**: Full system test with mocked Binance API.

**Acceptance Criteria**:
- [x] Register a symbol via API
- [x] Verify backfill creates historical records
- [x] Verify heartbeat fetches and stores new prices
- [x] Verify logs are written per-component

**Dependencies**: TASK-17

**Complexity**: L

---

## Bonus Features (Post-MVP)

### ✅ TASK-19: Price Chart Visualization

**Description**: Interactive Plotly HTML chart for viewing historical price data.

**Acceptance Criteria**:
- [x] `GET /plot/prices` endpoint returns interactive HTML chart
- [x] Shows all symbols on log-scale Y-axis
- [x] Multiple line charts with different start times
- [x] Unit tests for chart generation

**Status**: ✅ Complete

---

## Future (Post-MVP)

Items from TBD section and beyond MVP scope:

### Research Tasks

- **SPIKE-1**: Strategy execution model (sequential vs parallel, timeout handling)
- **SPIKE-2**: Sub-wallet design and implementation
- **SPIKE-3**: Restart handling and duplicate run prevention
- **SPIKE-4**: REST API authentication and rate limiting

### Strategy Execution (MVP+1)

- Strategy registry and runtime registration
- Strategy interface and base class
- Position tracking in database
- Central order executor
- Wallet snapshot service

---

## Task Summary

| Milestone | Tasks | Total Complexity |
|-----------|-------|------------------|
| 1: Foundation | 3 | S (3) |
| 2: Database | 4 | S (1) + M (3) |
| 3: Binance API | 3 | M (3) |
| 4: Heartbeat | 3 | M (3) |
| 5: REST API | 3 | S (2) + M (1) |
| 6: Integration | 2 | M (1) + L (1) |
| **Total** | **18** | **Completed: 18** ✅ |

**Estimated MVP Timeline**: 2-3 weeks (assuming 1 developer, 4-5 tasks/week)
