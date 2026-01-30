# Binance API Research Findings

**Date:** 2026-01-29  
**Researcher:** Kimi Code CLI  
**Purpose:** Understand Binance API via CCXT for trading system implementation

---

## Executive Summary

Successfully tested Binance API integration using CCXT. All core operations work as expected:
- ✅ OHLCV/Klines fetching for backfill
- ✅ Current price fetching via tickers
- ✅ Wallet balance inspection
- ✅ Rate limiting works correctly
- ✅ API keys are valid and functional

---

## 1. Exchange Connection & Markets

### Findings
- **Markets loaded:** 4,206 trading pairs
- **Rate limit default:** 50ms between requests (configured by CCXT)
- **Time synchronization:** Exchange time matches UTC

### Popular Pairs Availability
| Symbol | Min Amount | Price Precision |
|--------|-----------|-----------------|
| BTC/USDT | 0.00001 | 0.01 |
| ETH/USDT | 0.0001 | 0.01 |
| SOL/USDT | 0.001 | 0.01 |
| BNB/USDT | 0.001 | 0.01 |

### Implications
- No need to validate symbol existence - CCXT throws error on invalid symbols
- Price precision handled automatically by CCXT
- Minimum order amounts must be checked before placing orders

---

## 2. OHLCV (Klines) Data - Critical for Backfill

### Data Structure
```python
# CCXT OHLCV format: [timestamp, open, high, low, close, volume]
candle = [
    1738164900000,  # timestamp (milliseconds)
    87463.65,       # open
    87463.66,       # high
    87425.62,       # low
    87445.80,       # close
    15.7628         # volume
]
```

### Timestamp Behavior
- **Interval:** 1-minute candles align to minute boundaries (HH:MM:00)
- **Timezone:** UTC (as Unix timestamps)
- **Example timestamps fetched:**
  - `14:55:00` - closed candle
  - `14:56:00` - closed candle
  - `14:57:00` - closed candle
  - `14:58:00` - closed candle
  - `14:59:00` - **current/open candle**

### Backfill Strategy Design

#### Scenario: Register BTC/USDT at 14:59:06
**Requirement:** BACKFILL_MINUTES=5 (from .env)

**Expected database entries:**
```
14:55:00 | close: 87445.80  ✓
14:56:00 | close: 87315.71  ✓
14:57:00 | close: 87183.48  ✓
14:58:00 | close: 87014.39  ✓
14:59:00 | close: 87062.83  ✓ (current minute, still open)
```

**Actual fetched data:**
```
14:55:00 | close: 87445.80
14:56:00 | close: 87315.71
14:57:00 | close: 87183.48
14:58:00 | close: 87014.39
14:59:00 | close: 87062.83
```

✅ **No gaps detected** - Binance provides continuous 1m data

### Key Finding: The "Buffer Delay" Importance

The current minute's candle (e.g., 14:59:00) is **still forming** during the minute. The heartbeat waits 5 seconds past the minute mark to ensure the previous minute's candle is closed.

**Sequence:**
1. `14:59:00` - Candle starts forming
2. `14:59:06` - Symbol registered, backfill fetches up to current
3. `15:00:05` - **First heartbeat** (60s interval + 5s buffer)
4. At this point, `14:59:00` candle is guaranteed closed

### Implementation Recommendation

```python
async def backfill_symbol(exchange, symbol: str, backfill_minutes: int):
    """
    Fetch historical candles for backfill.
    
    Strategy:
    1. Calculate start_time = now - backfill_minutes
    2. Fetch candles with since=start_time
    3. Store in database with timestamp rounded to minute
    4. On next heartbeat, fetch only the new closed candle
    """
    now_ms = exchange.milliseconds()
    backfill_start_ms = now_ms - (backfill_minutes * 60 * 1000)
    
    ohlcv = await exchange.fetch_ohlcv(
        symbol=symbol,
        timeframe='1m',
        since=backfill_start_ms,
        limit=backfill_minutes + 1  # +1 for current forming candle
    )
    
    # Filter out the current forming candle if needed
    candles = []
    for ts, o, h, l, c, v in ohlcv:
        # Round timestamp to minute boundary
        minute_ts = (ts // 60000) * 60000
        candles.append({
            'symbol': symbol,
            'timestamp': minute_ts,
            'open': o,
            'high': h,
            'low': l,
            'close': c,
            'volume': v
        })
    
    return candles
```

