import asyncio
import time
import logging

logger = logging.getLogger("voice_agent.services.rate_limiter")


class AsyncTokenBucketRateLimiter:
    """Async token-bucket rate limiter to enforce Plivo Calls-Per-Second (CPS) limit."""

    def __init__(self, calls_per_second: float = 1.0, max_burst: int = 2):
        self.rate = max(0.1, calls_per_second)
        self.capacity = max(1, max_burst)
        self.tokens = float(self.capacity)
        self.last_update = time.perf_counter()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.perf_counter()
                elapsed = now - self.last_update
                self.last_update = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return

                # Calculate sleep duration to replenish 1 token
                deficit = 1.0 - self.tokens
                sleep_seconds = deficit / self.rate
                await asyncio.sleep(sleep_seconds)

