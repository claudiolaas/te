"""Tests for retry configuration using tenacity."""

from unittest.mock import AsyncMock

import ccxt
import pytest
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from trading_system.utils.retry import DEFAULT_RETRY


class TestDefaultRetry:
    """Tests for DEFAULT_RETRY configuration."""

    def test_default_retry_has_required_keys(self):
        """Test that DEFAULT_RETRY contains all tenacity configuration keys."""
        assert "stop" in DEFAULT_RETRY
        assert "wait" in DEFAULT_RETRY
        assert "retry" in DEFAULT_RETRY

    def test_default_retry_stop_config(self):
        """Test that stop is configured for 3 attempts."""
        from tenacity.stop import stop_after_attempt

        stop_config = DEFAULT_RETRY["stop"]
        assert isinstance(stop_config, stop_after_attempt)
        assert stop_config.max_attempt_number == 3

    def test_default_retry_wait_config(self):
        """Test that wait is configured with exponential backoff."""
        from tenacity.wait import wait_exponential

        wait_config = DEFAULT_RETRY["wait"]
        assert isinstance(wait_config, wait_exponential)
        assert wait_config.min == 1
        assert wait_config.max == 60

    def test_default_retry_exception_types(self):
        """Test that retry is configured for CCXT exceptions."""
        from tenacity.retry import retry_if_exception_type

        retry_config = DEFAULT_RETRY["retry"]
        assert isinstance(retry_config, retry_if_exception_type)
        assert retry_config.exception_types == (
            ccxt.NetworkError,
            ccxt.ExchangeNotAvailable,
            ccxt.RequestTimeout,
        )


class TestRetryBehavior:
    """Tests for retry behavior with tenacity."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Test that successful call doesn't retry."""
        mock_func = AsyncMock(return_value="success")

        @retry(**DEFAULT_RETRY)
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self):
        """Test that NetworkError triggers retry."""
        mock_func = AsyncMock(
            side_effect=[
                ccxt.NetworkError("Connection failed"),
                ccxt.NetworkError("Still failed"),
                "success",
            ]
        )

        # Use shorter wait for faster tests
        config = dict(
            DEFAULT_RETRY,
            wait=wait_exponential(min=0.01, max=0.1),
        )

        @retry(**config)
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded(self):
        """Test that max attempts raises final exception."""
        mock_func = AsyncMock(side_effect=ccxt.NetworkError("Always fails"))

        # Use shorter wait for faster tests
        config = dict(
            DEFAULT_RETRY,
            wait=wait_exponential(min=0.01, max=0.1),
        )

        @retry(**config)
        async def test_func():
            return await mock_func()

        with pytest.raises(ccxt.NetworkError, match="Always fails"):
            await test_func()

        assert mock_func.call_count == 3

        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_exception(self):
        """Test that non-retryable exceptions are raised immediately."""
        mock_func = AsyncMock(side_effect=ValueError("Bad input"))

        @retry(**DEFAULT_RETRY)
        async def test_func():
            return await mock_func()

        with pytest.raises(ValueError, match="Bad input"):
            await test_func()

        assert mock_func.call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_custom_retryable_exceptions(self):
        """Test custom retryable exceptions list."""
        mock_func = AsyncMock(
            side_effect=[
                ValueError("Retry this"),
                "success",
            ]
        )

        custom_config = dict(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=0.01, max=0.1),
            retry=retry_if_exception_type(ValueError),
            reraise=True,
        )

        @retry(**custom_config)
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
    @pytest.mark.asyncio
    async def test_custom_attempt_count(self):
        """Test custom max attempts."""
        mock_func = AsyncMock(
            side_effect=[
                ccxt.NetworkError("Failed"),
                "success",
            ]
        )

        custom_config = dict(
            DEFAULT_RETRY,
            stop=stop_after_attempt(2),
            wait=wait_exponential(min=0.01, max=0.1),
        )

        @retry(**custom_config)
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
        assert mock_func.call_count == 2