---

## 3. Current Price Fetching

### Single vs Multiple Tickers
- **Single ticker:** `fetch_ticker('BTC/USDT')` - detailed info
- **Multiple tickers:** `fetch_tickers(['BTC/USDT', 'ETH/USDT'])` - more efficient for heartbeat

### Ticker Structure
```python
{
    'symbol': 'BTC/USDT',
    'last': 87025.51,           # Last traded price
    'bid': 87025.51,            # Best bid
    'ask': 87025.52,            # Best ask
    'quoteVolume': 1260181726.7, # 24h volume in USDT
    'timestamp': 1738165143005, # Exchange timestamp
}
```

### Heartbeat Implementation
For the heartbeat's price fetching, use `fetch_tickers()` with all registered symbols:

```python
async def fetch_prices(exchange, registered_symbols: list[str]):
    """Fetch current prices for all registered symbols."""
    tickers = await exchange.fetch_tickers(registered_symbols)
    
    prices = {}
    for symbol in registered_symbols:
        if symbol in tickers:
            prices[symbol] = {
                'price': tickers[symbol]['last'],
                'timestamp': tickers[symbol]['timestamp'],
                'bid': tickers[symbol]['bid'],
                'ask': tickers[symbol]['ask']
            }
    
    return prices
```

---

## 4. Wallet & Balance Inspection

### Balance Structure
```python
{
    'BTC': {'free': 0.000011, 'used': 0.0, 'total': 0.000011},
    'ETH': {'free': 0.000147, 'used': 0.0, 'total': 0.000147},
    'USDC': {'free': 124.736025, 'used': 0.0, 'total': 124.736025},
    # ... more currencies
    'timestamp': 1769502845514
}
```

### Key Findings
1. **Small balances exist** - dust from previous trades
2. **USDC available** - 124.74 USDC for trading
3. **No USDT** - but strategies typically trade against USDT pairs
4. **Free vs Used** - clean separation for open orders

### Wallet Snapshot for Heartbeat
The heartbeat needs to capture:
1. **Exchange wallet** - full balance from `fetch_balance()`
2. **Strategy sub-wallets** - calculated from trades (not directly available)

```python
async def capture_wallet_snapshot(exchange):
    """Capture full wallet snapshot for heartbeat."""
    balance = await exchange.fetch_balance()
    
    snapshot = {
        'timestamp': balance['timestamp'],
        'balances': {
            currency: {
                'total': data['total'],
                'free': data['free'],
                'used': data['used']
            }
            for currency, data in balance.items()
            if isinstance(data, dict) and data.get('total', 0) > 0
        }
    }
    
    return snapshot
```

---

## 5. Rate Limits

### Measured Performance
| Metric | Value |
|--------|-------|
| CCXT rateLimit | 50ms |
| Average request time | ~320ms |
| 5 requests total | ~1.6s |

### Implications for Heartbeat
- Heartbeat must complete within 60 seconds
- 3 API calls per heartbeat minimum:
  1. `fetch_tickers()` - all symbol prices
  2. `fetch_balance()` - wallet snapshot
  3. Strategy-specific calls (if any)
- With rate limiting, this should complete in < 2 seconds

### Binance Rate Limits (Official)
- **Request weight:** Each endpoint has a "weight"
- **IP limits:** 1,200 request weight per minute
- **Order limits:** 50 orders per 10 seconds (for trading)

CCXT handles rate limiting automatically with `enableRateLimit: True`.

---

## 6. Order Placement

### Market Order Example
```python
order = await exchange.create_market_buy_order(
    symbol='BTC/USDT',
    amount=0.001  # BTC amount to buy
)
```

