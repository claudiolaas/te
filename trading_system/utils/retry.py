"""Retry configuration using tenacity.

This module provides default retry configuration for CCXT operations.
Use tenacity's @retry decorator directly with these defaults.

Example:
    from tenacity import retry
    from trading_system.utils.retry import DEFAULT_RETRY

    @retry(**DEFAULT_RETRY)
    async def fetch_data():
        return await client.fetch_ticker("BTC/USDT")
"""

import ccxt
from tenacity import (
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Default retry configuration for CCXT network operations
DEFAULT_RETRY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=60),
    retry=retry_if_exception_type(
        (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout)
    ),
    reraise=True,  # Re-raise the original exception instead of RetryError
)

__all__ = ["DEFAULT_RETRY"]
