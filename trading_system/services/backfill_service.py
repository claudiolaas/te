"""Backfill service for fetching historical price data."""

import logging

from tenacity import retry

from trading_system.clients import BinanceClient
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.repositories import PriceRepository, SymbolRepository
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
    ) -> dict:
        """Backfill historical price data for a symbol.

        Fetches OHLCV candles from Binance and stores them in the database.
        Uses the configured BACKFILL_MINUTES if not specified.

        When gap_fill_enabled is True, intelligently detects gaps between
        existing data and current time, filling only what's necessary.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            minutes: Number of minutes to backfill (default: settings.backfill_minutes)

        Returns:
            Dict with backfill results including status, strategy used, and records stored

        Raises:
            ValueError: If symbol is not registered
            ccxt.BadSymbol: If symbol is not valid on exchange
        """
        backfill_minutes = minutes or self._settings.backfill_minutes

        # Get symbol from database
        symbol_obj = await self._symbol_repo.get_by_symbol(symbol)
        if symbol_obj is None:
            raise ValueError(f"Symbol '{symbol}' is not registered. Register it first.")

        # Calculate fetch window using gap-filling logic
        window = await self._calculate_fetch_window(symbol_obj.id, backfill_minutes)

        if window['strategy'] == 'no_action':
            logger.info(f"Backfill for {symbol}: {window['reason']}")
            return {
                'symbol': symbol,
                'status': 'no_action',
                'reason': window['reason'],
                'records_stored': 0,
            }

        logger.info(
            f"Starting backfill for {symbol}: strategy={window['strategy']}, "
            f"from_ms={window['since_ms']}, to_ms={window['until_ms']}"
        )

        # Fetch candles with retry
        candles = await self._fetch_with_retry(
            symbol, window['since_ms'], window['limit']
        )

        if not candles:
            logger.warning(f"No candles returned for {symbol}")
            return {
                'symbol': symbol,
                'status': 'no_data',
                'strategy': window['strategy'],
                'records_stored': 0,
            }

        logger.info(f"Fetched {len(candles)} candles for {symbol}")

        # Transform and store
        price_data = self._transform_candles(symbol_obj.id, candles)

        if price_data:
            await self._price_repo.save_many(symbol_obj.id, price_data)
            logger.info(f"Stored {len(price_data)} price records for {symbol}")

        return {
            'symbol': symbol,
            'status': 'success',
            'strategy': window['strategy'],
            'records_stored': len(price_data),
            'fetch_from_ms': window['since_ms'],
            'fetch_to_ms': window['until_ms'],
        }

    async def _calculate_fetch_window(
        self,
        symbol_id: int,
        backfill_minutes: int
    ) -> dict:
        """Calculate the fetch window using gap-filling logic.

        Args:
            symbol_id: Database ID of the symbol
            backfill_minutes: Desired minutes of historical data

        Returns:
            Dict with since_ms, until_ms, limit, and strategy
        """
        now_ms = self._binance.milliseconds
        # Don't fetch the currently forming candle - use previous complete minute
        until_ms = ((now_ms // 60000) * 60000) - 60000
        required_ms = backfill_minutes * 60 * 1000

        # Get latest timestamp from database
        latest = await self._price_repo.get_latest(symbol_id)

        if latest is None:
            # No existing data - standard backfill
            since_ms = until_ms - required_ms
            return {
                'since_ms': since_ms,
                'until_ms': until_ms,
                'limit': backfill_minutes,
                'strategy': 'full_backfill',
            }

        # Calculate gap between latest data and now
        gap_ms = until_ms - latest.timestamp
        threshold_ms = self._settings.gap_fill_threshold_minutes * 60 * 1000

        # Handle clock skew (negative gap)
        if gap_ms < 0:
            logger.warning(
                f"Clock skew detected: gap={gap_ms}ms, treating as continuous"
            )
            gap_ms = 0

        if gap_ms <= threshold_ms:
            # Continuous data - check if need to extend backward
            oldest = await self._price_repo.get_oldest(symbol_id)
            existing_ms = until_ms - oldest.timestamp if oldest else 0

            if existing_ms >= required_ms:
                # Have sufficient history, no action needed
                return {
                    'since_ms': 0,
                    'until_ms': 0,
                    'limit': 0,
                    'strategy': 'no_action',
                    'reason': 'sufficient_history',
                }
            else:
                # Need to extend backward to meet requirement
                since_ms = until_ms - required_ms
                return {
                    'since_ms': since_ms,
                    'until_ms': until_ms,
                    'limit': backfill_minutes,
                    'strategy': 'extend_backward',
                }
        else:
            # Gap detected - get oldest to calculate existing history
            oldest = await self._price_repo.get_oldest(symbol_id)
            existing_ms = latest.timestamp - oldest.timestamp if oldest else 0

            if (gap_ms + existing_ms) < required_ms:
                # Gap + existing < required, need to extend backward
                since_ms = until_ms - required_ms
                strategy = 'gap_plus_extend'
            else:
                # Gap alone satisfies requirement, fill gap only
                since_ms = latest.timestamp + 60000  # Start after last data point
                strategy = 'gap_only'

            # Apply max gap limit
            max_gap_ms = self._settings.max_gap_fill_minutes * 60 * 1000
            fetch_window_ms = until_ms - since_ms
            if fetch_window_ms > max_gap_ms:
                since_ms = until_ms - max_gap_ms
                strategy += '_limited'

            limit = (until_ms - since_ms) // 60000

            return {
                'since_ms': since_ms,
                'until_ms': until_ms,
                'limit': limit,
                'strategy': strategy,
            }

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

    async def backfill_all_symbols(self) -> list[dict]:
        """Backfill all active symbols with gap-filling logic.

        This is intended to be called on system startup to ensure
        all symbols have continuous data.

        Returns:
            List of backfill results for each symbol
        """
        symbols = await self._symbol_repo.list_active()
        if not symbols:
            logger.info("No active symbols to backfill")
            return []

        logger.info(f"Starting gap-fill backfill for {len(symbols)} symbols")

        results = []
        for symbol_obj in symbols:
            try:
                result = await self.backfill_symbol(symbol_obj.symbol)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to backfill {symbol_obj.symbol}: {e}")
                results.append({
                    'symbol': symbol_obj.symbol,
                    'status': 'error',
                    'error': str(e),
                    'records_stored': 0,
                })

        # Log summary
        success_count = sum(1 for r in results if r['status'] == 'success')
        no_action_count = sum(1 for r in results if r['status'] == 'no_action')
        error_count = len(results) - success_count - no_action_count
        total_records = sum(r.get('records_stored', 0) for r in results)

        logger.info(
            f"Backfill complete: {success_count} success, {no_action_count} no-action, "
            f"{error_count} errors, {total_records} total records stored"
        )

        return results

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
        oldest = await self._price_repo.get_oldest(symbol_obj.id)

        return {
            'symbol': symbol,
            'symbol_id': symbol_obj.id,
            'registered_at': symbol_obj.created_at.isoformat(),
            'total_records': count,
            'latest_timestamp': latest.timestamp if latest else None,
            'latest_price': latest.close if latest else None,
            'oldest_timestamp': oldest.timestamp if oldest else None,
        }
