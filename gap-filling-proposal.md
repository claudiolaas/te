# Gap-Filling Extension for Backfill Mechanism

## Executive Summary

This proposal outlines an extension to the existing backfill mechanism that intelligently handles **gap-filling** when a symbol already has data in the database. Instead of always fetching `BACKFILL_MINUTES` of historical data, the system will detect gaps between the last stored datapoint and the current time, filling only what's necessary.

---

## Current Behavior

```python
# Current implementation always fetches BACKFILL_MINUTES from "now"
now_ms = self._binance.milliseconds
since_ms = now_ms - (backfill_minutes * 60 * 1000)
```

**Problem:** 
- Symbol has data from 12:34:00 - 12:55:00 (21 minutes)
- System restarts at 13:05:00 (10 minute gap)
- With `BACKFILL_MINUTES=100`, system fetches 100 minutes from 11:25:00 onwards
- Result: ~79 minutes of duplicate data + 10 minutes of gap data

---

## Proposed Behavior

### Core Logic: Smart Gap Detection

```python
async def backfill_symbol_with_gap_fill(self, symbol: str, minutes: int | None = None) -> dict:
    """
    Strategy:
    1. Get latest timestamp from database
    2. Calculate gap between latest and now
    3. Apply gap-filling rules based on gap_size vs backfill_minutes
    4. Fetch and store missing data
    """
```

### Decision Matrix

| Scenario | Gap Size | Existing Data | BACKFILL_MINUTES | Action | Rationale |
|----------|----------|---------------|------------------|--------|-----------|
| **1** | 5 min | 10 records | 100 | Fill gap + extend to 100 min | Gap insufficient for required history |
| **2** | 5 min | 200 records | 100 | Fill gap only | Already have sufficient history |
| **3** | 0 min | 100 records | 100 | No action | Data is continuous and sufficient |
| **4** | 30 min | 0 records | 100 | Full backfill (100 min) | No existing data, standard backfill |
| **5** | 150 min | 50 records | 100 | Fill gap (150 min) | Gap larger than backfill window |
| **6** | 5 min | 10 records | 5 | Fill gap only | Gap satisfies backfill requirement |
| **7** | 0 min | 50 records | 100 | Extend 50 min back | Continuous but insufficient history |

---

## Gap-Filling Strategy Rules

### Rule 1: Gap Detection Threshold

```python
GAP_FILL_THRESHOLD_MS = 60_000  # 1 minute - gaps smaller than this are ignored
```
- Gaps < 1 minute are considered "continuous" (network jitter, processing delays)
- Gaps >= 1 minute trigger gap-filling logic

### Rule 2: Required History Calculation

```python
required_history_ms = backfill_minutes * 60 * 1000
existing_history_ms = now_ms - oldest_timestamp  # if data exists
actual_history_ms = now_ms - latest_timestamp    # if filling gap
```

### Rule 3: Fetch Window Determination

```python
# Case A: No existing data -> Standard backfill
if latest_timestamp is None:
    since_ms = now_ms - required_history_ms

# Case B: Gap + insufficient existing history -> Fill gap + extend
elif (gap_size + existing_history_ms) < required_history_ms:
    # Need to go back further to meet BACKFILL_MINUTES requirement
    since_ms = now_ms - required_history_ms

# Case C: Gap + sufficient existing history -> Fill gap only
else:
    since_ms = latest_timestamp + 60_000  # Start from after last data point
```

### Rule 4: Overlapping Data Handling

The database already handles this via `ON CONFLICT DO UPDATE`:

```sql
INSERT INTO price_data ...
ON CONFLICT(symbol_id, timestamp) DO UPDATE SET
    open = excluded.open,
    high = excluded.high,
    low = excluded.low,
    close = excluded.close,
    volume = excluded.volume
```

This ensures idempotent operations - refetching existing data is safe.

---

## Detailed Scenarios with Examples

### Scenario 1: Small Gap, Insufficient History (Gap + Extend)

```
Timeline:
  12:00 ├───────┬───────┬───────┬───────────────────────────┤ 13:30
       DB:10   DB:20  LATEST   GAP:5min                  NOW
       
  BACKFILL_MINUTES = 100
  Existing data: 10 records (10 min)
  Gap: 5 minutes
  
Calculation:
  Required: 100 minutes
  Have: 10 + 5 = 15 minutes (if only fill gap)
  Missing: 100 - 15 = 85 minutes
  
Action:
  Fetch from: NOW - 100 min = 12:30
  Fetch to: NOW = 13:30
  Result: 100 candles (fills gap + extends back 85 min)
```

### Scenario 2: Small Gap, Sufficient History (Gap Only)

