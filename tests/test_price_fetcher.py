"""Tests for PriceFetcher using real Binance API calls."""

import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from trading_system.clients import BinanceClient, TickerData
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.heartbeat.price_fetcher import PriceFetcher, PriceFetchResult
from trading_system.repositories import SymbolRepository


# Real symbols for testing against Binance API
TEST_SYMBOLS = ["BTC/USDT", "ETH/USDT"]


@pytest_asyncio.fixture
async def real_binance_client():
    """Create a real Binance client with credentials from environment."""
    # Load settings from .env file
    settings = Settings()

    client = BinanceClient(settings)
    await client.initialize()

    yield client

    await client.close()


@pytest_asyncio.fixture
async def setup():
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

        # Create fetcher
        fetcher = PriceFetcher(client, db)

        yield fetcher, client, db

        await client.close()
        await db.close()


class TestPriceFetcherRealAPI:
    """Tests for PriceFetcher class using real Binance API."""

    @pytest.mark.asyncio
    async def test_fetch_all_no_symbols(self, setup):
        """Test fetch_all with no registered symbols."""
        fetcher, client, db = setup

        results = await fetcher.fetch_all()

        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_all_success(self, setup):
        """Test successful price fetch for multiple symbols using real API."""
        fetcher, client, db = setup

        # Register symbols
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("ETH/USDT")

        # Fetch real prices from Binance API
        results = await fetcher.fetch_all()

        assert len(results) == 2

        # Check BTC
        btc_result = next(r for r in results if r.symbol == "BTC/USDT")
        assert btc_result.success is True
        assert btc_result.price is not None
        assert btc_result.price > 0
        assert btc_result.timestamp is not None

        # Check ETH
        eth_result = next(r for r in results if r.symbol == "ETH/USDT")
        assert eth_result.success is True
        assert eth_result.price is not None
        assert eth_result.price > 0
        assert eth_result.timestamp is not None

    @pytest.mark.asyncio
    async def test_fetch_all_stores_prices(self, setup):
        """Test that fetched prices are stored in database."""
        fetcher, client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        await fetcher.fetch_all()

        # Verify price was stored
        from trading_system.repositories import PriceRepository
        price_repo = PriceRepository(db)
        symbol = await symbol_repo.get_by_symbol("BTC/USDT")
        latest = await price_repo.get_latest(symbol.id)

        assert latest is not None
        assert latest.close > 0  # Real price should be positive
        assert latest.open == latest.close  # Single-point candle
        assert latest.high == latest.close
        assert latest.low == latest.close

    @pytest.mark.asyncio
    async def test_fetch_all_with_invalid_symbol_batch_failure(self, setup):
        """Test handling when batch request contains an invalid symbol.

        Real Binance API throws BadSymbol exception for invalid symbols,
        causing the entire batch to fail gracefully.
        """
        fetcher, client, db = setup

        # Register symbols (one real, one fake)
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")
        await symbol_repo.register("INVALID/SYMBOL123")

        results = await fetcher.fetch_all()

        assert len(results) == 2

        # Both should fail because the batch request throws BadSymbol
        assert all(not r.success for r in results)
        assert all("does not have market symbol" in r.error for r in results)

    @pytest.mark.asyncio
    async def test_fetch_single_success(self, setup):
        """Test fetch_single for one symbol using real API."""
        fetcher, client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        result = await fetcher.fetch_single("BTC/USDT")

        assert result.success is True
        assert result.price is not None
        assert result.price > 0
        assert result.timestamp is not None

    @pytest.mark.asyncio
    async def test_fetch_single_not_registered(self, setup):
        """Test fetch_single for unregistered symbol."""
        fetcher, client, db = setup

        result = await fetcher.fetch_single("BTC/USDT")

        assert result.success is False
        assert "not registered" in result.error

    @pytest.mark.asyncio
    async def test_fetch_single_invalid_symbol(self, setup):
        """Test fetch_single with an invalid symbol."""
        fetcher, client, db = setup

        # Register an invalid symbol (will try to fetch anyway)
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("INVALID/FAKE123")

        result = await fetcher.fetch_single("INVALID/FAKE123")

        assert result.success is False
        # Should get an error from Binance API about invalid symbol
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_timestamp_normalization(self, setup):
        """Test that timestamps are normalized to minute boundaries."""
        fetcher, client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        await fetcher.fetch_all()

        # Verify timestamp was rounded to minute
        from trading_system.repositories import PriceRepository
        price_repo = PriceRepository(db)
        symbol = await symbol_repo.get_by_symbol("BTC/USDT")
        latest = await price_repo.get_latest(symbol.id)

        assert latest is not None
        # Should be rounded to minute (60000 ms)
        assert latest.timestamp % 60000 == 0

    @pytest.mark.asyncio
    async def test_fetch_all_updates_last_price_cache(self, setup):
        """Test that fetch_all updates symbol's last price cache."""
        fetcher, client, db = setup

        # Register symbol
        symbol_repo = SymbolRepository(db)
        await symbol_repo.register("BTC/USDT")

        # Fetch prices
        await fetcher.fetch_all()

        # Verify last price was updated
        symbol = await symbol_repo.get_by_symbol("BTC/USDT")
        assert symbol.last_price is not None
        assert symbol.last_price > 0


class TestPriceFetcherWithRealClientDirectly:
    """Tests that interact directly with real Binance client."""

    @pytest.mark.asyncio
    async def test_fetch_ticker_returns_valid_data(self, real_binance_client):
        """Test that fetch_ticker returns valid TickerData from real API."""
        ticker = await real_binance_client.fetch_ticker("BTC/USDT")

        assert isinstance(ticker, TickerData)
        assert ticker.symbol == "BTC/USDT"
        assert ticker.last > 0
        assert ticker.bid > 0
        assert ticker.ask > 0
        assert ticker.timestamp > 0
        assert ticker.volume >= 0

    @pytest.mark.asyncio
    async def test_fetch_tickers_batch(self, real_binance_client):
        """Test that fetch_tickers works with multiple symbols."""
        tickers = await real_binance_client.fetch_tickers(TEST_SYMBOLS)

        assert len(tickers) == 2
        assert "BTC/USDT" in tickers
        assert "ETH/USDT" in tickers

        for symbol, ticker in tickers.items():
            assert isinstance(ticker, TickerData)
            assert ticker.last > 0
            assert ticker.timestamp > 0


class TestPriceFetchResult:
    """Tests for PriceFetchResult dataclass (no API calls needed)."""

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
