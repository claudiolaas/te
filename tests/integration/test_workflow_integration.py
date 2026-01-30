"""End-to-end workflow integration tests.

These tests validate complete user workflows from start to finish,
using real components throughout the entire system.

Workflow: Register symbol → Backfill historical data → Heartbeat fetch → Verify data
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
from trading_system.repositories import PriceRepository, SymbolRepository
from trading_system.services import BackfillService


@pytest_asyncio.fixture
async def full_system_setup():
    """Create a complete system setup with all real components."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create database
        db_path = Path(tmpdir) / "test.db"
        db = DatabaseManager(db_path)
        await db.initialize()

        # Load settings
        settings = Settings()

        # Create real Binance client
        client = BinanceClient(settings)
        await client.initialize()

        # Create repositories
        symbol_repo = SymbolRepository(db)
        price_repo = PriceRepository(db)

        # Create services
        backfill_service = BackfillService(client, db, settings)

        # Patch log manager for coordinator
        with patch('trading_system.heartbeat.coordinator.log_manager') as mock_log_manager:
            mock_logger = MagicMock()
            mock_log_manager.get_heartbeat_logger.return_value = mock_logger

            # Create coordinator with real client
            coordinator = HeartbeatCoordinator(client, db, settings)

            yield {
                'db': db,
                'client': client,
                'settings': settings,
                'symbol_repo': symbol_repo,
                'price_repo': price_repo,
                'backfill_service': backfill_service,
                'coordinator': coordinator,
                'mock_logger': mock_logger,
                'tmpdir': tmpdir
            }

        await client.close()
        await db.close()


@pytest.mark.integration
class TestFullWorkflow:
    """End-to-end workflow tests with all real components."""

    @pytest.mark.asyncio
    async def test_register_symbol_backfill_and_fetch(self, full_system_setup):
        """Complete workflow: register symbol, backfill data, heartbeat fetch, verify."""
        setup = full_system_setup
        symbol_repo = setup['symbol_repo']
        price_repo = setup['price_repo']
        backfill_service = setup['backfill_service']
        coordinator = setup['coordinator']

        symbol = "BTC/USDT"

        # Step 1: Register the symbol
        registered = await symbol_repo.register(symbol)
        assert registered is not None
        assert registered.symbol == symbol
        assert registered.is_active is True

        # Verify symbol is in database
        all_symbols = await symbol_repo.list_active()
        assert len(all_symbols) == 1
        assert all_symbols[0].symbol == symbol

        # Step 2: Backfill historical data (last 30 minutes)
        backfill_result = await backfill_service.backfill_symbol(
            symbol=symbol,
            minutes=30
        )

        # Verify backfill completed
        assert backfill_result is not None
        print(f"Backfilled {len(backfill_result)} candles")

        # Step 3: Get symbol to check ID for price queries
        symbol_record = await symbol_repo.get_by_symbol(symbol)
        assert symbol_record is not None

        # Step 4: Run heartbeat fetch to get current price
        # Run once directly instead of using scheduler for predictable results
        results = await coordinator.run_once()

        # Verify fetch succeeded
        assert len(results) == 1
        assert results[0].success is True, f"Fetch failed: {results[0].error}"
        assert results[0].price is not None

        # Step 5: Verify current price was stored
        latest_price = await price_repo.get_latest(symbol_record.id)
        assert latest_price is not None
        assert latest_price.close > 0
        assert latest_price.timestamp > 0

        # Step 6: Verify symbol cache was updated
        # Clear cache to get fresh data from database
        symbol_repo._invalidate_cache()
        updated_symbol = await symbol_repo.get_by_symbol(symbol)
        assert updated_symbol.last_price is not None
        assert updated_symbol.last_price > 0
        assert updated_symbol.last_price_at is not None

        print(f"Latest price: {latest_price.close}")
        print(f"Symbol cache: {updated_symbol.last_price}")

    @pytest.mark.asyncio
    async def test_multiple_symbols_workflow(self, full_system_setup):
        """Test workflow with multiple symbols."""
        setup = full_system_setup
        symbol_repo = setup['symbol_repo']
        coordinator = setup['coordinator']

        symbols = ["BTC/USDT", "ETH/USDT"]

        # Step 1: Register multiple symbols
        for symbol in symbols:
            await symbol_repo.register(symbol)

        all_active = await symbol_repo.list_active()
        assert len(all_active) == 2

        # Step 2: Run heartbeat for all symbols
        results = await coordinator.run_once()

        # Should have results for both symbols
        assert len(results) == 2

        # Verify both succeeded
        for result in results:
            assert result.success is True
            assert result.price is not None
            assert result.price > 0

        # Step 3: Verify both symbols have cached prices
        # Invalidate cache to get fresh data with updated last_price
        symbol_repo._invalidate_cache()
        for symbol in symbols:
            symbol_record = await symbol_repo.get_by_symbol(symbol)
            assert symbol_record.last_price is not None
            assert symbol_record.last_price > 0

    @pytest.mark.asyncio
    async def test_symbol_lifecycle_workflow(self, full_system_setup):
        """Test complete symbol lifecycle: register, fetch, deactivate, reactivate."""
        setup = full_system_setup
        symbol_repo = setup['symbol_repo']
        coordinator = setup['coordinator']

        symbol = "BTC/USDT"

        # Register
        registered = await symbol_repo.register(symbol)
        assert registered.is_active is True

        # Fetch prices
        await coordinator.run_once()

        # Verify cache updated
        symbol_repo._invalidate_cache()
        symbol_record = await symbol_repo.get_by_symbol(symbol)
        assert symbol_record.last_price is not None

        # Deactivate using the coordinator's symbol repo to ensure cache is synchronized
        # This is necessary because the coordinator uses its own SymbolRepository instance
        coordinator_symbol_repo = coordinator._price_fetcher._symbol_repo
        symbol_record = await coordinator_symbol_repo.get_by_symbol(symbol)
        await coordinator_symbol_repo.deactivate(symbol_record.id)

        # Verify deactivated in coordinator's repo
        symbol_record = await coordinator_symbol_repo.get_by_symbol(symbol)
        assert symbol_record.is_active is False

        # Fetch should skip inactive symbol
        results = await coordinator.run_once()
        assert len(results) == 0  # No active symbols

        # Reactivate by re-registering (using coordinator's repo for consistency)
        await coordinator_symbol_repo.register(symbol)
        symbol_record = await coordinator_symbol_repo.get_by_symbol(symbol)
        assert symbol_record.is_active is True

        # Fetch should work again
        results = await coordinator.run_once()
        assert len(results) == 1
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_error_recovery_workflow(self, full_system_setup):
        """Test system recovers from errors during workflow."""
        setup = full_system_setup
        symbol_repo = setup['symbol_repo']
        coordinator = setup['coordinator']

        # Register valid and invalid symbols
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("INVALID/SYMBOL123")

        # Run heartbeat - should handle error gracefully
        results = await coordinator.run_once()

        # Both fail due to batch request failing on invalid symbol
        assert len(results) == 2
        assert all(not r.success for r in results)

        # System should still be operational
        # Deactivate invalid symbol using coordinator's repo to ensure cache sync
        coordinator_symbol_repo = coordinator._price_fetcher._symbol_repo
        invalid_symbol = await coordinator_symbol_repo.get_by_symbol("INVALID/SYMBOL123")
        await coordinator_symbol_repo.deactivate(invalid_symbol.id)

        # Now fetch should succeed for valid symbol
        results = await coordinator.run_once()

        assert len(results) == 1
        assert results[0].symbol == "BTC/USDT"
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_data_consistency_workflow(self, full_system_setup):
        """Test data consistency across multiple fetches."""
        setup = full_system_setup
        symbol_repo = setup['symbol_repo']
        price_repo = setup['price_repo']
        coordinator = setup['coordinator']

        symbol = "BTC/USDT"
        await symbol_repo.register(symbol)

        symbol_record = await symbol_repo.get_by_symbol(symbol)

        # Run multiple fetches
        prices_over_time = []
        for _ in range(3):
            results = await coordinator.run_once()
            if results and results[0].success:
                prices_over_time.append(results[0].price)

            # Small delay between fetches
            await asyncio.sleep(0.1)

        # Should have some prices
        assert len(prices_over_time) > 0

        # All prices should be positive
        assert all(p > 0 for p in prices_over_time)

        # Verify prices were stored in database using count method
        # Note: Prices with same minute timestamp overwrite each other due to
        # ON CONFLICT clause, so count may be less than number of fetches
        price_count = await price_repo.count(symbol_record.id)
        assert price_count >= 1  # At least one price should be stored

        # Latest price should match symbol cache
        latest = await price_repo.get_latest(symbol_record.id)
        symbol_repo._invalidate_cache()  # Invalidate to get fresh symbol data
        updated_symbol = await symbol_repo.get_by_symbol(symbol)
        assert latest.close == updated_symbol.last_price


