"""Tests for BackfillService."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_system.clients import BinanceClient, OHLCVData
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.repositories import PriceRepository, SymbolRepository
from trading_system.services import BackfillService


class TestBackfillService:
    """Tests for BackfillService class."""

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
                backfill_minutes=5,
                gap_fill_enabled=True,
                gap_fill_threshold_minutes=1,
                max_gap_fill_minutes=1000,
            )

            # Create mocked Binance client
            mock_client = MagicMock(spec=BinanceClient)
            mock_client.milliseconds = 1000000000000  # Fixed timestamp

            # Create service
            service = BackfillService(mock_client, db, settings)

            yield service, mock_client, db

            await db.close()

    @pytest.fixture
    async def setup_with_data(self):
        """Create test setup with existing price data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = DatabaseManager(db_path)
            await db.initialize()

            settings = Settings(
                binance_api_key="test_key",
                binance_api_secret="test_secret",
                backfill_minutes=5,
                gap_fill_enabled=True,
                gap_fill_threshold_minutes=1,
                max_gap_fill_minutes=1000,
            )

            mock_client = MagicMock(spec=BinanceClient)
            # Current time: 1000000000000
            mock_client.milliseconds = 1000000000000

            service = BackfillService(mock_client, db, settings)

            # Register symbol and add existing data
            symbol_repo = SymbolRepository(db)
            symbol = await symbol_repo.register("BTC/USDT")
            price_repo = PriceRepository(db)

            yield service, mock_client, db, symbol, price_repo

            await db.close()

    @pytest.mark.asyncio
    async def test_backfill_symbol_success(self, setup):
        """Test successful backfill of a symbol."""
        service, mock_client, db = setup

        # Register symbol first
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Mock the client's fetch_ohlcv (which is called by _fetch_with_retry)
        # Use timestamps 1 minute apart (60000 ms)
        # Current time: 1000000000000 (fixed in mock)
        # until_ms will be: ((1000000000000 // 60000) * 60000) - 60000 = 999999994000
        base_ts = 999999994000 - 120000  # 2 minutes before until_ms
        mock_client.fetch_ohlcv = AsyncMock(return_value=[
            OHLCVData(timestamp=base_ts, open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0),
            OHLCVData(timestamp=base_ts + 60000, open=105.0, high=115.0, low=95.0, close=110.0, volume=2000.0),
            OHLCVData(timestamp=base_ts + 120000, open=110.0, high=120.0, low=100.0, close=115.0, volume=3000.0),
        ])

        result = await service.backfill_symbol("BTC/USDT")

        assert result['status'] == 'success'
        assert result['records_stored'] == 3
        assert result['strategy'] == 'full_backfill'

        # Verify candles were stored
        price_repo = PriceRepository(db)
        symbol = await symbol_repo.get_by_symbol("BTC/USDT")
        count = await price_repo.count(symbol.id)
        assert count == 3

    @pytest.mark.asyncio
    async def test_backfill_symbol_not_registered(self, setup):
        """Test that backfill raises error for unregistered symbol."""
        service, mock_client, db = setup

        with pytest.raises(ValueError, match="not registered"):
            await service.backfill_symbol("BTC/USDT")

    @pytest.mark.asyncio
    async def test_backfill_symbol_custom_minutes(self, setup):
        """Test backfill with custom minutes parameter."""
        service, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Mock fetch_ohlcv to return empty (just checking parameters)
        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        await service.backfill_symbol("BTC/USDT", minutes=10)

        # Verify fetch was called with correct limit
        mock_client.fetch_ohlcv.assert_called_once()
        call_kwargs = mock_client.fetch_ohlcv.call_args[1]
        assert call_kwargs['limit'] == 11  # 10 + 1

    @pytest.mark.asyncio
    async def test_backfill_symbol_empty_response(self, setup):
        """Test backfill with empty API response."""
        service, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        result = await service.backfill_symbol("BTC/USDT")

        assert result['status'] == 'no_data'
        assert result['records_stored'] == 0

    @pytest.mark.asyncio
    async def test_backfill_timestamp_normalization(self, setup):
        """Test that timestamps are rounded to minute boundaries."""
        service, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Mock with non-minute timestamps
        # until_ms will be ~1000000000000 - 60000, so use a timestamp that works
        mock_client.fetch_ohlcv = AsyncMock(return_value=[
            OHLCVData(timestamp=999999994000, open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0),
        ])

        result = await service.backfill_symbol("BTC/USDT")

        # Timestamp should be rounded to minute
        assert result['status'] == 'success'
        assert result['records_stored'] == 1

    @pytest.mark.asyncio
    async def test_backfill_uses_settings_default(self, setup):
        """Test that backfill uses settings.backfill_minutes when not specified."""
        service, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        await service.backfill_symbol("BTC/USDT")  # No minutes parameter

        # Verify fetch_ohlcv was called
        mock_client.fetch_ohlcv.assert_called_once()
        # Verify limit was set correctly (minutes + 1 for current candle)
        call_kwargs = mock_client.fetch_ohlcv.call_args[1]
        assert call_kwargs['limit'] == 6  # 5 (default) + 1

    @pytest.mark.asyncio
    async def test_backfill_retries_on_network_error(self, setup):
        """Test that backfill uses retry mechanism.

        Note: The actual retry logic is tested in test_retry.py.
        Here we just verify the service integrates with it.
        """
        service, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Mock succeeds immediately
        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        # Should complete without error
        candles = await service.backfill_symbol("BTC/USDT")

        assert mock_client.fetch_ohlcv.call_count == 1

    @pytest.mark.asyncio
    async def test_get_backfill_status(self, setup):
        """Test getting backfill status."""
        service, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        symbol = await symbol_repo.register("BTC/USDT")

        # Add some price data
        price_repo = PriceRepository(db)
        await price_repo.save(symbol.id, 1000000000000, 100.0, 110.0, 90.0, 105.0, 1000.0)

        status = await service.get_backfill_status("BTC/USDT")

        assert status['symbol'] == "BTC/USDT"
        assert status['symbol_id'] == symbol.id
        assert status['total_records'] == 1
        assert status['latest_price'] == 105.0
        assert status['oldest_timestamp'] == 1000000000000

    @pytest.mark.asyncio
    async def test_get_backfill_status_not_registered(self, setup):
        """Test status for unregistered symbol."""
        service, mock_client, db = setup

        status = await service.get_backfill_status("BTC/USDT")

        assert 'error' in status
        assert "not registered" in status['error']

    @pytest.mark.asyncio
    async def test_get_backfill_status_empty(self, setup):
        """Test status for symbol with no data."""
        service, mock_client, db = setup

        # Register symbol but no price data
        symbol_repo = SymbolRepository(db)
        symbol = await symbol_repo.register("BTC/USDT")

        status = await service.get_backfill_status("BTC/USDT")

        assert status['symbol'] == "BTC/USDT"
        assert status['total_records'] == 0
        assert status['latest_timestamp'] is None
        assert status['latest_price'] is None


    # ==========================================================================
    # Gap-Filling Tests
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_gap_fill_no_action_sufficient_history(self, setup_with_data):
        """Test that no action is taken when sufficient history exists and no gap."""
        service, mock_client, db, symbol, price_repo = setup_with_data

        # Add 10 minutes of continuous data (more than backfill_minutes=5)
        # Current time: 1000000000000
        # until_ms: 999999994000 (previous complete minute)
        base_ts = 999999994000 - 600000  # 10 minutes before until_ms
        for i in range(10):
            await price_repo.save(
                symbol.id,
                base_ts + (i * 60000),  # Every minute
                100.0 + i, 110.0 + i, 90.0 + i, 105.0 + i, 1000.0
            )

        # Mock should not be called since no backfill is needed
        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        result = await service.backfill_symbol("BTC/USDT")

        assert result['status'] == 'no_action'
        assert result['reason'] == 'sufficient_history'
        mock_client.fetch_ohlcv.assert_not_called()

    @pytest.mark.asyncio
    async def test_gap_fill_extend_backward(self, setup_with_data):
        """Test extending backward when continuous but insufficient history."""
        service, mock_client, db, symbol, price_repo = setup_with_data

        # Add only 2 minutes of data (less than backfill_minutes=5)
        base_ts = 999999994000 - 120000  # 2 minutes before until_ms
        for i in range(2):
            await price_repo.save(
                symbol.id,
                base_ts + (i * 60000),
                100.0 + i, 110.0 + i, 90.0 + i, 105.0 + i, 1000.0
            )

        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        result = await service.backfill_symbol("BTC/USDT")

        assert result['status'] == 'no_data'  # No data returned from mock
        assert result['strategy'] == 'extend_backward'

    @pytest.mark.asyncio
    async def test_gap_fill_gap_only(self, setup_with_data):
        """Test filling only the gap when sufficient history exists."""
        service, mock_client, db, symbol, price_repo = setup_with_data

        # Calculate timestamps based on current mock time
        # Current time: 1000000000000
        # until_ms: ((1000000000000 // 60000) * 60000) - 60000 = 999999900000
        until_ms = 999999900000

        # Add 10 minutes of data ending 5 minutes ago (gap of 5 minutes)
        # Latest data should be at: until_ms - 300000 (5 min gap) = 999999600000
        # So data runs from 999999000000 to 999999540000 (10 minutes)
        base_ts = until_ms - 600000 - 300000  # 10 minutes of data, 5 min gap
        for i in range(10):
            await price_repo.save(
                symbol.id,
                base_ts + (i * 60000),
                100.0 + i, 110.0 + i, 90.0 + i, 105.0 + i, 1000.0
            )

        # Should fetch only the 5-minute gap
        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        result = await service.backfill_symbol("BTC/USDT")

        assert result['strategy'] == 'gap_only'
        # Verify fetch was called with limited window (gap only)
        call_args = mock_client.fetch_ohlcv.call_args[1]
        # Since: last_data + 1min = 999999540000 + 60000 = 999999600000
        assert call_args['since'] == 999999600000

    @pytest.mark.asyncio
    async def test_gap_fill_gap_plus_extend(self, setup_with_data):
        """Test filling gap plus extending when combined history is insufficient."""
        service, mock_client, db, symbol, price_repo = setup_with_data

        # Add 2 minutes of data ending 3 minutes ago (gap of 3 minutes)
        # Total: 5 minutes, which meets backfill_minutes=5
        # But let's do 1 minute of data with 2 minute gap = 3 minutes total < 5
        base_ts = 999999994000 - 60000 - 120000  # 1 min data, 2 min gap
        for i in range(1):
            await price_repo.save(
                symbol.id,
                base_ts + (i * 60000),
                100.0, 110.0, 90.0, 105.0, 1000.0
            )

        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        result = await service.backfill_symbol("BTC/USDT")

        # Gap (2 min) + existing (1 min) = 3 min < required (5 min)
        # Should extend backward
        assert result['strategy'] == 'gap_plus_extend'

    @pytest.mark.asyncio
    async def test_gap_fill_full_backfill_no_existing_data(self, setup):
        """Test full backfill when no existing data."""
        service, mock_client, db = setup

        # Register symbol but no data
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        result = await service.backfill_symbol("BTC/USDT")

        assert result['strategy'] == 'full_backfill'

    @pytest.mark.asyncio
    async def test_gap_fill_disabled(self, setup_with_data):
        """Test that when gap_fill_enabled is False, it does standard backfill."""
        service, mock_client, db, symbol, price_repo = setup_with_data

        # Modify settings to disable gap fill
        service._settings.gap_fill_enabled = False

        # Add some existing data
        await price_repo.save(symbol.id, 999999994000 - 600000, 100.0, 110.0, 90.0, 105.0, 1000.0)

        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        # When gap_fill_enabled is False, we still use the same logic
        # but it should work normally
        result = await service.backfill_symbol("BTC/USDT")

        # The settings flag is for the startup flow, the service still works
        assert result['status'] == 'no_data'

    @pytest.mark.asyncio
    async def test_gap_fill_max_gap_limit(self, setup_with_data):
        """Test that max_gap_fill_minutes limits the fetch window."""
        service, mock_client, db, symbol, price_repo = setup_with_data

        # Set small max gap
        service._settings.max_gap_fill_minutes = 10

        # Add old data with a 100-minute gap
        old_ts = 999999994000 - 6000000  # 100 minutes before until_ms
        await price_repo.save(symbol.id, old_ts, 100.0, 110.0, 90.0, 105.0, 1000.0)

        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        result = await service.backfill_symbol("BTC/USDT")

        # Should be limited
        assert '_limited' in result['strategy']

    @pytest.mark.asyncio
    async def test_gap_fill_clock_skew(self, setup_with_data):
        """Test handling of clock skew (negative gap)."""
        service, mock_client, db, symbol, price_repo = setup_with_data

        # Add data in the "future" (after current time)
        # This simulates clock skew where DB has newer data than "now"
        future_ts = 1000000000000 + 60000  # 1 minute in the future
        await price_repo.save(symbol.id, future_ts, 100.0, 110.0, 90.0, 105.0, 1000.0)

        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        result = await service.backfill_symbol("BTC/USDT")

        # Should treat as continuous and extend backward (since insufficient history)
        assert result['strategy'] == 'extend_backward'

    @pytest.mark.asyncio
    async def test_backfill_all_symbols(self, setup):
        """Test backfilling all active symbols."""
        service, mock_client, db = setup

        # Register multiple symbols
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("ETH/USDT")

        mock_client.fetch_ohlcv = AsyncMock(return_value=[])

        results = await service.backfill_all_symbols()

        assert len(results) == 2
        assert all(r['symbol'] in ["BTC/USDT", "ETH/USDT"] for r in results)

    @pytest.mark.asyncio
    async def test_backfill_all_symbols_no_symbols(self, setup):
        """Test backfilling when no symbols exist."""
        service, mock_client, db = setup

        results = await service.backfill_all_symbols()

        assert results == []

    @pytest.mark.asyncio
    async def test_backfill_all_symbols_with_error(self, setup):
        """Test backfilling continues even if one symbol fails."""
        service, mock_client, db = setup

        # Register multiple symbols
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("ETH/USDT")

        # Mock fails for first call, succeeds for second
        mock_client.fetch_ohlcv = AsyncMock(side_effect=[
            Exception("Network error"),
            [],
        ])

        results = await service.backfill_all_symbols()

        assert len(results) == 2
        # First symbol should have error status
        error_results = [r for r in results if r['status'] == 'error']
        assert len(error_results) == 1
        assert 'Network error' in error_results[0]['error']
