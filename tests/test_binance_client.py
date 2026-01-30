"""Tests for BinanceClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_system.clients import BinanceClient
from trading_system.config import Settings


class TestBinanceClient:
    """Tests for BinanceClient class."""

    @pytest.fixture
    def settings(self):
        """Create test settings."""
        return Settings(
            binance_api_key="test_key",
            binance_api_secret="test_secret"
        )

    @pytest.fixture
    async def client(self, settings):
        """Create a mocked BinanceClient."""
        with patch('trading_system.clients.binance_client.ccxt.binance') as mock_ccxt:
            # Setup mock exchange
            mock_exchange = AsyncMock()
            mock_exchange.load_markets = AsyncMock()
            mock_exchange.close = AsyncMock()
            # milliseconds is called as a method but we need it to return a value directly
            mock_exchange.milliseconds = MagicMock(return_value=1234567890000)
            mock_exchange.markets = {'BTC/USDT': {}, 'ETH/USDT': {}}

            mock_ccxt.return_value = mock_exchange

            client = BinanceClient(settings)
            await client.initialize()

            yield client, mock_exchange

            await client.close()

    @pytest.mark.asyncio
    async def test_initialization_creates_exchange(self, settings):
        """Test that initialization creates CCXT exchange with correct config."""
        with patch('trading_system.clients.binance_client.ccxt.binance') as mock_ccxt:
            mock_exchange = AsyncMock()
            mock_exchange.load_markets = AsyncMock()
            mock_ccxt.return_value = mock_exchange

            client = BinanceClient(settings)
            await client.initialize()

            # Verify CCXT binance was created
            mock_ccxt.assert_called_once()

            # Get the config that was passed (could be kwargs or positional)
            call_args = mock_ccxt.call_args

            # Check that the config dict contains our settings
            if call_args.kwargs:
                config = call_args.kwargs
            else:
                config = call_args.args[0] if call_args.args else {}

            assert config.get('apiKey') == "test_key"
            assert config.get('secret') == "test_secret"
            assert config.get('enableRateLimit') is True
            assert config.get('options', {}).get('defaultType') == 'spot'

            # Verify markets were loaded
            mock_exchange.load_markets.assert_called_once()

            await client.close()

    @pytest.mark.asyncio
    async def test_fetch_ticker_returns_normalized_data(self, client):
        """Test that fetch_ticker returns normalized TickerData."""
        client_obj, mock_exchange = client

        # Setup mock ticker response
        mock_exchange.fetch_ticker = AsyncMock(return_value={
            'symbol': 'BTC/USDT',
            'last': 50000.0,
            'bid': 49999.0,
            'ask': 50001.0,
            'timestamp': 1234567890000,
            'quoteVolume': 1000000.0
        })

        ticker = await client_obj.fetch_ticker("BTC/USDT")

        assert ticker.symbol == "BTC/USDT"
        assert ticker.last == 50000.0
        assert ticker.bid == 49999.0
        assert ticker.ask == 50001.0
        assert ticker.timestamp == 1234567890000
        assert ticker.volume == 1000000.0

        mock_exchange.fetch_ticker.assert_called_once_with("BTC/USDT")

    @pytest.mark.asyncio
    async def test_fetch_tickers_batch_request(self, client):
        """Test that fetch_tickers makes batch request."""
        client_obj, mock_exchange = client

        mock_exchange.fetch_tickers = AsyncMock(return_value={
            'BTC/USDT': {
                'symbol': 'BTC/USDT',
                'last': 50000.0,
                'bid': 49999.0,
                'ask': 50001.0,
                'timestamp': 1234567890000,
                'quoteVolume': 1000000.0
            },
            'ETH/USDT': {
                'symbol': 'ETH/USDT',
                'last': 3000.0,
                'bid': 2999.0,
                'ask': 3001.0,
                'timestamp': 1234567890000,
                'quoteVolume': 500000.0
            }
        })

        tickers = await client_obj.fetch_tickers(["BTC/USDT", "ETH/USDT"])

        assert len(tickers) == 2
        assert tickers["BTC/USDT"].last == 50000.0
        assert tickers["ETH/USDT"].last == 3000.0

        mock_exchange.fetch_tickers.assert_called_once_with(["BTC/USDT", "ETH/USDT"])

    @pytest.mark.asyncio
    async def test_fetch_tickers_handles_missing_symbols(self, client):
        """Test that fetch_tickers handles missing symbols gracefully."""
        client_obj, mock_exchange = client

        mock_exchange.fetch_tickers = AsyncMock(return_value={
            'BTC/USDT': {
                'symbol': 'BTC/USDT',
                'last': 50000.0,
                'bid': 49999.0,
                'ask': 50001.0,
                'timestamp': 1234567890000,
                'quoteVolume': 1000000.0
            }
        })

        # Request BTC and ETH, but only BTC is returned
        tickers = await client_obj.fetch_tickers(["BTC/USDT", "ETH/USDT"])

        assert len(tickers) == 1
        assert "BTC/USDT" in tickers
        assert "ETH/USDT" not in tickers

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_returns_normalized_data(self, client):
        """Test that fetch_ohlcv returns normalized OHLCVData."""
        client_obj, mock_exchange = client

        # Mock OHLCV response: [timestamp, open, high, low, close, volume]
        mock_exchange.fetch_ohlcv = AsyncMock(return_value=[
            [1000, 100.0, 110.0, 90.0, 105.0, 1000.0],
            [2000, 105.0, 115.0, 95.0, 110.0, 2000.0],
            [3000, 110.0, 120.0, 100.0, 115.0, 3000.0],
        ])

        candles = await client_obj.fetch_ohlcv("BTC/USDT", since=1000, limit=3)

        assert len(candles) == 3

        # Check first candle
        assert candles[0].timestamp == 1000
        assert candles[0].open == 100.0
        assert candles[0].high == 110.0
        assert candles[0].low == 90.0
        assert candles[0].close == 105.0
        assert candles[0].volume == 1000.0

        mock_exchange.fetch_ohlcv.assert_called_once_with(
            symbol="BTC/USDT",
            timeframe='1m',
            since=1000,
            limit=3
        )

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_default_parameters(self, client):
        """Test that fetch_ohlcv uses correct defaults."""
        client_obj, mock_exchange = client

        mock_exchange.fetch_ohlcv = AsyncMock(return_value=[])

        await client_obj.fetch_ohlcv("BTC/USDT")

        mock_exchange.fetch_ohlcv.assert_called_once_with(
            symbol="BTC/USDT",
            timeframe='1m',
            since=None,
            limit=None
        )

    @pytest.mark.asyncio
    async def test_fetch_balance_returns_normalized_data(self, client):
        """Test that fetch_balance returns normalized balance."""
        client_obj, mock_exchange = client

        mock_exchange.fetch_balance = AsyncMock(return_value={
            'total': {'BTC': 1.5, 'ETH': 10.0, 'USDT': 1000.0, 'XRP': 0.0},
            'free': {'BTC': 1.0, 'ETH': 10.0, 'USDT': 500.0, 'XRP': 0.0},
            'used': {'BTC': 0.5, 'ETH': 0.0, 'USDT': 500.0, 'XRP': 0.0},
        })

        balance = await client_obj.fetch_balance()

        # Should only include non-zero balances
        assert 'BTC' in balance
        assert 'ETH' in balance
        assert 'USDT' in balance
        assert 'XRP' not in balance  # Zero balance filtered out

        # Check structure
        assert balance['BTC'] == {'total': 1.5, 'free': 1.0, 'used': 0.5}
        assert balance['ETH'] == {'total': 10.0, 'free': 10.0, 'used': 0.0}

    @pytest.mark.asyncio
    async def test_fetch_balance_empty(self, client):
        """Test that fetch_balance handles empty balance."""
        client_obj, mock_exchange = client

        mock_exchange.fetch_balance = AsyncMock(return_value={
            'total': {},
            'free': {},
            'used': {},
        })

        balance = await client_obj.fetch_balance()

        assert balance == {}

    @pytest.mark.asyncio
    async def test_markets_property(self, client):
        """Test that markets property returns loaded markets."""
        client_obj, _ = client

        markets = client_obj.markets

        assert markets == {'BTC/USDT': {}, 'ETH/USDT': {}}

    @pytest.mark.asyncio
    async def test_milliseconds_property(self, client):
        """Test that milliseconds property returns exchange timestamp."""
        client_obj, mock_exchange = client

        # milliseconds is a property that calls the exchange method
        ms = client_obj.milliseconds

        # The mock should return the set value
        assert ms == 1234567890000

    @pytest.mark.asyncio
    async def test_uninitialized_raises_error(self, settings):
        """Test that operations raise error when not initialized."""
        client = BinanceClient(settings)
        # Don't initialize

        with pytest.raises(RuntimeError, match="not initialized"):
            await client.fetch_ticker("BTC/USDT")

        with pytest.raises(RuntimeError, match="not initialized"):
            await client.fetch_ohlcv("BTC/USDT")

        with pytest.raises(RuntimeError, match="not initialized"):
            await client.fetch_balance()

    @pytest.mark.asyncio
    async def test_close_releases_resources(self, settings):
        """Test that close releases CCXT exchange."""
        with patch('trading_system.clients.binance_client.ccxt.binance') as mock_ccxt:
            mock_exchange = AsyncMock()
            mock_exchange.load_markets = AsyncMock()
            mock_exchange.close = AsyncMock()
            mock_ccxt.return_value = mock_exchange

            client = BinanceClient(settings)
            await client.initialize()
            await client.close()

            mock_exchange.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self, settings):
        """Test async context manager."""
        with patch('trading_system.clients.binance_client.ccxt.binance') as mock_ccxt:
            mock_exchange = AsyncMock()
            mock_exchange.load_markets = AsyncMock()
            mock_exchange.close = AsyncMock()
            mock_exchange.milliseconds.return_value = 1234567890000
            mock_ccxt.return_value = mock_exchange

            async with BinanceClient(settings) as client:
                assert client._initialized
                # Should be able to use the client
                _ = client.milliseconds

            # After exiting context, should be closed
            mock_exchange.close.assert_called_once()
