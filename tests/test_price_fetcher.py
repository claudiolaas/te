"""Tests for PriceFetcher."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_system.clients import BinanceClient, TickerData
from trading_system.database import DatabaseManager
from trading_system.heartbeat.price_fetcher import PriceFetcher, PriceFetchResult
from trading_system.repositories import SymbolRepository


class TestPriceFetcher:
    """Tests for PriceFetcher class."""

    @pytest.fixture
    async def setup(self):
        """Create test setup with mocked components."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create database
            db_path = Path(tmpdir) / "test.db"
            db = DatabaseManager(db_path)
            await db.initialize()

            # Create mocked Binance client
            mock_client = MagicMock(spec=BinanceClient)

            # Create fetcher
            fetcher = PriceFetcher(mock_client, db)

            yield fetcher, mock_client, db

            await db.close()

    @pytest.mark.asyncio
    async def test_fetch_all_no_symbols(self, setup):
        """Test fetch_all with no registered symbols."""
        fetcher, mock_client, db = setup

        results = await fetcher.fetch_all()

        assert results == []
        mock_client.fetch_tickers.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_all_success(self, setup):
        """Test successful price fetch for multiple symbols."""
        fetcher, mock_client, db = setup

        # Register symbols
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("ETH/USDT")

        # Mock tickers response
        mock_client.fetch_tickers = AsyncMock(return_value={
            "BTC/USDT": TickerData(
                symbol="BTC/USDT",
                last=50000.0,
                bid=49999.0,
                ask=50001.0,
                timestamp=1234567890000,
                volume=1000.0
            ),
            "ETH/USDT": TickerData(
                symbol="ETH/USDT",
                last=3000.0,
                bid=2999.0,
                ask=3001.0,
                timestamp=1234567890000,
                volume=500.0
            )
        })

        results = await fetcher.fetch_all()

        assert len(results) == 2

        # Check BTC
        btc_result = next(r for r in results if r.symbol == "BTC/USDT")
        assert btc_result.success is True
        assert btc_result.price == 50000.0

        # Check ETH
        eth_result = next(r for r in results if r.symbol == "ETH/USDT")
        assert eth_result.success is True
        assert eth_result.price == 3000.0

    @pytest.mark.asyncio
    async def test_fetch_all_stores_prices(self, setup):
        """Test that fetched prices are stored in database."""
        fetcher, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Mock ticker
        mock_client.fetch_tickers = AsyncMock(return_value={
            "BTC/USDT": TickerData(
                symbol="BTC/USDT",
                last=50000.0,
                bid=49999.0,
                ask=50001.0,
                timestamp=1234567890000,
                volume=1000.0
            )
        })

        await fetcher.fetch_all()

        # Verify price was stored
        from trading_system.repositories import PriceRepository
        price_repo = PriceRepository(db)
        symbol = await symbol_repo.get_by_symbol("BTC/USDT")
        latest = await price_repo.get_latest(symbol.id)

        assert latest is not None
        assert latest.close == 50000.0
        assert latest.open == 50000.0  # Single-point candle
        assert latest.high == 50000.0
        assert latest.low == 50000.0

    @pytest.mark.asyncio
    async def test_fetch_all_missing_symbol_in_response(self, setup):
        """Test handling when symbol is missing from API response."""
        fetcher, mock_client, db = setup

        # Register symbols
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("ETH/USDT")

        # Return only BTC
        mock_client.fetch_tickers = AsyncMock(return_value={
            "BTC/USDT": TickerData(
                symbol="BTC/USDT",
                last=50000.0,
                bid=49999.0,
                ask=50001.0,
                timestamp=1234567890000,
                volume=1000.0
            )
        })

        results = await fetcher.fetch_all()

        assert len(results) == 2

        btc_result = next(r for r in results if r.symbol == "BTC/USDT")
        assert btc_result.success is True

        eth_result = next(r for r in results if r.symbol == "ETH/USDT")
        assert eth_result.success is False
        assert "No ticker data" in eth_result.error

    @pytest.mark.asyncio
    async def test_fetch_all_batch_failure(self, setup):
        """Test handling when batch fetch fails completely."""
        fetcher, mock_client, db = setup

        # Register symbols
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("ETH/USDT")

        # Make fetch fail
        mock_client.fetch_tickers = AsyncMock(side_effect=Exception("API Error"))

        results = await fetcher.fetch_all()

        assert len(results) == 2
        assert all(not r.success for r in results)
        assert all("API Error" in r.error for r in results)

    @pytest.mark.asyncio
    async def test_fetch_all_per_symbol_error_handling(self, setup):
        """Test that one symbol error doesn't affect others."""
        fetcher, mock_client, db = setup

        # Register symbols
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("ETH/USDT")

        # Normal response - processing happens per-symbol
        mock_client.fetch_tickers = AsyncMock(return_value={
            "BTC/USDT": TickerData(
                symbol="BTC/USDT",
                last=50000.0,
                bid=49999.0,
                ask=50001.0,
                timestamp=1234567890000,
                volume=1000.0
            ),
            "ETH/USDT": TickerData(
                symbol="ETH/USDT",
                last=3000.0,
                bid=2999.0,
                ask=3001.0,
                timestamp=1234567890000,
                volume=500.0
            )
        })

        # Simulate error during ETH processing by breaking store method
        original_store = fetcher._store_price
        call_count = 0

        async def broken_store(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # Fail on second call (ETH)
                raise ValueError("Store error")
            await original_store(*args, **kwargs)

        fetcher._store_price = broken_store

        results = await fetcher.fetch_all()

        # BTC should succeed, ETH should fail
        btc_result = next(r for r in results if r.symbol == "BTC/USDT")
        eth_result = next(r for r in results if r.symbol == "ETH/USDT")

        assert btc_result.success is True
        assert eth_result.success is False

    @pytest.mark.asyncio
    async def test_fetch_single_success(self, setup):
        """Test fetch_single for one symbol."""
        fetcher, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Mock single ticker fetch
        mock_client.fetch_ticker = AsyncMock(return_value=TickerData(
            symbol="BTC/USDT",
            last=50000.0,
            bid=49999.0,
            ask=50001.0,
            timestamp=1234567890000,
            volume=1000.0
        ))

        result = await fetcher.fetch_single("BTC/USDT")

        assert result.success is True
        assert result.price == 50000.0
        mock_client.fetch_ticker.assert_called_once_with("BTC/USDT")

    @pytest.mark.asyncio
    async def test_fetch_single_not_registered(self, setup):
        """Test fetch_single for unregistered symbol."""
        fetcher, mock_client, db = setup

        result = await fetcher.fetch_single("BTC/USDT")

        assert result.success is False
        assert "not registered" in result.error

    @pytest.mark.asyncio
    async def test_fetch_single_error(self, setup):
        """Test fetch_single when API fails."""
        fetcher, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Make fetch fail
        mock_client.fetch_ticker = AsyncMock(side_effect=Exception("Network error"))

        result = await fetcher.fetch_single("BTC/USDT")

        assert result.success is False
        assert "Network error" in result.error

    @pytest.mark.asyncio
    async def test_timestamp_normalization(self, setup):
        """Test that timestamps are normalized to minute boundaries."""
        fetcher, mock_client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Use non-minute timestamp
        ts_with_seconds = 1234567890123  # Has milliseconds

        mock_client.fetch_tickers = AsyncMock(return_value={
            "BTC/USDT": TickerData(
                symbol="BTC/USDT",
                last=50000.0,
                bid=49999.0,
                ask=50001.0,
                timestamp=ts_with_seconds,
                volume=1000.0
            )
        })

        await fetcher.fetch_all()

        # Verify timestamp was rounded
        from trading_system.repositories import PriceRepository
        price_repo = PriceRepository(db)
        symbol = await symbol_repo.get_by_symbol("BTC/USDT")
        latest = await price_repo.get_latest(symbol.id)

        # Should be rounded to minute (60000 ms)
        assert latest.timestamp % 60000 == 0


class TestPriceFetchResult:
    """Tests for PriceFetchResult dataclass."""

    def test_success_result(self):
        """Test successful result creation."""
        result = PriceFetchResult(
            symbol="BTC/USDT",
            price=50000.0,
            timestamp=1234567890000,
            success=True
        )

        assert result.symbol == "BTC/USDT"
        assert result.price == 50000.0
        assert result.success is True
        assert result.error is None

    def test_failure_result(self):
        """Test failed result creation."""
        result = PriceFetchResult(
            symbol="BTC/USDT",
            price=None,
            timestamp=None,
            success=False,
            error="API Error"
        )

        assert result.symbol == "BTC/USDT"
        assert result.price is None
        assert result.success is False
        assert result.error == "API Error"
