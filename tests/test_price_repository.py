"""Tests for PriceRepository."""

import tempfile
from pathlib import Path

import pytest

from trading_system.database import DatabaseManager
from trading_system.repositories import PriceData, PriceRepository, SymbolRepository


class TestPriceRepository:
    """Tests for PriceRepository class."""

    @pytest.fixture
    async def repo(self):
        """Create a PriceRepository with temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = DatabaseManager(db_path)
            await db.initialize()
            repo = PriceRepository(db)
            yield repo
            await db.close()

    @pytest.fixture
    async def symbol_id(self, repo):
        """Create a test symbol and return its ID."""
        # Need to create a SymbolRepository to register a symbol
        db = repo._db
        symbol_repo = SymbolRepository(db)
        symbol = await symbol_repo.register("BTC/USDT")
        return symbol.id

    @pytest.mark.asyncio
    async def test_save_price_data(self, repo, symbol_id):
        """Test saving a single price data point."""
        row_id = await repo.save(
            symbol_id=symbol_id,
            timestamp=1234567890000,
            open_price=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=1000.0
        )

        assert row_id is not None
        assert isinstance(row_id, int)

    @pytest.mark.asyncio
    async def test_save_updates_on_conflict(self, repo, symbol_id):
        """Test that saving duplicate timestamp updates existing record."""
        timestamp = 1234567890000

        # Save initial
        await repo.save(symbol_id, timestamp, 100.0, 110.0, 90.0, 105.0, 1000.0)

        # Save update for same timestamp
        await repo.save(symbol_id, timestamp, 101.0, 111.0, 91.0, 106.0, 1001.0)

        # Should only have one record
        count = await repo.count(symbol_id)
        assert count == 1

        # Verify updated values
        latest = await repo.get_latest(symbol_id)
        assert latest.close == 106.0
        assert latest.volume == 1001.0

    @pytest.mark.asyncio
    async def test_save_many(self, repo, symbol_id):
        """Test batch saving multiple candles."""
        candles = [
            {"timestamp": 1234567890000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1000.0},
            {"timestamp": 1234567950000, "open": 105.0, "high": 115.0, "low": 95.0, "close": 110.0, "volume": 2000.0},
            {"timestamp": 1234568010000, "open": 110.0, "high": 120.0, "low": 100.0, "close": 115.0, "volume": 3000.0},
        ]

        count = await repo.save_many(symbol_id, candles)

        assert count == 3
        assert await repo.count(symbol_id) == 3

    @pytest.mark.asyncio
    async def test_save_many_empty_list(self, repo, symbol_id):
        """Test that save_many with empty list returns 0."""
        count = await repo.save_many(symbol_id, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_range(self, repo, symbol_id):
        """Test getting price data for a time range."""
        # Insert test data
        candles = [
            {"timestamp": 1000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0},
            {"timestamp": 2000, "open": 105.0, "high": 115.0, "low": 95.0, "close": 110.0, "volume": 2.0},
            {"timestamp": 3000, "open": 110.0, "high": 120.0, "low": 100.0, "close": 115.0, "volume": 3.0},
            {"timestamp": 4000, "open": 115.0, "high": 125.0, "low": 105.0, "close": 120.0, "volume": 4.0},
        ]
        await repo.save_many(symbol_id, candles)

        # Get range
        results = await repo.get_range(symbol_id, start_time=1500, end_time=3500)

        assert len(results) == 2
        assert results[0].timestamp == 2000
        assert results[1].timestamp == 3000

    @pytest.mark.asyncio
    async def test_get_range_inclusive(self, repo, symbol_id):
        """Test that get_range is inclusive of boundaries."""
        candles = [
            {"timestamp": 1000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0},
            {"timestamp": 2000, "open": 105.0, "high": 115.0, "low": 95.0, "close": 110.0, "volume": 2.0},
        ]
        await repo.save_many(symbol_id, candles)

        results = await repo.get_range(symbol_id, start_time=1000, end_time=2000)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_range_returns_ordered(self, repo, symbol_id):
        """Test that get_range returns results in ascending timestamp order."""
        # Insert out of order
        candles = [
            {"timestamp": 3000, "open": 110.0, "high": 120.0, "low": 100.0, "close": 115.0, "volume": 3.0},
            {"timestamp": 1000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0},
            {"timestamp": 2000, "open": 105.0, "high": 115.0, "low": 95.0, "close": 110.0, "volume": 2.0},
        ]
        await repo.save_many(symbol_id, candles)

        results = await repo.get_range(symbol_id, start_time=0, end_time=5000)

        timestamps = [r.timestamp for r in results]
        assert timestamps == [1000, 2000, 3000]

    @pytest.mark.asyncio
    async def test_get_range_empty_result(self, repo, symbol_id):
        """Test that get_range returns empty list when no data."""
        results = await repo.get_range(symbol_id, start_time=0, end_time=1000)
        assert results == []

    @pytest.mark.asyncio
    async def test_get_latest(self, repo, symbol_id):
        """Test getting the most recent price data."""
        candles = [
            {"timestamp": 1000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0},
            {"timestamp": 2000, "open": 105.0, "high": 115.0, "low": 95.0, "close": 110.0, "volume": 2.0},
            {"timestamp": 3000, "open": 110.0, "high": 120.0, "low": 100.0, "close": 115.0, "volume": 3.0},
        ]
        await repo.save_many(symbol_id, candles)

        latest = await repo.get_latest(symbol_id)

        assert latest is not None
        assert latest.timestamp == 3000
        assert latest.close == 115.0

    @pytest.mark.asyncio
    async def test_get_latest_returns_none_for_empty(self, repo, symbol_id):
        """Test that get_latest returns None when no data."""
        latest = await repo.get_latest(symbol_id)
        assert latest is None

    @pytest.mark.asyncio
    async def test_get_before(self, repo, symbol_id):
        """Test getting prices before a timestamp."""
        candles = [
            {"timestamp": 1000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0},
            {"timestamp": 2000, "open": 105.0, "high": 115.0, "low": 95.0, "close": 110.0, "volume": 2.0},
            {"timestamp": 3000, "open": 110.0, "high": 120.0, "low": 100.0, "close": 115.0, "volume": 3.0},
        ]
        await repo.save_many(symbol_id, candles)

        results = await repo.get_before(symbol_id, timestamp=2500, limit=2)

        assert len(results) == 2
        assert results[0].timestamp == 2000  # Most recent first
        assert results[1].timestamp == 1000

    @pytest.mark.asyncio
    async def test_get_after(self, repo, symbol_id):
        """Test getting prices after a timestamp."""
        candles = [
            {"timestamp": 1000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0},
            {"timestamp": 2000, "open": 105.0, "high": 115.0, "low": 95.0, "close": 110.0, "volume": 2.0},
            {"timestamp": 3000, "open": 110.0, "high": 120.0, "low": 100.0, "close": 115.0, "volume": 3.0},
        ]
        await repo.save_many(symbol_id, candles)

        results = await repo.get_after(symbol_id, timestamp=1500, limit=2)

        assert len(results) == 2
        assert results[0].timestamp == 2000
        assert results[1].timestamp == 3000

    @pytest.mark.asyncio
    async def test_count(self, repo, symbol_id):
        """Test counting price records."""
        # Empty initially
        assert await repo.count(symbol_id) == 0

        # Add data
        candles = [
            {"timestamp": 1000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0},
            {"timestamp": 2000, "open": 105.0, "high": 115.0, "low": 95.0, "close": 110.0, "volume": 2.0},
        ]
        await repo.save_many(symbol_id, candles)

        assert await repo.count(symbol_id) == 2

    @pytest.mark.asyncio
    async def test_delete_range(self, repo, symbol_id):
        """Test deleting price data in a range."""
        candles = [
            {"timestamp": 1000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0},
            {"timestamp": 2000, "open": 105.0, "high": 115.0, "low": 95.0, "close": 110.0, "volume": 2.0},
            {"timestamp": 3000, "open": 110.0, "high": 120.0, "low": 100.0, "close": 115.0, "volume": 3.0},
        ]
        await repo.save_many(symbol_id, candles)

        deleted = await repo.delete_range(symbol_id, start_time=1500, end_time=2500)

        assert deleted == 1
        assert await repo.count(symbol_id) == 2

        # Verify correct record deleted
        remaining = await repo.get_range(symbol_id, start_time=0, end_time=5000)
        timestamps = [r.timestamp for r in remaining]
        assert timestamps == [1000, 3000]

    @pytest.mark.asyncio
    async def test_price_data_from_row(self, repo, symbol_id):
        """Test PriceData dataclass from_row method."""
        await repo.save(
            symbol_id=symbol_id,
            timestamp=1234567890000,
            open_price=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=1000.0
        )

        data = await repo.get_latest(symbol_id)

        assert isinstance(data, PriceData)
        assert data.symbol_id == symbol_id
        assert data.timestamp == 1234567890000
        assert data.open == 100.0
        assert data.high == 110.0
        assert data.low == 90.0
        assert data.close == 105.0
        assert data.volume == 1000.0

    @pytest.mark.asyncio
    async def test_multiple_symbols_isolated(self, repo):
        """Test that data for different symbols is isolated."""
        db = repo._db
        symbol_repo = SymbolRepository(db)

        btc = await symbol_repo.register("BTC/USDT")
        eth = await symbol_repo.register("ETH/USDT")

        # Add data for BTC
        await repo.save(btc.id, 1000, 50000.0, 51000.0, 49000.0, 50500.0, 100.0)

        # Add data for ETH
        await repo.save(eth.id, 1000, 3000.0, 3100.0, 2900.0, 3050.0, 200.0)

        # Verify isolation
        btc_data = await repo.get_latest(btc.id)
        eth_data = await repo.get_latest(eth.id)

        assert btc_data.close == 50500.0
        assert eth_data.close == 3050.0

        assert await repo.count(btc.id) == 1
        assert await repo.count(eth.id) == 1
