"""Retry logic with exponential backoff for transient failures."""

import asyncio
import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import ccxt

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_attempts: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay between retries in seconds (default: 1.0)
        max_delay: Maximum delay between retries in seconds (default: 60.0)
        exponential_base: Base for exponential backoff (default: 2.0)
        retryable_exceptions: Tuple of exception types to retry on
    """
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple[type[Exception], ...] = (
        ccxt.NetworkError,
        ccxt.ExchangeNotAvailable,
        ccxt.RequestTimeout,
    )

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt using exponential backoff.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        delay = self.base_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)


def with_retry(
    config: RetryConfig | None = None,
    on_retry: Callable[[Exception, int, float], None] | None = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for adding retry logic with exponential backoff.

    Args:
        config: Retry configuration (uses defaults if not provided)
        on_retry: Optional callback called on each retry with (exception, attempt, delay)

    Returns:
        Decorated function

    Example:
        @with_retry()
        async def fetch_data():
            return await api.get_data()

        @with_retry(RetryConfig(max_attempts=5, base_delay=2.0))
        async def critical_operation():
            return await api.critical_call()
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            last_exception: Exception | None = None

            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e

                    if attempt < config.max_attempts - 1:
                        delay = config.calculate_delay(attempt)

                        logger.warning(
                            f"Retry attempt {attempt + 1}/{config.max_attempts} "
                            f"for {func.__name__}: {e}. Retrying in {delay:.1f}s..."
                        )

                        if on_retry:
                            on_retry(e, attempt, delay)

                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"Max retries ({config.max_attempts}) exceeded "
                            f"for {func.__name__}: {e}"
                        )

            # All retries exhausted
            raise last_exception or RuntimeError("Retry loop failed without exception")

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            # For sync functions, we can't use asyncio.sleep
            # This is a simplified version that just retries immediately
            last_exception: Exception | None = None

            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e

                    if attempt < config.max_attempts - 1:
                        logger.warning(
                            f"Retry attempt {attempt + 1}/{config.max_attempts} "
                            f"for {func.__name__}: {e}"
                        )

                        if on_retry:
                            on_retry(e, attempt, 0)
                    else:
                        logger.error(
                            f"Max retries ({config.max_attempts}) exceeded "
                            f"for {func.__name__}: {e}"
                        )

            raise last_exception or RuntimeError("Retry loop failed without exception")

        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class RetryableOperation:
    """Class-based retry wrapper for more complex scenarios.

    Allows for dynamic retry configuration and state tracking.

    Example:
        operation = RetryableOperation(fetch_data, RetryConfig(max_attempts=5))
        result = await operation.execute()
    """

    def __init__(
        self,
        func: Callable[..., T],
        config: RetryConfig | None = None,
        name: str | None = None
    ):
        """Initialize retryable operation.

        Args:
            func: Function to wrap
            config: Retry configuration
            name: Operation name for logging
        """
        self._func = func
        self._config = config or RetryConfig()
        self._name = name or func.__name__
        self._attempt_count = 0

    async def execute(self, *args, **kwargs) -> T:
        """Execute the operation with retries.

        Args:
            *args: Positional arguments for the wrapped function
            **kwargs: Keyword arguments for the wrapped function

        Returns:
            Result of the wrapped function
        """
        self._attempt_count = 0
        last_exception: Exception | None = None

        for attempt in range(self._config.max_attempts):
            self._attempt_count = attempt + 1

            try:
                if asyncio.iscoroutinefunction(self._func):
                    return await self._func(*args, **kwargs)
                else:
                    return self._func(*args, **kwargs)
            except self._config.retryable_exceptions as e:
                last_exception = e

                if attempt < self._config.max_attempts - 1:
                    delay = self._config.calculate_delay(attempt)

                    logger.warning(
                        f"Retry attempt {attempt + 1}/{self._config.max_attempts} "
                        f"for {self._name}: {e}. Retrying in {delay:.1f}s..."
                    )

                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Max retries ({self._config.max_attempts}) exceeded "
                        f"for {self._name}: {e}"
                    )

        raise last_exception or RuntimeError("Retry loop failed without exception")

    @property
    def attempt_count(self) -> int:
        """Get the number of attempts made in last execution."""
        return self._attempt_count


async def retry_operation(
    func: Callable[..., T],
    *args,
    config: RetryConfig | None = None,
    **kwargs
) -> T:
    """Execute a function with retry logic (functional API).

    Args:
        func: Function to execute
        *args: Positional arguments
        config: Retry configuration
        **kwargs: Keyword arguments

    Returns:
        Result of the function

    Example:
        result = await retry_operation(
            client.fetch_ticker,
            "BTC/USDT",
            config=RetryConfig(max_attempts=5)
        )
    """
    operation = RetryableOperation(func, config)
    return await operation.execute(*args, **kwargs)
