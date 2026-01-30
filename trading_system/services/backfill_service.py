"""Backfill service for fetching historical price data."""

import logging

from trading_system.clients import BinanceClient
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.repositories import PriceRepository, SymbolRepository
from tenacity import retry

from trading_system.utils.retry import DEFAULT_RETRY

logger = logging.getLogger(__name__)


class BackfillService:
    """Service for backfilling historical price data.

    Handles:
    - Fetching historical OHLCV data from Binance
    - Storing data in the database
    - Retry logic for network failures
    - Timestamp normalization

    Usage:
        backfill = BackfillService(binance_client, db_manager, settings)

        # Backfill a newly registered symbol
        candles = await backfill.backfill_symbol("BTC/USDT")
        print(f"Backfilled {len(candles)} candles")
    """

    def __init__(
        self,
        binance_client: BinanceClient,
        db: DatabaseManager,
        settings: Settings
    ) -> None:
        """Initialize backfill service.

        Args:
            binance_client: Initialized Binance client
            db: Database manager
            settings: Application settings
        """
        self._binance = binance_client
        self._db = db
        self._settings = settings
        self._symbol_repo = SymbolRepository(db)
        self._price_repo = PriceRepository(db)

    async def backfill_symbol(
        self,
        symbol: str,
        minutes: int | None = None
    ) -> list[dict]:
        """Backfill historical price data for a symbol.

        Fetches OHLCV candles from Binance and stores them in the database.
        Uses the configured BACKFILL_MINUTES if not specified.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            minutes: Number of minutes to backfill (default: settings.backfill_minutes)

        Returns:
            List of candle data that was stored

        Raises:
            ValueError: If symbol is not registered
            ccxt.BadSymbol: If symbol is not valid on exchange
        """
        backfill_minutes = minutes or self._settings.backfill_minutes

        # Get symbol from database
        symbol_obj = await self._symbol_repo.get_by_symbol(symbol)
        if symbol_obj is None:
            raise ValueError(f"Symbol '{symbol}' is not registered. Register it first.")

        logger.info(f"Starting backfill for {symbol}: {backfill_minutes} minutes")

        # Calculate time range
        now_ms = self._binance.milliseconds
        since_ms = now_ms - (backfill_minutes * 60 * 1000)

        # Fetch candles with retry
        candles = await self._fetch_with_retry(symbol, since_ms, backfill_minutes)

        if not candles:
            logger.warning(f"No candles returned for {symbol}")
            return []

        logger.info(f"Fetched {len(candles)} candles for {symbol}")

        # Transform and store
        price_data = self._transform_candles(symbol_obj.id, candles)

        if price_data:
            await self._price_repo.save_many(symbol_obj.id, price_data)
            logger.info(f"Stored {len(price_data)} price records for {symbol}")

        return price_data

    @retry(**DEFAULT_RETRY)
    async def _fetch_with_retry(
        self,
        symbol: str,
        since_ms: int,
        limit: int
    ) -> list:
        """Fetch OHLCV data with retry logic.

        Args:
            symbol: Trading pair
            since_ms: Start timestamp in milliseconds
            limit: Maximum number of candles

        Returns:
            List of OHLCV data from exchange
        """
        return await self._binance.fetch_ohlcv(
            symbol=symbol,
            timeframe='1m',
            since=since_ms,
            limit=limit + 1  # +1 for current forming candle
        )

    def _transform_candles(
        self,
        symbol_id: int,
        candles: list
    ) -> list[dict]:
        """Transform OHLCV data to database format.

        Args:
            symbol_id: Database ID of the symbol
            candles: List of OHLCVData objects

        Returns:
            List of dicts ready for database insertion
        """
        result = []

        for candle in candles:
            # Round timestamp to minute boundary
            # Binance returns timestamps at minute boundaries, but ensure consistency
            minute_ts = (candle.timestamp // 60000) * 60000

            result.append({
                'symbol_id': symbol_id,
                'timestamp': minute_ts,
                'open': candle.open,
                'high': candle.high,
                'low': candle.low,
                'close': candle.close,
                'volume': candle.volume
            })

        return result

    async def get_backfill_status(self, symbol: str) -> dict:
        """Get backfill status for a symbol.

        Args:
            symbol: Trading pair

        Returns:
            Dict with backfill status information
        """
        symbol_obj = await self._symbol_repo.get_by_symbol(symbol)
        if symbol_obj is None:
            return {'error': f"Symbol '{symbol}' not registered"}

        count = await self._price_repo.count(symbol_obj.id)
        latest = await self._price_repo.get_latest(symbol_obj.id)

        return {
            'symbol': symbol,
            'symbol_id': symbol_obj.id,
            'registered_at': symbol_obj.created_at.isoformat(),
            'total_records': count,
            'latest_timestamp': latest.timestamp if latest else None,
            'latest_price': latest.close if latest else None,
        }
