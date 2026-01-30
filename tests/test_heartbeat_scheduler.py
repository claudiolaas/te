"""Tests for HeartbeatScheduler."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from trading_system.heartbeat.scheduler import HeartbeatScheduler, HeartbeatStats


class TestHeartbeatStats:
    """Tests for HeartbeatStats dataclass."""

    def test_default_values(self):
        """Test that HeartbeatStats has correct defaults."""
        stats = HeartbeatStats()

        assert stats.beats_executed == 0
        assert stats.beats_failed == 0
        assert stats.start_time is None
        assert stats.last_beat_time is None

    def test_uptime_seconds_no_start(self):
        """Test uptime calculation when not started."""
        stats = HeartbeatStats()
        assert stats.uptime_seconds == 0.0

    def test_uptime_seconds_with_start(self):
        """Test uptime calculation when running."""
        stats = HeartbeatStats()
        stats.start_time = datetime.now(UTC)

        # Should be very small but positive
        assert stats.uptime_seconds >= 0.0


class TestHeartbeatScheduler:
    """Tests for HeartbeatScheduler class."""

    @pytest.fixture
    def mock_handler(self):
        """Create a mock beat handler."""
        return AsyncMock()

    @pytest.fixture
    def scheduler(self, mock_handler):
        """Create a heartbeat scheduler for testing."""
        return HeartbeatScheduler(
            interval_seconds=60,
            buffer_delay_seconds=5,
            handler=mock_handler,
            name="test_heartbeat"
        )

    @pytest.mark.asyncio
    async def test_initialization(self, scheduler, mock_handler):
        """Test that scheduler initializes correctly."""
        assert scheduler._interval == 60
        assert scheduler._buffer_delay == 5
        assert scheduler._handler is mock_handler
        assert scheduler._name == "test_heartbeat"
        assert scheduler.effective_interval == 65
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_start_sets_running(self, scheduler):
        """Test that start() sets running state."""
        await scheduler.start()

        assert scheduler.is_running
        assert scheduler.stats.start_time is not None

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, scheduler):
        """Test that stop() clears running state."""
        await scheduler.start()
        await scheduler.stop()

        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, scheduler):
        """Test that stop() handles not running gracefully."""
        # Should not raise
        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_start_when_already_running(self, scheduler):
        """Test that start() handles already running gracefully."""
        await scheduler.start()

        # Starting again should not raise, just log warning
        await scheduler.start()

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_handler_called_on_beat(self, scheduler, mock_handler):
        """Test that handler is called on each beat."""
        # Use very short interval for testing
        scheduler._interval = 0
        scheduler._buffer_delay = 0.05  # 50ms for fast test

        await scheduler.start()

        # Wait for a few beats
        await asyncio.sleep(0.15)

        await scheduler.stop()

        # Handler should have been called at least once
        assert mock_handler.call_count >= 1

    @pytest.mark.asyncio
    async def test_beat_number_increments(self, scheduler, mock_handler):
        """Test that beat number increments correctly."""
        scheduler._interval = 0
        scheduler._buffer_delay = 0.05

        await scheduler.start()
        await asyncio.sleep(0.15)
        await scheduler.stop()

        # Check that beat numbers were passed correctly
        calls = mock_handler.call_args_list
        for i, call in enumerate(calls, 1):
            assert call[0][0] == i  # First arg should be beat number

    @pytest.mark.asyncio
    async def test_handler_error_does_not_stop_heartbeat(self, scheduler, mock_handler):
        """Test that handler errors don't stop the heartbeat."""
        mock_handler.side_effect = [ValueError("Test error"), None, None]

        scheduler._interval = 0
        scheduler._buffer_delay = 0.05

        await scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()

        # Should have attempted multiple beats despite error
        assert mock_handler.call_count >= 2
        assert scheduler.stats.beats_failed >= 1

    @pytest.mark.asyncio
    async def test_stats_tracking(self, scheduler, mock_handler):
        """Test that statistics are tracked correctly."""
        scheduler._interval = 0
        scheduler._buffer_delay = 0.05

        await scheduler.start()
        await asyncio.sleep(0.15)
        await scheduler.stop()

        stats = scheduler.stats
        assert stats.beats_executed >= 1
        assert stats.last_beat_time is not None
        assert stats.uptime_seconds > 0

    @pytest.mark.asyncio
    async def test_graceful_shutdown_with_signal(self, scheduler, mock_handler):
        """Test graceful shutdown on signal."""
        scheduler._interval = 0
        scheduler._buffer_delay = 0.1

        await scheduler.start()

        # Wait a bit
        await asyncio.sleep(0.05)

        # Simulate signal
        scheduler._signal_handler()

        # Give time for shutdown
        await asyncio.sleep(0.1)

        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_handler):
        """Test async context manager."""
        scheduler = HeartbeatScheduler(
            interval_seconds=0,
            buffer_delay_seconds=0.05,
            handler=mock_handler,
            name="test"
        )

        async with scheduler:
            assert scheduler.is_running
            await asyncio.sleep(0.1)

        assert not scheduler.is_running

    def test_calculate_initial_delay(self, scheduler):
        """Test initial delay calculation."""
        delay = scheduler._calculate_initial_delay()

        # Should be between buffer_delay and effective_interval + buffer
        assert 0 <= delay <= scheduler.effective_interval + 1

    def test_calculate_next_beat_delay(self, scheduler):
        """Test next beat delay calculation."""
        delay = scheduler._calculate_next_beat_delay()

        # Should be positive and around the effective interval
        assert delay > 0
        assert delay <= scheduler.effective_interval + 1


class TestHeartbeatSchedulerEdgeCases:
    """Edge case tests for HeartbeatScheduler."""

    @pytest.mark.asyncio
    async def test_stop_event_during_initial_delay(self):
        """Test that stop during initial delay works."""
        handler = AsyncMock()
        scheduler = HeartbeatScheduler(
            interval_seconds=60,  # Long interval
            buffer_delay_seconds=5,
            handler=handler
        )

        # Start and immediately stop
        await scheduler.start()
        await scheduler.stop()

        # Handler should not have been called
        assert handler.call_count == 0

    @pytest.mark.asyncio
    async def test_rapid_start_stop(self):
        """Test rapid start/stop cycles."""
        handler = AsyncMock()
        scheduler = HeartbeatScheduler(
            interval_seconds=0,
            buffer_delay_seconds=0.01,
            handler=handler
        )

        for _ in range(3):
            await scheduler.start()
            await asyncio.sleep(0.02)
            await scheduler.stop()

        # Should handle cycles gracefully
        assert not scheduler.is_running
