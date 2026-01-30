"""Binance API client using CCXT."""

from dataclasses import dataclass
from typing import Any

import ccxt.async_support as ccxt

from trading_system.config import Settings


@dataclass
class TickerData:
    """Normalized ticker data."""
    symbol: str
    last: float
    bid: float
    ask: float
    timestamp: int  # Unix timestamp in milliseconds
    volume: float


@dataclass
class OHLCVData:
    """Normalized OHLCV candle data."""
    timestamp: int  # Unix timestamp in milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float


class BinanceClient:
    """Async Binance API client using CCXT.
    
    Provides:
    - Market data fetching (tickers, OHLCV)
    - Balance/wallet queries
    - Order placement (future use)
    - Rate limiting and error handling
    
    Usage:
        settings = Settings()
        client = BinanceClient(settings)
        
        await client.initialize()
        
        # Fetch current price
        ticker = await client.fetch_ticker("BTC/USDT")
        print(f"BTC price: {ticker.last}")
        
        # Fetch OHLCV for backfill
        candles = await client.fetch_ohlcv("BTC/USDT", since=timestamp)
        
        await client.close()
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize Binance client.
        
        Args:
            settings: Application settings with API credentials
        """
        self._settings = settings
        self._exchange: ccxt.binance | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize CCXT exchange connection."""
        if self._initialized:
            return

        self._exchange = ccxt.binance({
            'apiKey': self._settings.binance_api_key,
            'secret': self._settings.binance_api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True,
            }
        })

        # Load markets to validate connection
        await self._exchange.load_markets()

        self._initialized = True

    async def close(self) -> None:
        """Close exchange connection."""
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None
            self._initialized = False

    async def fetch_ticker(self, symbol: str) -> TickerData:
        """Fetch current ticker data for a symbol.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            
        Returns:
            TickerData with current price information
            
        Raises:
            ccxt.BadSymbol: If symbol is not valid
            ccxt.NetworkError: On network issues
        """
        if not self._initialized or self._exchange is None:
            raise RuntimeError("Client not initialized. Call initialize() first.")

        ticker = await self._exchange.fetch_ticker(symbol)

        return TickerData(
            symbol=ticker['symbol'],
            last=ticker['last'],
            bid=ticker['bid'],
            ask=ticker['ask'],
            timestamp=ticker['timestamp'] or self._exchange.milliseconds(),
            volume=ticker.get('quoteVolume', 0.0)
        )

    async def fetch_tickers(self, symbols: list[str]) -> dict[str, TickerData]:
        """Fetch tickers for multiple symbols (batch request).
        
        More efficient than calling fetch_ticker multiple times.
        
        Args:
            symbols: List of trading pairs
            
        Returns:
            Dict mapping symbol to TickerData
        """
        if not self._initialized or self._exchange is None:
            raise RuntimeError("Client not initialized. Call initialize() first.")

        tickers = await self._exchange.fetch_tickers(symbols)

        result = {}
        for symbol in symbols:
            if symbol in tickers:
                ticker = tickers[symbol]
                result[symbol] = TickerData(
                    symbol=ticker['symbol'],
                    last=ticker['last'],
                    bid=ticker['bid'],
                    ask=ticker['ask'],
                    timestamp=ticker['timestamp'] or self._exchange.milliseconds(),
                    volume=ticker.get('quoteVolume', 0.0)
                )

        return result

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1m',
        since: int | None = None,
        limit: int | None = None
    ) -> list[OHLCVData]:
        """Fetch OHLCV (candle) data.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (default: '1m')
            since: Start timestamp in milliseconds (optional)
            limit: Maximum number of candles (optional)
            
        Returns:
            List of OHLCVData ordered by timestamp ascending
        """
        if not self._initialized or self._exchange is None:
            raise RuntimeError("Client not initialized. Call initialize() first.")

        ohlcv = await self._exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=since,
            limit=limit
        )

        return [
            OHLCVData(
                timestamp=candle[0],
                open=candle[1],
                high=candle[2],
                low=candle[3],
                close=candle[4],
                volume=candle[5]
            )
            for candle in ohlcv
        ]

    async def fetch_balance(self) -> dict[str, dict[str, float]]:
        """Fetch account balance.
        
        Returns:
            Dict mapping currency to {'total': float, 'free': float, 'used': float}
        """
        if not self._initialized or self._exchange is None:
            raise RuntimeError("Client not initialized. Call initialize() first.")

        balance = await self._exchange.fetch_balance()

        # Filter to only currencies with non-zero balances
        result = {}
        for currency, amounts in balance['total'].items():
            if amounts and amounts > 0:
                result[currency] = {
                    'total': balance['total'].get(currency, 0.0),
                    'free': balance['free'].get(currency, 0.0),
                    'used': balance['used'].get(currency, 0.0)
                }

        return result

    @property
    def markets(self) -> dict[str, Any]:
        """Get loaded markets."""
        if not self._initialized or self._exchange is None:
            raise RuntimeError("Client not initialized. Call initialize() first.")
        return self._exchange.markets

    @property
    def milliseconds(self) -> int:
        """Get current timestamp in milliseconds."""
        if not self._initialized or self._exchange is None:
            raise RuntimeError("Client not initialized. Call initialize() first.")
        return self._exchange.milliseconds()

    async def __aenter__(self) -> "BinanceClient":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
