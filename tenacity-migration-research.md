# Tenacity Migration Research

## Understanding of the Feature

### What This Feature Does
Migrate from a custom-built retry mechanism to using the `tenacity` library - a popular, well-maintained Python library for retrying operations with various backoff strategies.

### Key Requirements and Goals
1. **Replace custom retry logic** with `tenacity` equivalents
2. **Preserve existing behavior** (but API syntax can change):
   - Exponential backoff with configurable base and max delay
   - Configurable max attempts
   - Configurable retryable exceptions (default to CCXT network errors)
   - Support for both sync and async functions
   - Logging of retry attempts
   - Optional callback on retry
3. **Add tenacity as a dependency** in `pyproject.toml`
4. **Update all usages** in the codebase to use the new syntax
5. **Update tests** to verify tenacity-based implementation

### User-Facing Behavior
- **Behavior is preserved**: same retry logic, backoff, exception handling
- **API may change**: we can use tenacity's native syntax or a simplified wrapper
- **All existing usages** in `backfill_service.py` and `price_fetcher.py` will be updated to new syntax

---

## How the Feature Fits in the Codebase

### Current Implementation Location
- **Main file**: `trading_system/utils/retry.py` (245 lines)
- **Exports**: `trading_system/utils/__init__.py`

### Current API Surface

```python
# Configuration
@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple[type[Exception], ...] = (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout)

# Decorator
@with_retry(config=None, on_retry=None)

# Class-based wrapper
RetryableOperation(func, config=None, name=None)

# Functional helper
retry_operation(func, *args, config=None, **kwargs)
```

### Current Usage in Codebase

1. **`trading_system/services/backfill_service.py`** (line 102):
   ```python
   @with_retry(RetryConfig(max_attempts=3, base_delay=1.0))
   async def _fetch_with_retry(...)
   ```

2. **`trading_system/heartbeat/price_fetcher.py`** (line 108):
   ```python
   @with_retry(RetryConfig(max_attempts=3, base_delay=1.0))
   async def _fetch_tickers_with_retry(...)
   ```

3. **Tests**: `tests/test_retry.py` (278 lines) - comprehensive tests for all retry functionality

---

## Migration Strategy

Since the API syntax can change, the recommended approach is:

### Option: Native Tenacity with Project Defaults

**Approach**:
1. Add `tenacity` to dependencies
2. Delete `trading_system/utils/retry.py` entirely
3. Update usages to use tenacity's native `@retry` decorator
4. Create a small defaults module OR define common retry configs at call sites

**Example of new usage**:
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import ccxt
import logging

logger = logging.getLogger(__name__)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=60),
    retry=retry_if_exception_type((ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def _fetch_with_retry(...):
    ...
```

**Benefits**:
- Clean, idiomatic tenacity usage
- No wrapper/abstraction overhead
- Full access to tenacity features (jitter, composite waits, etc.)
- Less code to maintain

---

## Clarifying Questions

1. **Sync Function Support**: The current sync implementation retries immediately without delay. Should tenacity migration:
   - **A)** Keep this behavior (no delay for sync)
   - **B)** Implement proper delays for sync using tenacity's built-in waits
   - **C)** Only support async (remove sync support) - removes need for sync tests

2. **Project defaults**: Should we create a shared retry configuration (e.g., `RETRY_DEFAULTS = dict(stop=..., wait=..., retry=...)`) that can be spread into `@retry(**RETRY_DEFAULTS)`?

3. **`RetryableOperation` class**: This class provides imperative retry execution. Is this needed, or can usages be converted to decorator style?

4. **`retry_operation` function**: Same question - is this pattern needed, or can it be replaced?

---

## Files to Modify

| File | Changes |
|------|---------|
| `pyproject.toml` | Add `tenacity>=8.0.0` to dependencies |
| `trading_system/utils/retry.py` | **Delete** (no longer needed) |
| `trading_system/utils/__init__.py` | Remove retry exports |
| `trading_system/services/backfill_service.py` | Update to tenacity native syntax |
| `trading_system/heartbeat/price_fetcher.py` | Update to tenacity native syntax |
| `tests/test_retry.py` | **Delete** or repurpose to test tenacity integration |
| `tests/test_backfill_service.py` | Update if tests rely on retry internals |

---

## Tenacity Feature Mapping

| Current Feature | Tenacity Equivalent |
|----------------|---------------------|
| `max_attempts` | `stop=stop_after_attempt(n)` |
| `base_delay` + `exponential_base` + `max_delay` | `wait=wait_exponential(min=base_delay, max=max_delay, exp_base=exponential_base)` |
| `retryable_exceptions` | `retry=retry_if_exception_type((exc1, exc2, ...))` |
| `on_retry` callback | `before_sleep=before_sleep_log(logger, level)` or custom callback |
| Async support | Works automatically with `@retry` |
| Logging | `before_sleep_log(logger, logging.WARNING)` |

---

## Potential Challenges

1. **Tests need rewriting**: Since we're changing the API, all retry tests need to be rewritten for tenacity

2. **Sync delay behavior**: Tenacity implements proper delays for sync functions. If we want to keep current behavior (no delays), we'd need to use `wait=wait_none()` for sync

3. **RetryableOperation / retry_operation**: If these patterns are needed, we need to decide how to implement with tenacity (or if they can be removed)