@pytest.mark.integration
class TestBackfillIntegration:
    """Integration tests for backfill service with real Binance API."""

    @pytest.mark.asyncio
    async def test_backfill_real_historical_data(self, full_system_setup):
        """Test backfilling real historical data from Binance."""
        setup = full_system_setup
        symbol_repo = setup['symbol_repo']
        price_repo = setup['price_repo']
        backfill_service = setup['backfill_service']

        symbol = "BTC/USDT"
        await symbol_repo.register(symbol)

        symbol_record = await symbol_repo.get_by_symbol(symbol)

        # Backfill last 30 minutes
        result = await backfill_service.backfill_symbol(
            symbol=symbol,
            minutes=30
        )

        # Verify backfill completed (may have 0 records if no trades)
        assert result is not None

        # Get stored data count (get_all_for_symbol doesn't exist)
        price_count = await price_repo.count(symbol_record.id)
        all_prices = await price_repo.get_range(symbol_record.id, start_time=0, end_time=9999999999999)

        print(f"Backfilled {len(all_prices)} price records")

        # If data was fetched, verify structure
        if all_prices:
            for price in all_prices:
                assert price.open > 0
                assert price.high > 0
                assert price.low > 0
                assert price.close > 0
                assert price.timestamp > 0
                assert price.high >= price.low
                assert price.high >= price.open
                assert price.high >= price.close

    @pytest.mark.asyncio
    async def test_backfill_multiple_symbols(self, full_system_setup):
        """Test backfilling multiple symbols."""
        setup = full_system_setup
        symbol_repo = setup['symbol_repo']
        backfill_service = setup['backfill_service']

        symbols = ["BTC/USDT", "ETH/USDT"]
        for symbol in symbols:
            await symbol_repo.register(symbol)

        # Backfill each symbol (short period)
        for symbol in symbols:
            result = await backfill_service.backfill_symbol(
                symbol=symbol,
                minutes=10
            )
            assert result is not None