```
Timeline:
  11:30 ├────────────────────────────┬────────┬───────┤ 13:30
       DB:200 records (200 min)     LATEST   GAP:5min  NOW
       
  BACKFILL_MINUTES = 100
  Existing data: 200 records
  Gap: 5 minutes
  
Calculation:
  Required: 100 minutes
  Have: 200 + 5 = 205 minutes (if fill gap)
  Missing: 0 (already have enough)
  
Action:
  Fetch from: LATEST + 1 min = 13:25:00
  Fetch to: NOW = 13:30:00
  Result: 5 candles (gap fill only)
```

### Scenario 3: Large Gap, Any History (Gap Priority)

```
Timeline:
  11:00 ├───────┤                 ├──────────────────────┤ 13:30
       DB:50                          GAP:100min          NOW
       
  BACKFILL_MINUTES = 100
  Existing data: 50 records
  Gap: 100 minutes
  
Calculation:
  Gap (100 min) >= BACKFILL_MINUTES (100 min)
  
Action:
  Fetch from: LATEST + 1 min = 11:51:00
  Fetch to: NOW = 13:30:00
  Result: 100 candles (fills entire gap)
  Note: Old data (11:00-11:50) becomes "orphaned" in DB
```

### Scenario 4: Continuous Data, Insufficient History (Extend Backward)

```
Timeline:
  12:40 ├────────────────────────────┤ 13:30
       OLDEST (50 records)          NOW
       
  BACKFILL_MINUTES = 100
  Existing data: 50 records (continuous)
  Gap: 0 minutes
  
Calculation:
  Required: 100 minutes
  Have: 50 minutes
  Missing: 50 minutes
  
Action:
  Fetch from: NOW - 100 min = 12:30
  Fetch to: NOW = 13:30:00
  Result: 100 candles (extends back 50 min, 50 overlapped)
```

### Scenario 5: No Existing Data (Standard Backfill)

```
Timeline:
  13:00 ├────────────────────────────┤ 13:30
       (empty)                      NOW
       
  BACKFILL_MINUTES = 100
  
Action:
  Fetch from: NOW - 100 min = 12:20
  Fetch to: NOW = 13:30
  Result: 100 candles (standard backfill)
```

---

## Edge Cases & Mitigations

### Edge Case 1: Clock Skew / Future Timestamps

**Problem:** System clock or exchange clock is ahead of database timestamp.

```
Latest DB timestamp: 13:00:00
Exchange time: 12:59:30 (30s behind)
Calculated gap: -30 seconds (negative!)
```

**Mitigation:**
```python
if gap_ms < 0:
    logger.warning(f"Clock skew detected: gap={gap_ms}ms, treating as 0")
    gap_ms = 0
```

### Edge Case 2: Exchange Data Unavailable for Gap Period

**Problem:** Exchange was down or symbol was delisted during gap period.

```
Gap: 12:00 - 13:00 (1 hour)
Exchange returns empty for 12:30 - 12:45
```

**Mitigation:**
- Log warning about partial gap fill
- Continue with available data
- Mark gap as "partially filled" in metrics

### Edge Case 3: Very Large Gaps (> 1000 candles)

**Problem:** System was down for days. Gap = 5000 minutes.

```
BACKFILL_MINUTES = 100
Gap = 5000 minutes
```

**Mitigation:**
```python
MAX_GAP_FILL_MINUTES = 1000  # Configurable limit

if gap_minutes > MAX_GAP_FILL_MINUTES:
    logger.warning(f"Gap too large ({gap_minutes}m), limiting to {MAX_GAP_FILL_MINUTES}m")
    since_ms = now_ms - (MAX_GAP_FILL_MINUTES * 60 * 1000)
```

### Edge Case 4: Duplicate Timestamps from Different Sources

**Problem:** Backfill OHLCV and heartbeat ticker data may have same timestamp.

**Mitigation:**
- Backfill uses OHLCV (has volume)
- Heartbeat uses ticker (volume=0)
- `ON CONFLICT DO UPDATE` ensures latest data wins
- Consider adding `data_source` column for traceability

### Edge Case 5: Partial Candle at Gap Boundary

**Problem:** Gap ends at 13:05:00, but current candle is forming (13:05:00 - 13:06:00).

```
Latest complete candle: 13:04:00
Current forming candle: 13:05:00 (incomplete)
Gap fill should not include 13:05:00 if using OHLCV
```

**Mitigation:**
```python
# Don't fetch the currently forming candle
end_ms = ((now_ms // 60000) * 60000) - 60000  # Previous complete minute
```

### Edge Case 6: Rate Limits During Gap Fill

**Problem:** Large gap requires many API calls (pagination).

```python
# Binance limit is 1000 candles per request
# Gap of 5000 minutes = 5 requests
```

**Mitigation:**
- Use existing retry mechanism
- Add delay between pagination requests
- Consider `asyncio.gather` for multiple symbols

### Edge Case 7: Multiple Consecutive Gap Fills

**Problem:** System starts, fills gap, crashes, restarts - gap exists again.

```
Restart 1: Fill gap 12:00-13:00, crashes at 13:15
Restart 2: Should detect 13:00-13:15 as new gap
```