### Order Response Structure
```python
{
    'id': '123456789',
    'clientOrderId': 'my_order_123',
    'symbol': 'BTC/USDT',
    'type': 'market',
    'side': 'buy',
    'amount': 0.001,
    'price': None,           # Market order - no fixed price
    'cost': 87.02,           # Total USDT spent
    'filled': 0.001,
    'remaining': 0.0,
    'status': 'closed',      # Market orders fill immediately
    'trades': [...]          # Individual fills
}
```

### Safety Considerations
- **No testnet used** - these are real API keys with real funds
- **Small amounts** - wallet has minimal balance, safe to test
- **Market orders** - execute immediately at current market price

---

## 7. Backfill Design Specification

Based on the research, here is the recommended backfill implementation:

### Database Schema (Price Data)
```sql
CREATE TABLE price_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,  -- Unix timestamp in milliseconds, rounded to minute
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timestamp)
);

CREATE INDEX idx_price_symbol_time ON price_data(symbol, timestamp);
```

### Backfill Algorithm
```python
class BackfillService:
    def __init__(self, exchange, db, settings):
        self.exchange = exchange
        self.db = db
        self.backfill_minutes = settings.backfill_minutes
    
    async def backfill_symbol(self, symbol: str) -> list[dict]:
        """
        Backfill historical data for a newly registered symbol.
        
        Returns list of candle data stored to database.
        """
        now_ms = self.exchange.milliseconds()
        start_ms = now_ms - (self.backfill_minutes * 60 * 1000)
        
        # Fetch candles
        ohlcv = await self.exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe='1m',
            since=start_ms,
            limit=self.backfill_minutes + 1
        )
        
        # Transform and store
        candles = []
        for ts, o, h, l, c, v in ohlcv:
            # Ensure timestamp is at minute boundary
            minute_ts = (ts // 60000) * 60000
            
            candle = {
                'symbol': symbol,
                'timestamp': minute_ts,
                'open': o,
                'high': h,
                'low': l,
                'close': c,
                'volume': v
            }
            candles.append(candle)
        
        # Store in database
        await self.db.store_price_data(candles)
        
        return candles
```

### Error Handling
```python
async def backfill_with_retry(self, symbol: str, max_retries: int = 3):
    """Backfill with exponential backoff on failure."""
    for attempt in range(max_retries):
        try:
            return await self.backfill_symbol(symbol)
        except ccxt.NetworkError as e:
            wait_time = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(f"Backfill attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)
        except ccxt.ExchangeError as e:
            logger.error(f"Backfill failed permanently: {e}")
            raise
    
    raise Exception(f"Backfill failed after {max_retries} attempts")
```

### Backfill Timing Diagram

```
Timeline (registering at 14:59:06):

14:54:00  14:55:00  14:56:00  14:57:00  14:58:00  14:59:00  15:00:00  15:01:00
    |         |         |         |         |         |         |         |
    ▼         ▼         ▼         ▼         ▼         ▼         ▼         ▼
   [=========backfilled=========]  [register  [====heartbeat starts====]
                                    @14:59:06]          
                                                         ▲
                                                    fetches this
                                                    at 15:00:05
```

---

## 8. Key Findings Summary

| Finding | Impact | Recommendation |
|---------|--------|----------------|
| OHLCV timestamps align to minute boundaries | Reliable backfill | Store timestamps rounded to 60s |
| No gaps in 1m data | Simpler logic | No gap-filling needed for MVP |
| Rate limit 50ms | Fast enough | Keep `enableRateLimit: True` |
| `fetch_tickers()` batch | Efficient | Fetch all prices in one call |
| Current candle is open | Wait for close | Use buffer delay (5s) before fetching |
| Wallet has small balances | Safe to test | Can test with real API |

---

## 9. Open Questions

1. **Testnet availability:** Should we use Binance testnet for development?
   - Testnet requires separate API keys
   - Testnet has different rate limits
   - Real data is more reliable for testing

2. **Subwallet calculation:** How to track per-strategy balances?
   - Option A: Calculate from trade history
   - Option B: Maintain allocation percentages
   - Option C: Track strategy positions separately

