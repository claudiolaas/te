"""Heartbeat scheduler that triggers at regular intervals."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

BeatHandler = Callable[[int], Awaitable[None]]
"""Type alias for beat handler functions.

Args:
    beat_number: Incrementing counter for each beat (starting at 1)
"""


@dataclass
class HeartbeatStats:
    """Statistics for heartbeat execution."""
    beats_executed: int = 0
    beats_failed: int = 0
    start_time: datetime | None = None
    last_beat_time: datetime | None = None

    @property
    def uptime_seconds(self) -> float:
        """Calculate uptime in seconds."""
        if self.start_time is None:
            return 0.0
        return (datetime.now(UTC) - self.start_time).total_seconds()


class HeartbeatScheduler:
    """Asyncio-based scheduler that triggers at regular intervals.

    The heartbeat aligns to minute boundaries and includes a configurable
    buffer delay to ensure candles are closed before fetching.

    Usage:
        async def on_beat(beat_number: int):
            print(f"Beat #{beat_number}")

        scheduler = HeartbeatScheduler(
            interval_seconds=60,
            buffer_delay_seconds=5,
            handler=on_beat
        )

        await scheduler.start()
        # Runs until interrupted...
        await scheduler.stop()
    """

    def __init__(
        self,
        interval_seconds: int,
        buffer_delay_seconds: int,
        handler: BeatHandler,
        name: str = "heartbeat"
    ) -> None:
        """Initialize heartbeat scheduler.

        Args:
            interval_seconds: Base interval between beats (e.g., 60 for minute)
            buffer_delay_seconds: Additional delay after interval (e.g., 5)
            handler: Async function to call on each beat
            name: Name for logging identification
        """
        self._interval = interval_seconds
        self._buffer_delay = buffer_delay_seconds
        self._handler = handler
        self._name = name
        self._stats = HeartbeatStats()

        self._running = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

        # Track beat number
        self._beat_number = 0

    @property
    def effective_interval(self) -> int:
        """Get the effective interval including buffer."""
        return self._interval + self._buffer_delay

    @property
    def is_running(self) -> bool:
        """Check if heartbeat is currently running."""
        return self._running

    @property
    def stats(self) -> HeartbeatStats:
        """Get current statistics."""
        return self._stats

    async def start(self) -> None:
        """Start the heartbeat scheduler.

        Sets up signal handlers and begins the beat loop.
        """
        if self._running:
            logger.warning(f"Heartbeat '{self._name}' is already running")
            return

        self._running = True
        self._stats.start_time = datetime.now(UTC)
        self._stop_event.clear()

        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()

        logger.info(
            f"Starting heartbeat '{self._name}' "
            f"(interval={self._interval}s, buffer={self._buffer_delay}s, "
            f"effective={self.effective_interval}s)"
        )

        # Start the beat loop
        self._task = asyncio.create_task(self._beat_loop())

    async def stop(self) -> None:
        """Stop the heartbeat scheduler gracefully."""
        if not self._running:
            return

        logger.info(f"Stopping heartbeat '{self._name}'...")

        self._running = False
        self._stop_event.set()

        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except TimeoutError:
                logger.warning(f"Heartbeat '{self._name}' task did not stop gracefully, cancelling...")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        logger.info(
            f"Heartbeat '{self._name}' stopped. "
            f"Stats: {self._stats.beats_executed} beats executed, "
            f"{self._stats.beats_failed} failed, "
            f"uptime={self._stats.uptime_seconds:.1f}s"
        )

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        try:
            loop = asyncio.get_running_loop()

            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self._signal_handler)
                except NotImplementedError:
                    # Windows doesn't support add_signal_handler
                    pass
        except Exception as e:
            logger.warning(f"Could not setup signal handlers: {e}")

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received shutdown signal for heartbeat '{self._name}'")
        asyncio.create_task(self.stop())

    async def _beat_loop(self) -> None:
        """Main beat loop that triggers at regular intervals."""
        # Calculate initial delay to align to next interval boundary
        initial_delay = self._calculate_initial_delay()

        if initial_delay > 0:
            logger.info(f"Waiting {initial_delay:.1f}s for first beat alignment...")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=initial_delay
                )
                # Stop was requested during initial delay
                return
            except TimeoutError:
                pass

        # Main loop
        while self._running:
            self._beat_number += 1
            beat_start = datetime.now(UTC)

            try:
                logger.debug(f"Heartbeat '{self._name}' beat #{self._beat_number}")
                await self._handler(self._beat_number)

                self._stats.beats_executed += 1
                self._stats.last_beat_time = beat_start

            except Exception as e:
                self._stats.beats_failed += 1
                logger.exception(
                    f"Error in heartbeat '{self._name}' beat #{self._beat_number}: {e}"
                )
                # Continue running - don't let handler errors stop the heartbeat

            # Calculate next beat time
            next_beat_delay = self._calculate_next_beat_delay()

            if next_beat_delay > 0:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=next_beat_delay
                    )
                    # Stop was requested
                    break
                except TimeoutError:
                    pass

    def _calculate_initial_delay(self) -> float:
        """Calculate delay to align to next interval boundary.

        Returns:
            Seconds to wait before first beat
        """
        # If interval is 0 (testing), just use buffer delay
        if self._interval == 0:
            return self._buffer_delay

        now = datetime.now(UTC)

        # Calculate seconds until next interval boundary
        seconds_into_minute = now.second + now.microsecond / 1_000_000
        seconds_to_next_interval = self._interval - (seconds_into_minute % self._interval)

        # Add buffer delay
        total_delay = seconds_to_next_interval + self._buffer_delay

        return total_delay

    def _calculate_next_beat_delay(self) -> float:
        """Calculate delay until next beat.

        Returns:
            Seconds to wait before next beat
        """
        # If interval is 0 (testing), just use buffer delay
        if self._interval == 0:
            return self._buffer_delay

        now = datetime.now(UTC)

        # Calculate when the next interval boundary is
        seconds_into_minute = now.second + now.microsecond / 1_000_000
        seconds_to_next_interval = self._interval - (seconds_into_minute % self._interval)

        # Add buffer delay
        total_delay = seconds_to_next_interval + self._buffer_delay

        return total_delay

    async def __aenter__(self) -> "HeartbeatScheduler":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
