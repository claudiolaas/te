"""Price data repository for OHLCV storage and retrieval."""

from dataclasses import dataclass
from datetime import datetime

from trading_system.database import DatabaseManager


@dataclass
class PriceData:
    """OHLCV price data model."""
    id: int
    symbol_id: int
    timestamp: int  # Unix timestamp in milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row) -> "PriceData":
        """Create PriceData from database row."""
        return cls(
            id=row["id"],
            symbol_id=row["symbol_id"],
            timestamp=row["timestamp"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
        )


class PriceRepository:
    """Repository for OHLCV price data operations.

    Provides storage and retrieval of minute-level candle data.
    Optimized for time-series queries with proper indexing.

    Usage:
        repo = PriceRepository(db_manager)

        # Save single candle
        await repo.save(1, timestamp=1234567890000, open=100.0, high=101.0, 
                       low=99.0, close=100.5, volume=10.5)

        # Save multiple candles (batch insert)
        await repo.save_many(symbol_id, candles)

        # Get price range
        prices = await repo.get_range(symbol_id, start_time=1234567890000, 
                                      end_time=1234567900000)

        # Get latest price
        latest = await repo.get_latest(symbol_id)
    """

    def __init__(self, db: DatabaseManager) -> None:
        """Initialize repository.

        Args:
            db: Database manager instance
        """
        self._db = db

    async def save(
        self,
        symbol_id: int,
        timestamp: int,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float
    ) -> int:
        """Save a single price data point.

        Args:
            symbol_id: Symbol database ID
            timestamp: Unix timestamp in milliseconds (should be rounded to minute)
            open_price: Opening price
            high: High price
            low: Low price
            close: Closing price
            volume: Trading volume

        Returns:
            int: ID of inserted row (or existing row if duplicate)
        """
        try:
            cursor = await self._db.execute(
                """
                INSERT INTO price_data 
                (symbol_id, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol_id, timestamp) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume
                """,
                (symbol_id, timestamp, open_price, high, low, close, volume)
            )
            return cursor.lastrowid
        except Exception as e:
            raise ValueError(f"Failed to save price data: {e}") from e

    async def save_many(self, symbol_id: int, candles: list[dict]) -> int:
        """Save multiple price data points (batch insert).

        More efficient than calling save() multiple times.

        Args:
            symbol_id: Symbol database ID
            candles: List of candle dicts with keys: timestamp, open, high, low, close, volume

        Returns:
            int: Number of rows inserted/updated
        """
        if not candles:
            return 0

        # Build batch insert
        values = []
        for candle in candles:
            values.append((
                symbol_id,
                candle["timestamp"],
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
                candle["volume"]
            ))

        async with self._db.connection() as conn:
            # Use executemany for batch insert
            await conn.executemany(
                """
                INSERT INTO price_data 
                (symbol_id, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol_id, timestamp) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume
                """,
                values
            )
            await conn.commit()

        return len(candles)

    async def get_range(
        self,
        symbol_id: int,
        start_time: int,
        end_time: int
    ) -> list[PriceData]:
        """Get price data for a time range.

        Args:
            symbol_id: Symbol database ID
            start_time: Start timestamp in milliseconds (inclusive)
            end_time: End timestamp in milliseconds (inclusive)

        Returns:
            List of PriceData ordered by timestamp ascending
        """
        rows = await self._db.fetch_all(
            """
            SELECT * FROM price_data 
            WHERE symbol_id = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
            """,
            (symbol_id, start_time, end_time)
        )

        return [PriceData.from_row(row) for row in rows]

    async def get_latest(self, symbol_id: int) -> PriceData | None:
        """Get the most recent price data for a symbol.

        Args:
            symbol_id: Symbol database ID

        Returns:
            Most recent PriceData or None if no data
        """
        row = await self._db.fetch_one(
            """
            SELECT * FROM price_data 
            WHERE symbol_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (symbol_id,)
        )

        if row is None:
            return None

        return PriceData.from_row(row)

    async def get_before(
        self,
        symbol_id: int,
        timestamp: int,
        limit: int = 1
    ) -> list[PriceData]:
        """Get price data before a specific timestamp.

        Useful for getting historical context before a specific time.

        Args:
            symbol_id: Symbol database ID
            timestamp: Reference timestamp in milliseconds
            limit: Maximum number of records to return

        Returns:
            List of PriceData ordered by timestamp descending (most recent first)
        """
        rows = await self._db.fetch_all(
            """
            SELECT * FROM price_data 
            WHERE symbol_id = ? AND timestamp < ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol_id, timestamp, limit)
        )

        return [PriceData.from_row(row) for row in rows]

    async def get_after(
        self,
        symbol_id: int,
        timestamp: int,
        limit: int = 100
    ) -> list[PriceData]:
        """Get price data after a specific timestamp.

        Args:
            symbol_id: Symbol database ID
            timestamp: Reference timestamp in milliseconds
            limit: Maximum number of records to return

        Returns:
            List of PriceData ordered by timestamp ascending
        """
        rows = await self._db.fetch_all(
            """
            SELECT * FROM price_data 
            WHERE symbol_id = ? AND timestamp > ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (symbol_id, timestamp, limit)
        )

        return [PriceData.from_row(row) for row in rows]

    async def count(self, symbol_id: int) -> int:
        """Count total price data records for a symbol.

        Args:
            symbol_id: Symbol database ID

        Returns:
            Number of price records
        """
        row = await self._db.fetch_one(
            "SELECT COUNT(*) as count FROM price_data WHERE symbol_id = ?",
            (symbol_id,)
        )

        return row["count"] if row else 0

    async def delete_range(
        self,
        symbol_id: int,
        start_time: int,
        end_time: int
    ) -> int:
        """Delete price data for a time range.

        Args:
            symbol_id: Symbol database ID
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds

        Returns:
            Number of rows deleted
        """
        cursor = await self._db.execute(
            """
            DELETE FROM price_data 
            WHERE symbol_id = ? AND timestamp >= ? AND timestamp <= ?
            """,
            (symbol_id, start_time, end_time)
        )

        return cursor.rowcount
