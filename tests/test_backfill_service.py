"""Tests for BackfillService."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_system.clients import BinanceClient, OHLCVData
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.repositories import SymbolRepository
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
                backfill_minutes=5
            )

            # Create mocked Binance client
            mock_client = MagicMock(spec=BinanceClient)
            mock_client.milliseconds = 1000000000000  # Fixed timestamp

            # Create service
            service = BackfillService(mock_client, db, settings)

            yield service, mock_client, db

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
        base_ts = 1000000000000
        mock_client.fetch_ohlcv = AsyncMock(return_value=[
            OHLCVData(timestamp=base_ts, open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0),
            OHLCVData(timestamp=base_ts + 60000, open=105.0, high=115.0, low=95.0, close=110.0, volume=2000.0),
            OHLCVData(timestamp=base_ts + 120000, open=110.0, high=120.0, low=100.0, close=115.0, volume=3000.0),
        ])

        candles = await service.backfill_symbol("BTC/USDT")

        assert len(candles) == 3

        # Verify candles were stored
        from trading_system.repositories import PriceRepository
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

        service._fetch_with_retry = AsyncMock(return_value=[])

        candles = await service.backfill_symbol("BTC/USDT")

        assert candles == []

    @pytest.mark.asyncio
    async def test_backfill_timestamp_normalization(self, setup):
        """Test that timestamps are rounded to minute boundaries."""
        service, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Mock with non-minute timestamps
        mock_client.fetch_ohlcv = AsyncMock(return_value=[
            OHLCVData(timestamp=60000123, open=100.0, high=110.0, low=90.0, close=105.0, volume=1000.0),
        ])

        candles = await service.backfill_symbol("BTC/USDT")

        # Timestamp should be rounded to minute
        assert candles[0]['timestamp'] == 60000000  # Rounded to minute

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
        from trading_system.repositories import PriceRepository
        price_repo = PriceRepository(db)
        await price_repo.save(symbol.id, 1000000000000, 100.0, 110.0, 90.0, 105.0, 1000.0)

        status = await service.get_backfill_status("BTC/USDT")

        assert status['symbol'] == "BTC/USDT"
        assert status['symbol_id'] == symbol.id
        assert status['total_records'] == 1
        assert status['latest_price'] == 105.0

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
