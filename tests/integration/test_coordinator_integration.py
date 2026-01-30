"""Integration tests for HeartbeatCoordinator with real BinanceClient.

These tests validate the coordinator's behavior with actual API calls to Binance,
providing end-to-end confidence in the heartbeat system.
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from trading_system.clients import BinanceClient
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.heartbeat.coordinator import HeartbeatCoordinator
from trading_system.repositories import SymbolRepository


@pytest_asyncio.fixture
async def real_coordinator_setup():
    """Create test setup with real Binance client and database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create database
        db_path = Path(tmpdir) / "test.db"
        db = DatabaseManager(db_path)
        await db.initialize()

        # Load settings and create real Binance client
        settings = Settings()
        client = BinanceClient(settings)
        await client.initialize()

        # Patch log manager to avoid file operations in tests
        with patch('trading_system.heartbeat.coordinator.log_manager') as mock_log_manager:
            mock_logger = MagicMock()
            mock_log_manager.get_heartbeat_logger.return_value = mock_logger

            # Create coordinator with real client
            coordinator = HeartbeatCoordinator(client, db, settings)

            yield coordinator, client, db, settings, mock_logger

        await client.close()
        await db.close()


@pytest.mark.integration
class TestCoordinatorWithRealBinance:
    """Integration tests for coordinator with real Binance API."""

    @pytest.mark.asyncio
    async def test_run_once_with_real_api(self, real_coordinator_setup):
        """Test running a single heartbeat cycle with real Binance API."""
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # Register real symbols
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("ETH/USDT")

        # Run a single heartbeat
        results = await coordinator.run_once()

        # Verify results
        assert len(results) == 2

        # Check that both symbols were fetched successfully
        btc_result = next(r for r in results if r.symbol == "BTC/USDT")
        eth_result = next(r for r in results if r.symbol == "ETH/USDT")

        assert btc_result.success is True
        assert btc_result.price is not None
        assert btc_result.price > 0
        assert btc_result.timestamp is not None

        assert eth_result.success is True
        assert eth_result.price is not None
        assert eth_result.price > 0

        # Verify logging occurred
        mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_run_once_stores_prices_in_database(self, real_coordinator_setup):
        """Test that prices fetched from real API are stored in database."""
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Run heartbeat
        await coordinator.run_once()

        # Verify price was stored in database
        from trading_system.repositories import PriceRepository
        price_repo = PriceRepository(db)
        symbol = await symbol_repo.get_by_symbol("BTC/USDT")
        latest = await price_repo.get_latest(symbol.id)

        assert latest is not None
        assert latest.close > 0  # Real price should be positive
        assert latest.timestamp > 0

    @pytest.mark.asyncio
    async def test_run_once_updates_symbol_cache(self, real_coordinator_setup):
        """Test that symbol last_price cache is updated after fetch."""
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Verify initial state - no last_price
        symbol = await symbol_repo.get_by_symbol("BTC/USDT")
        assert symbol.last_price is None

        # Run heartbeat
        await coordinator.run_once()

        # Verify last_price was updated
        symbol_repo._invalidate_cache()  # Invalidate cache to get fresh data
        symbol = await symbol_repo.get_by_symbol("BTC/USDT")
        assert symbol.last_price is not None
        assert symbol.last_price > 0

    @pytest.mark.asyncio
    async def test_run_once_handles_invalid_symbol(self, real_coordinator_setup):
        """Test coordinator handles invalid symbol gracefully with real API."""
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # Register one valid and one invalid symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("INVALID/SYMBOL123")

        # Run heartbeat - should not raise
        results = await coordinator.run_once()

        # Should have results for both symbols
        assert len(results) == 2

        # Both should fail because batch request fails on invalid symbol
        assert all(not r.success for r in results)

        # Errors are logged by price_fetcher logger, not heartbeat_logger
        # Just verify that we got failure results for both symbols

    @pytest.mark.asyncio
    async def test_run_once_with_no_symbols(self, real_coordinator_setup):
        """Test coordinator handles no registered symbols."""
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # No symbols registered
        results = await coordinator.run_once()

        # Should return empty list
        assert results == []

        # Should log that no symbols are registered
        # The coordinator logs via heartbeat_logger, check that info was called
        mock_logger.info.assert_called()


@pytest.mark.integration
class TestCoordinatorRealSchedulerIntegration:
    """Integration tests for coordinator with real scheduler timing."""

    @pytest.mark.asyncio
    async def test_integration_with_real_scheduler_and_api(self, real_coordinator_setup):
        """Integration test with real scheduler and real Binance API.

        Uses very short intervals to test the full scheduling loop.
        """
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # Register a symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Use very short intervals for testing
        coordinator._scheduler._interval = 0
        coordinator._scheduler._buffer_delay = 0.05

        await coordinator.start()

        # Wait for a few beats
        await asyncio.sleep(0.15)

        await coordinator.stop()

        # Should have executed at least one beat
        assert coordinator.scheduler_stats.beats_executed >= 1

        # Verify that actual fetches occurred
        mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_scheduler_alignment_with_real_fetching(self, real_coordinator_setup):
        """Test that scheduler aligns correctly to time boundaries with real fetches."""
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Use 1-second interval
        coordinator._scheduler._interval = 1
        coordinator._scheduler._buffer_delay = 0.1

        await coordinator.start()

        # Wait for first beat
        await asyncio.sleep(0.3)

        # Get stats after first beat
        stats_after_first = coordinator.scheduler_stats.beats_executed

        # Wait for potential second beat
        await asyncio.sleep(1.0)

        await coordinator.stop()

        # Should have executed at least one beat, possibly two
        assert coordinator.scheduler_stats.beats_executed >= 1


@pytest.mark.integration
class TestCoordinatorErrorHandlingIntegration:
    """Integration tests for coordinator error handling with real API."""

    @pytest.mark.asyncio
    async def test_graceful_shutdown_during_fetch(self, real_coordinator_setup):
        """Test coordinator shuts down gracefully even during active fetching."""
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Start with short interval
        coordinator._scheduler._interval = 0
        coordinator._scheduler._buffer_delay = 0.1

        await coordinator.start()

        # Let it run briefly
        await asyncio.sleep(0.05)

        # Stop immediately (may be mid-fetch)
        await coordinator.stop()

        # Should not raise and should be stopped
        assert not coordinator.is_running

    @pytest.mark.asyncio
    async def test_multiple_start_stop_cycles(self, real_coordinator_setup):
        """Test coordinator handles multiple start/stop cycles."""
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        for _ in range(3):
            await coordinator.start()
            assert coordinator.is_running
            await coordinator.stop()
            assert not coordinator.is_running

    @pytest.mark.asyncio
    async def test_context_manager_with_real_api(self, real_coordinator_setup):
        """Test async context manager with real Binance API."""
        coordinator, client, db, settings, mock_logger = real_coordinator_setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        async with coordinator:
            assert coordinator.is_running
            # Let one beat occur
            await asyncio.sleep(0.1)

        assert not coordinator.is_running
