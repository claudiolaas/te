"""Price fetching service for heartbeat."""

import logging
from dataclasses import dataclass

from trading_system.clients import BinanceClient
from trading_system.database import DatabaseManager
from trading_system.repositories import PriceRepository, SymbolRepository
from trading_system.utils import RetryConfig, with_retry

logger = logging.getLogger(__name__)


@dataclass
class PriceFetchResult:
    """Result of a price fetch operation."""
    symbol: str
    price: float | None
    timestamp: int | None
    success: bool
    error: str | None = None


class PriceFetcher:
    """Service that fetches current prices for all registered symbols.
    
    Fetches prices from Binance and stores them in the database.
    Handles per-symbol errors gracefully - one failure doesn't block others.
    
    Usage:
        fetcher = PriceFetcher(binance_client, db_manager)
        
        results = await fetcher.fetch_all()
        for result in results:
            if result.success:
                print(f"{result.symbol}: {result.price}")
            else:
                print(f"{result.symbol}: ERROR - {result.error}")
    """

    def __init__(
        self,
        binance_client: BinanceClient,
        db: DatabaseManager
    ) -> None:
        """Initialize price fetcher.
        
        Args:
            binance_client: Initialized Binance client
            db: Database manager
        """
        self._binance = binance_client
        self._db = db
        self._symbol_repo = SymbolRepository(db)
        self._price_repo = PriceRepository(db)

    async def fetch_all(self) -> list[PriceFetchResult]:
        """Fetch current prices for all registered symbols.
        
        Fetches prices in batch for efficiency, then stores each
        price in the database. Per-symbol errors are caught and
        reported without affecting other symbols.
        
        Returns:
            List of PriceFetchResult for each symbol
        """
        # Get all active symbols
        symbols = await self._symbol_repo.list_active()

        if not symbols:
            logger.debug("No active symbols to fetch prices for")
            return []

        symbol_names = [s.symbol for s in symbols]
        logger.info(f"Fetching prices for {len(symbol_names)} symbols: {symbol_names}")

        # Fetch all tickers in one batch request
        try:
            tickers = await self._fetch_tickers_with_retry(symbol_names)
        except Exception as e:
            logger.error(f"Failed to fetch tickers batch: {e}")
            # Return failure for all symbols
            return [
                PriceFetchResult(
                    symbol=name,
                    price=None,
                    timestamp=None,
                    success=False,
                    error=str(e)
                )
                for name in symbol_names
            ]

        # Process each symbol individually
        results = []
        for symbol_obj in symbols:
            result = await self._process_symbol(symbol_obj, tickers)
            results.append(result)

        # Log summary
        success_count = sum(1 for r in results if r.success)
        logger.info(
            f"Price fetch complete: {success_count}/{len(results)} symbols successful"
        )

        return results

    @with_retry(RetryConfig(max_attempts=3, base_delay=1.0))
    async def _fetch_tickers_with_retry(
        self,
        symbol_names: list[str]
    ) -> dict:
        """Fetch tickers batch with retry logic.
        
        Args:
            symbol_names: List of symbol names to fetch
            
        Returns:
            Dict of symbol to ticker data
        """
        return await self._binance.fetch_tickers(symbol_names)

    async def _process_symbol(
        self,
        symbol_obj,
        tickers: dict
    ) -> PriceFetchResult:
        """Process a single symbol's price data.
        
        Args:
            symbol_obj: Symbol database object
            tickers: Dict of fetched tickers
            
        Returns:
            PriceFetchResult
        """
        symbol_name = symbol_obj.symbol

        try:
            # Check if we have ticker data
            if symbol_name not in tickers:
                error_msg = f"No ticker data returned for {symbol_name}"
                logger.warning(error_msg)
                return PriceFetchResult(
                    symbol=symbol_name,
                    price=None,
                    timestamp=None,
                    success=False,
                    error=error_msg
                )

            ticker = tickers[symbol_name]

            # Store the price data as a single-point candle
            # For real-time prices, we store as O=H=L=C=last_price
            timestamp_ms = ticker.timestamp
            price = ticker.last

            await self._store_price(symbol_obj.id, timestamp_ms, price)

            # Update symbol's last price cache
            await self._symbol_repo.update_last_price(symbol_obj.id, price)

            logger.debug(
                f"Fetched {symbol_name}: price={price}, timestamp={timestamp_ms}"
            )

            return PriceFetchResult(
                symbol=symbol_name,
                price=price,
                timestamp=timestamp_ms,
                success=True
            )

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Error processing {symbol_name}: {error_msg}")

            return PriceFetchResult(
                symbol=symbol_name,
                price=None,
                timestamp=None,
                success=False,
                error=error_msg
            )

    async def _store_price(
        self,
        symbol_id: int,
        timestamp_ms: int,
        price: float
    ) -> None:
        """Store price data in database.
        
        Stores as a single-point candle where O=H=L=C=price.
        This allows strategies to query consistent OHLCV format.
        
        Args:
            symbol_id: Symbol database ID
            timestamp_ms: Timestamp in milliseconds
            price: Price value
        """
        # Round timestamp to minute boundary
        minute_ts = (timestamp_ms // 60000) * 60000

        # Store as single-point candle
        await self._price_repo.save(
            symbol_id=symbol_id,
            timestamp=minute_ts,
            open_price=price,
            high=price,
            low=price,
            close=price,
            volume=0.0  # No volume for ticker data
        )

    async def fetch_single(self, symbol: str) -> PriceFetchResult:
        """Fetch price for a single symbol.
        
        Args:
            symbol: Symbol name (e.g., "BTC/USDT")
            
        Returns:
            PriceFetchResult
        """
        # Get symbol from database
        symbol_obj = await self._symbol_repo.get_by_symbol(symbol)
        if symbol_obj is None:
            return PriceFetchResult(
                symbol=symbol,
                price=None,
                timestamp=None,
                success=False,
                error=f"Symbol '{symbol}' is not registered"
            )

        try:
            ticker = await self._binance.fetch_ticker(symbol)

            await self._store_price(symbol_obj.id, ticker.timestamp, ticker.last)
            await self._symbol_repo.update_last_price(symbol_obj.id, ticker.last)

            return PriceFetchResult(
                symbol=symbol,
                price=ticker.last,
                timestamp=ticker.timestamp,
                success=True
            )

        except Exception as e:
            logger.exception(f"Error fetching {symbol}: {e}")
            return PriceFetchResult(
                symbol=symbol,
                price=None,
                timestamp=None,
                success=False,
                error=str(e)
            )
