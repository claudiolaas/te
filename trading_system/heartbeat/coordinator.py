"""Heartbeat coordinator that orchestrates the heartbeat cycle."""

import logging
from datetime import UTC, datetime

from trading_system.clients import BinanceClient
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.logger import log_manager

from .price_fetcher import PriceFetcher
from .scheduler import HeartbeatScheduler

logger = logging.getLogger(__name__)


class HeartbeatCoordinator:
    """Main coordinator that orchestrates the heartbeat cycle.

    Wires the heartbeat scheduler to the price fetching service,
    handles errors gracefully, and logs each beat.

    Usage:
        coordinator = HeartbeatCoordinator(
            binance_client=client,
            db=db_manager,
            settings=settings
        )

        await coordinator.start()
        # Heartbeat is now running...
        await coordinator.stop()
    """

    def __init__(
        self,
        binance_client: BinanceClient,
        db: DatabaseManager,
        settings: Settings
    ) -> None:
        """Initialize heartbeat coordinator.

        Args:
            binance_client: Initialized Binance client
            db: Database manager
            settings: Application settings
        """
        self._binance = binance_client
        self._db = db
        self._settings = settings

        # Get heartbeat logger
        self._heartbeat_logger = log_manager.get_heartbeat_logger()

        # Create price fetcher
        self._price_fetcher = PriceFetcher(binance_client, db)

        # Create scheduler
        self._scheduler = HeartbeatScheduler(
            interval_seconds=settings.heartbeat_interval,
            buffer_delay_seconds=settings.heartbeat_buffer_delay,
            handler=self._on_beat,
            name="trading_system"
        )

        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if coordinator is running."""
        return self._running

    @property
    def scheduler_stats(self):
        """Get scheduler statistics."""
        return self._scheduler.stats

    async def start(self) -> None:
        """Start the heartbeat coordinator."""
        if self._running:
            logger.warning("Heartbeat coordinator is already running")
            return

        logger.info("Starting heartbeat coordinator...")
        self._running = True

        # Log startup
        self._heartbeat_logger.info(
            f"Heartbeat starting: interval={self._settings.heartbeat_interval}s, "
            f"buffer={self._settings.heartbeat_buffer_delay}s"
        )

        await self._scheduler.start()

    async def stop(self) -> None:
        """Stop the heartbeat coordinator gracefully."""
        if not self._running:
            return

        logger.info("Stopping heartbeat coordinator...")
        self._running = False

        await self._scheduler.stop()

        # Log shutdown
        stats = self._scheduler.stats
        self._heartbeat_logger.info(
            f"Heartbeat stopped: {stats.beats_executed} beats executed, "
            f"{stats.beats_failed} failed, uptime={stats.uptime_seconds:.1f}s"
        )

    async def _on_beat(self, beat_number: int) -> None:
        """Handle a heartbeat beat.

        This is called by the scheduler on each beat.

        Args:
            beat_number: Incrementing beat counter
        """
        beat_time = datetime.now(UTC)

        # Log beat start
        self._heartbeat_logger.info(
            f"Beat #{beat_number} started at {beat_time.isoformat()}"
        )

        try:
            # Fetch prices for all registered symbols
            results = await self._price_fetcher.fetch_all()

            # Log results
            success_count = sum(1 for r in results if r.success)
            total_count = len(results)

            if total_count > 0:
                self._heartbeat_logger.info(
                    f"Beat #{beat_number} complete: "
                    f"{success_count}/{total_count} symbols fetched"
                )

                # Log individual failures
                for result in results:
                    if not result.success:
                        self._heartbeat_logger.warning(
                            f"Beat #{beat_number} failed for {result.symbol}: "
                            f"{result.error}"
                        )
            else:
                self._heartbeat_logger.info(
                    f"Beat #{beat_number} complete: no symbols registered"
                )

        except Exception as e:
            # Log error but don't re-raise - heartbeat should continue
            self._heartbeat_logger.error(
                f"Beat #{beat_number} error: {e}"
            )
            logger.exception(f"Unexpected error in heartbeat beat #{beat_number}")

    async def run_once(self) -> list:
        """Run a single heartbeat cycle (for testing/debugging).

        Returns:
            List of PriceFetchResult
        """
        self._heartbeat_logger.info("Running single heartbeat cycle")
        return await self._price_fetcher.fetch_all()

    async def __aenter__(self) -> "HeartbeatCoordinator":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
