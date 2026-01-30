"""Tests for retry logic."""

from unittest.mock import AsyncMock, MagicMock

import ccxt
import pytest

from trading_system.utils import RetryableOperation, RetryConfig, retry_operation, with_retry


class TestRetryConfig:
    """Tests for RetryConfig class."""

    def test_default_values(self):
        """Test that RetryConfig has sensible defaults."""
        config = RetryConfig()

        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
        assert ccxt.NetworkError in config.retryable_exceptions

    def test_custom_values(self):
        """Test that RetryConfig accepts custom values."""
        config = RetryConfig(
            max_attempts=5,
            base_delay=2.0,
            max_delay=30.0,
            exponential_base=3.0
        )

        assert config.max_attempts == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 30.0
        assert config.exponential_base == 3.0

    def test_calculate_delay_exponential(self):
        """Test exponential delay calculation."""
        config = RetryConfig(base_delay=1.0, exponential_base=2.0)

        assert config.calculate_delay(0) == 1.0   # 1 * 2^0
        assert config.calculate_delay(1) == 2.0   # 1 * 2^1
        assert config.calculate_delay(2) == 4.0   # 1 * 2^2
        assert config.calculate_delay(3) == 8.0   # 1 * 2^3

    def test_calculate_delay_respects_max(self):
        """Test that delay is capped at max_delay."""
        config = RetryConfig(base_delay=10.0, max_delay=50.0, exponential_base=2.0)

        assert config.calculate_delay(0) == 10.0
        assert config.calculate_delay(1) == 20.0
        assert config.calculate_delay(2) == 40.0
        assert config.calculate_delay(3) == 50.0  # Capped
        assert config.calculate_delay(4) == 50.0  # Capped


class TestWithRetryDecorator:
    """Tests for @with_retry decorator."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Test that successful call doesn't retry."""
        mock_func = AsyncMock(return_value="success")

        @with_retry(RetryConfig(max_attempts=3))
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self):
        """Test that NetworkError triggers retry."""
        mock_func = AsyncMock(side_effect=[
            ccxt.NetworkError("Connection failed"),
            ccxt.NetworkError("Still failed"),
            "success"
        ])

        @with_retry(RetryConfig(max_attempts=3, base_delay=0.01))
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded(self):
        """Test that max attempts raises final exception."""
        mock_func = AsyncMock(side_effect=ccxt.NetworkError("Always fails"))

        @with_retry(RetryConfig(max_attempts=3, base_delay=0.01))
        async def test_func():
            return await mock_func()

        with pytest.raises(ccxt.NetworkError, match="Always fails"):
            await test_func()

        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_exception(self):
        """Test that non-retryable exceptions are raised immediately."""
        mock_func = AsyncMock(side_effect=ValueError("Bad input"))

        @with_retry(RetryConfig(max_attempts=3))
        async def test_func():
            return await mock_func()

        with pytest.raises(ValueError, match="Bad input"):
            await test_func()

        assert mock_func.call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_custom_retryable_exceptions(self):
        """Test custom retryable exceptions list."""
        mock_func = AsyncMock(side_effect=[
            ValueError("Retry this"),
            "success"
        ])

        config = RetryConfig(
            max_attempts=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError,)
        )

        @with_retry(config)
        async def test_func():
            return await mock_func()

        result = await test_func()

        assert result == "success"
        assert mock_func.call_count == 2

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        """Test that on_retry callback is called."""
        mock_func = AsyncMock(side_effect=[
            ccxt.NetworkError("Failed"),
            "success"
        ])
        on_retry_mock = MagicMock()

        @with_retry(
            RetryConfig(max_attempts=3, base_delay=0.01),
            on_retry=on_retry_mock
        )
        async def test_func():
            return await mock_func()

        await test_func()

        assert on_retry_mock.call_count == 1
        args = on_retry_mock.call_args[0]
        assert isinstance(args[0], ccxt.NetworkError)
        assert args[1] == 0  # First retry attempt
        assert args[2] == 0.01  # Delay


class TestRetryableOperation:
    """Tests for RetryableOperation class."""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Test successful execution."""
        mock_func = AsyncMock(return_value="success")

        op = RetryableOperation(mock_func, RetryConfig(max_attempts=3))
        result = await op.execute()

        assert result == "success"
        assert op.attempt_count == 1

    @pytest.mark.asyncio
    async def test_execute_with_retry(self):
        """Test execution with retries."""
        mock_func = AsyncMock(side_effect=[
            ccxt.NetworkError("Failed"),
            ccxt.NetworkError("Failed again"),
            "success"
        ])

        op = RetryableOperation(mock_func, RetryConfig(max_attempts=3, base_delay=0.01))
        result = await op.execute()

        assert result == "success"
        assert op.attempt_count == 3

    @pytest.mark.asyncio
    async def test_execute_max_attempts(self):
        """Test that max attempts raises exception."""
        mock_func = AsyncMock(side_effect=ccxt.NetworkError("Always fails"))

        op = RetryableOperation(mock_func, RetryConfig(max_attempts=3, base_delay=0.01))

        with pytest.raises(ccxt.NetworkError):
            await op.execute()

        assert op.attempt_count == 3

    @pytest.mark.asyncio
    async def test_execute_with_args(self):
        """Test execution with arguments."""
        mock_func = AsyncMock(return_value="success")

        op = RetryableOperation(mock_func)
        result = await op.execute("arg1", "arg2", key="value")

        assert result == "success"
        mock_func.assert_called_once_with("arg1", "arg2", key="value")


class TestRetryOperationFunction:
    """Tests for retry_operation function."""

    @pytest.mark.asyncio
    async def test_retry_operation_success(self):
        """Test retry_operation with success."""
        mock_func = AsyncMock(return_value="success")

        result = await retry_operation(
            mock_func,
            "arg1",
            config=RetryConfig(max_attempts=3),
            key="value"
        )

        assert result == "success"
        mock_func.assert_called_once_with("arg1", key="value")

    @pytest.mark.asyncio
    async def test_retry_operation_with_retries(self):
        """Test retry_operation with retries."""
        mock_func = AsyncMock(side_effect=[
            ccxt.NetworkError("Failed"),
            "success"
        ])

        result = await retry_operation(
            mock_func,
            config=RetryConfig(max_attempts=3, base_delay=0.01)
        )

        assert result == "success"
        assert mock_func.call_count == 2


class TestSyncFunctionRetry:
    """Tests for sync function retry."""

    def test_sync_function_retry(self):
        """Test that sync functions are handled."""
        call_count = 0

        def sync_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ccxt.NetworkError("Failed")
            return "success"

        @with_retry(RetryConfig(max_attempts=3))
        def test_func():
            return sync_func()

        result = test_func()

        assert result == "success"
        assert call_count == 3
