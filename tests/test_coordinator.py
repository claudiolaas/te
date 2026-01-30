"""Tests for HeartbeatCoordinator."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trading_system.clients import BinanceClient
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.heartbeat.coordinator import HeartbeatCoordinator


class TestHeartbeatCoordinator:
    """Tests for HeartbeatCoordinator class."""

    @pytest.fixture
    async def setup(self):
        """Create test setup with mocked components."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create database
            db_path = Path(tmpdir) / "test.db"
            db = DatabaseManager(db_path)
            await db.initialize()

            # Create settings
            settings = Settings(
                binance_api_key="test_key",
                binance_api_secret="test_secret",
                heartbeat_interval=60,
                heartbeat_buffer_delay=5
            )

            # Create mocked Binance client
            mock_client = MagicMock(spec=BinanceClient)

            # Patch the log manager to avoid file operations
            with patch('trading_system.heartbeat.coordinator.log_manager') as mock_log_manager:
                mock_logger = MagicMock()
                mock_log_manager.get_heartbeat_logger.return_value = mock_logger

                # Create coordinator
                coordinator = HeartbeatCoordinator(mock_client, db, settings)

                yield coordinator, mock_client, db, settings, mock_logger

            await db.close()

    @pytest.mark.asyncio
    async def test_initialization(self, setup):
        """Test that coordinator initializes correctly."""
        coordinator, mock_client, db, settings, _ = setup

        assert coordinator._binance is mock_client
        assert coordinator._db is db
        assert coordinator._settings is settings
        assert not coordinator.is_running
        assert coordinator._scheduler is not None
        assert coordinator._price_fetcher is not None

    @pytest.mark.asyncio
    async def test_start_sets_running(self, setup):
        """Test that start() sets running state."""
        coordinator, _, _, _, mock_logger = setup

        await coordinator.start()

        assert coordinator.is_running
        mock_logger.info.assert_called()

        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, setup):
        """Test that stop() clears running state."""
        coordinator, _, _, _, _ = setup

        await coordinator.start()
        await coordinator.stop()

        assert not coordinator.is_running

    @pytest.mark.asyncio
    async def test_start_when_already_running(self, setup):
        """Test that start() handles already running gracefully."""
        coordinator, _, _, _, _ = setup

        await coordinator.start()
        await coordinator.start()  # Second start should not raise

        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, setup):
        """Test that stop() handles not running gracefully."""
        coordinator, _, _, _, _ = setup

        # Should not raise
        await coordinator.stop()

    @pytest.mark.asyncio
    async def test_run_once(self, setup):
        """Test running a single heartbeat cycle."""
        coordinator, mock_client, db, _, mock_logger = setup

        # Register a symbol
        from trading_system.repositories import SymbolRepository
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Mock price fetcher
        from trading_system.heartbeat.price_fetcher import PriceFetchResult
        mock_results = [
            PriceFetchResult(symbol="BTC/USDT", price=50000.0, timestamp=1234567890000, success=True)
        ]

        with patch.object(coordinator._price_fetcher, 'fetch_all', return_value=mock_results):
            results = await coordinator.run_once()

        assert len(results) == 1
        assert results[0].symbol == "BTC/USDT"
        mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_on_beat_logs_success(self, setup):
        """Test that successful beat is logged correctly."""
        coordinator, _, _, _, mock_logger = setup

        # Mock price fetcher results
        from trading_system.heartbeat.price_fetcher import PriceFetchResult
        mock_results = [
            PriceFetchResult(symbol="BTC/USDT", price=50000.0, timestamp=1234567890000, success=True),
            PriceFetchResult(symbol="ETH/USDT", price=3000.0, timestamp=1234567890000, success=True)
        ]

        with patch.object(coordinator._price_fetcher, 'fetch_all', return_value=mock_results):
            await coordinator._on_beat(1)

        # Check that beat was logged
        log_calls = [call for call in mock_logger.method_calls if 'beat' in str(call).lower()]
        assert len(log_calls) >= 2  # Start and complete logs

    @pytest.mark.asyncio
    async def test_on_beat_logs_failures(self, setup):
        """Test that failed symbols are logged."""
        coordinator, _, _, _, mock_logger = setup

        # Mock price fetcher results with failure
        from trading_system.heartbeat.price_fetcher import PriceFetchResult
        mock_results = [
            PriceFetchResult(symbol="BTC/USDT", price=50000.0, timestamp=1234567890000, success=True),
            PriceFetchResult(symbol="ETH/USDT", price=None, timestamp=None, success=False, error="API Error")
        ]

        with patch.object(coordinator._price_fetcher, 'fetch_all', return_value=mock_results):
            await coordinator._on_beat(1)

        # Check that failure was logged
        warning_calls = [call for call in mock_logger.warning.call_args_list if 'ETH' in str(call)]
        assert len(warning_calls) > 0

    @pytest.mark.asyncio
    async def test_on_beat_handles_exception(self, setup):
        """Test that exceptions in beat don't stop heartbeat."""
        coordinator, _, _, _, mock_logger = setup

        # Make price fetcher raise exception
        with patch.object(coordinator._price_fetcher, 'fetch_all', side_effect=Exception("Unexpected error")):
            await coordinator._on_beat(1)

        # Error should be logged but not raised
        error_calls = [call for call in mock_logger.error.call_args_list]
        assert len(error_calls) > 0

    @pytest.mark.asyncio
    async def test_on_beat_no_symbols(self, setup):
        """Test beat when no symbols are registered."""
        coordinator, _, _, _, mock_logger = setup

        # Mock empty results
        with patch.object(coordinator._price_fetcher, 'fetch_all', return_value=[]):
            await coordinator._on_beat(1)

        # Should log that no symbols are registered
        info_calls = str(mock_logger.info.call_args_list)
        assert 'no symbols' in info_calls.lower() or '0/0' in info_calls

    @pytest.mark.asyncio
    async def test_context_manager(self, setup):
        """Test async context manager."""
        coordinator, _, _, _, _ = setup

        async with coordinator:
            assert coordinator.is_running

        assert not coordinator.is_running

    @pytest.mark.asyncio
    async def test_scheduler_stats(self, setup):
        """Test that scheduler stats are accessible."""
        coordinator, _, _, _, _ = setup

        stats = coordinator.scheduler_stats

        assert stats is not None
        assert stats.beats_executed == 0  # Not started yet

    @pytest.mark.asyncio
    async def test_integration_with_real_scheduler(self, setup):
        """Integration test with real scheduler (short interval)."""
        coordinator, _, _, settings, _ = setup

        # Use very short intervals for testing
        coordinator._scheduler._interval = 0
        coordinator._scheduler._buffer_delay = 0.05

        # Mock price fetcher
        from trading_system.heartbeat.price_fetcher import PriceFetchResult
        mock_results = [PriceFetchResult(symbol="BTC/USDT", price=50000.0, timestamp=1234567890000, success=True)]

        with patch.object(coordinator._price_fetcher, 'fetch_all', return_value=mock_results):
            await coordinator.start()

            # Wait for a few beats
            await asyncio.sleep(0.15)

            await coordinator.stop()

        # Should have executed multiple beats
        assert coordinator.scheduler_stats.beats_executed >= 1


# Need to import asyncio for the integration test
import asyncio