**Mitigation:**
- Atomic writes (per candle via UPSERT)
- Each restart recalculates gap from actual DB state
- Idempotent operations ensure consistency

---

## Implementation Plan

### Phase 1: Core Gap Detection

1. Add `get_oldest()` method to `PriceRepository`
2. Modify `BackfillService.backfill_symbol()` to detect gaps
3. Implement fetch window calculation logic

### Phase 2: Configuration Options

Add to `Settings`:
```python
# Gap filling configuration
gap_fill_enabled: bool = Field(default=True, description="Enable automatic gap filling")
gap_fill_threshold_minutes: int = Field(default=1, ge=0, description="Minimum gap to trigger fill")
max_gap_fill_minutes: int = Field(default=1000, ge=1, description="Maximum gap to fill in one operation")
```

### Phase 3: API Enhancement

Add endpoint to trigger manual gap fill:
```python
@app.post("/symbols/{symbol}/gap-fill")
async def trigger_gap_fill(symbol: str, max_minutes: int | None = None) -> dict:
    """Manually trigger gap fill for a symbol."""
```

### Phase 4: Monitoring & Metrics

Track in backfill status:
```python
{
    'gap_detected': True,
    'gap_minutes': 15,
    'gap_from': '2024-01-15T12:45:00Z',
    'gap_to': '2024-01-15T13:00:00Z',
    'fetch_strategy': 'gap_only',  # 'gap_only', 'gap_plus_extend', 'full_backfill'
}
```

---

## Algorithm Pseudocode

```python
async def backfill_symbol(self, symbol: str, minutes: int | None = None) -> dict:
    backfill_minutes = minutes or self._settings.backfill_minutes
    symbol_obj = await self._symbol_repo.get_by_symbol(symbol)
    
    now_ms = self._binance.milliseconds
    required_ms = backfill_minutes * 60 * 1000
    
    # Get existing data range
    latest = await self._price_repo.get_latest(symbol_obj.id)
    
    if latest is None:
        # No existing data - standard backfill
        since_ms = now_ms - required_ms
        strategy = "full_backfill"
    else:
        gap_ms = now_ms - latest.timestamp
        threshold_ms = self._settings.gap_fill_threshold_minutes * 60 * 1000
        
        if gap_ms <= threshold_ms:
            # Continuous data - check if need to extend backward
            oldest = await self._price_repo.get_oldest(symbol_obj.id)
            existing_ms = now_ms - oldest.timestamp
            
            if existing_ms >= required_ms:
                # Have sufficient history, no action needed
                return {'status': 'no_action', 'reason': 'sufficient_history'}
            else:
                # Need to extend backward
                since_ms = now_ms - required_ms
                strategy = "extend_backward"
        else:
            # Gap detected
            oldest = await self._price_repo.get_oldest(symbol_obj.id)
            existing_ms = latest.timestamp - oldest.timestamp if oldest else 0
            
            if (gap_ms + existing_ms) < required_ms:
                # Gap + existing < required, need to extend
                since_ms = now_ms - required_ms
                strategy = "gap_plus_extend"
            else:
                # Gap alone satisfies requirement
                since_ms = latest.timestamp + 60_000  # Start after last data
                strategy = "gap_only"
    
    # Apply max gap limit
    max_gap_ms = self._settings.max_gap_fill_minutes * 60 * 1000
    if (now_ms - since_ms) > max_gap_ms:
        since_ms = now_ms - max_gap_ms
        strategy += "_limited"
    
    # Fetch and store
    candles = await self._fetch_with_retry(symbol, since_ms, backfill_minutes)
    price_data = self._transform_candles(symbol_obj.id, candles)
    await self._price_repo.save_many(symbol_obj.id, price_data)
    
    return {
        'status': 'success',
        'strategy': strategy,
        'records_stored': len(price_data),
        'fetch_from_ms': since_ms,
        'fetch_to_ms': now_ms,
    }
```

---

## Backward Compatibility

The enhanced backfill is **fully backward compatible**:

1. **Default behavior:** Works exactly as before for new symbols
2. **Config opt-in:** Gap filling can be disabled via `gap_fill_enabled=false`
3. **Existing API:** `backfill_symbol()` signature unchanged
4. **Database:** No schema changes required

---

## Summary

This proposal introduces intelligent gap-filling that:

1. ✅ **Saves API calls** - Only fetches missing data when possible
2. ✅ **Maintains history requirements** - Ensures BACKFILL_MINUTES is always met
3. ✅ **Handles all edge cases** - Clock skew, large gaps, partial fills
4. ✅ **Backward compatible** - Existing behavior preserved for new symbols
5. ✅ **Observable** - Clear metrics on what strategy was used

**Key Decision Rule:**
```
IF gap + existing_data >= BACKFILL_MINUTES:
    Fill gap only
ELSE:
    Fill gap AND extend backward to meet BACKFILL_MINUTES
```

This ensures the system always maintains the configured history window while minimizing unnecessary API calls.