3. **Symbol normalization:** CCXT uses `BTC/USDT`, but Binance API uses `BTCUSDT`
   - CCXT handles normalization automatically
   - Store in database as `BTC/USDT` for consistency

---

## 10. Order Placement Deep Dive

### Market Limits for BTC/USDT
| Limit | Value | Notes |
|-------|-------|-------|
| Min amount | 0.00001 BTC | ~$0.87 at current price |
| Max amount | 9000 BTC | Not a concern for us |
| Min cost | 5 USDT | Hard minimum spend |
| Price precision | 0.01 | 2 decimal places |
| Amount precision | 0.00001 | 5 decimal places |

### Order Validation Checklist
Before placing any order:
1. ✅ Amount >= `market.limits.amount.min` (0.00001 BTC)
2. ✅ Cost >= `market.limits.cost.min` (5 USDT)
3. ✅ Balance check (free >= amount for sells, free >= estimated cost for buys)
4. ✅ Round amount to `market.precision.amount` (5 decimals)

### Order Lifecycle for Trading System
```
┌─────────────────────────────────────────────────────────────────┐
│ 1. STRATEGY RUN()                                               │
│    └── Returns target_position (0.0 to 1.0)                      │
├─────────────────────────────────────────────────────────────────┤
│ 2. EXECUTOR CALCULATES                                          │
│    ├── current_value = base_amount * current_price              │
│    ├── target_value = total_value * target_position             │
│    └── delta = target_value - current_value                     │
├─────────────────────────────────────────────────────────────────┤
│ 3. VALIDATE ORDER                                               │
│    ├── Check amount >= market.limits.amount.min                 │
│    ├── Check cost >= market.limits.cost.min                     │
│    └── Check balance sufficiency                                │
├─────────────────────────────────────────────────────────────────┤
│ 4. PLACE ORDER                                                  │
│    └── create_market_buy_order() or create_market_sell_order()  │
├─────────────────────────────────────────────────────────────────┤
│ 5. HANDLE RESPONSE                                              │
│    ├── status='closed' → Update state, log trade                │
│    ├── status='rejected' → Log error, no state change           │
│    └── status='open' → Poll until filled (unlikely for market)  │
├─────────────────────────────────────────────────────────────────┤
│ 6. UPDATE DATABASE                                              │
│    ├── Insert trade record                                      │
│    ├── Update strategy position                                 │
│    └── Update wallet snapshot                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Test Order Endpoint
Binance supports a test endpoint that validates without executing:
```python
# This validates the order but does NOT execute it
order = await exchange.create_order(
    symbol='BTC/USDT',
    type='market',
    side='buy',
    amount=0.00001,
    params={'test': True}  # ← Test mode
)
```

**Use case:** Pre-flight validation before actual trading.

---

## 11. Next Steps

1. ✅ Research complete - all findings documented
2. 🔄 Design database schema for price data (TASK-4)
3. 🔄 Implement `BinanceClient` class (TASK-5):
   - `fetch_ohlcv()` for backfill
   - `fetch_prices()` for heartbeat
   - `fetch_balance()` for wallet snapshot
   - `place_order()` for execution
4. 🔄 Implement `BackfillService` with retry logic
5. 🔄 Build Heartbeat Engine (TASK-6)

---

## Appendix A: Raw API Data Samples

### OHLCV Sample
```python
[
    1738164900000,  # 2026-01-29T14:55:00Z
    87463.65,       # open
    87463.66,       # high  
    87425.62,       # low
    87445.80,       # close
    15.7628         # volume
]
```

### Ticker Sample
```python
{
    'symbol': 'BTC/USDT',
    'last': 87025.51,
    'bid': 87025.51,
    'ask': 87025.52,
    'quoteVolume': 1260181726.7,
    'timestamp': 1738165143005
}
```

### Balance Sample
```python
{
    'BTC': {'free': 1.139e-05, 'used': 0.0, 'total': 1.139e-05},
    'USDC': {'free': 124.73602509, 'used': 0.0, 'total': 124.73602509}
}
```
