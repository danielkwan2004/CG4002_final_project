import asyncio
from collections import deque


class Synchroniser:
    """
    Consumes from two node queues (forearm, paddle), matches samples by
    timestamp within a tolerance, and forwards matched pairs to an output queue.
    """

    def __init__(
        self,
        forearm_queue: asyncio.Queue,
        paddle_queue: asyncio.Queue,
        output_queue: asyncio.Queue,
        logger,
        tolerance_ms: float = 2.5,
        buffer_window_ms: float = 50,
    ):
        self.forearm_queue = forearm_queue
        self.paddle_queue = paddle_queue
        self.output_queue = output_queue
        self.logger = logger
        self.tolerance_ms = tolerance_ms
        self.buffer_window_ms = buffer_window_ms

        self.paddle_buffer = deque()  # rolling buffer of recent paddle samples
        self.matched_count = 0
        self.unmatched_count = 0

    async def run(self):
        self.logger.info("Synchroniser started")
        # run both consumer loops concurrently
        await asyncio.gather(
            self._buffer_paddle_samples(),
            self._match_forearm_samples(),
        )

    async def _buffer_paddle_samples(self):
        while True:
            sample = await self.paddle_queue.get()
            self.paddle_buffer.append(sample)
            self._evict_stale_paddle_samples()

    def _evict_stale_paddle_samples(self):
        if not self.paddle_buffer:
            return
        newest_ts = self.paddle_buffer[-1]["timestamp"]
        while self.paddle_buffer and (newest_ts - self.paddle_buffer[0]["timestamp"]) > self.buffer_window_ms:
            stale = self.paddle_buffer.popleft()
            self.unmatched_count += 1
            self.logger.debug(f"Discarded stale paddle sample seq={stale['sequence']}")

    async def _match_forearm_samples(self):
        while True:
            forearm_sample = await self.forearm_queue.get()
            match = self._find_closest_paddle_match(forearm_sample["timestamp"])

            if match is not None:
                self.matched_count += 1
                paired = {
                    "type": "sensor_data",
                    "timestamp": forearm_sample["timestamp"],
                    "forearm": {
                        "acceleration": forearm_sample["acceleration"],
                        "gyroscope": forearm_sample["gyroscope"],
                    },
                    "paddle": {
                        "acceleration": match["acceleration"],
                        "gyroscope": match["gyroscope"],
                    },
                }
                await self.output_queue.put(paired)
                self.logger.debug(
                    f"Matched forearm seq={forearm_sample['sequence']} "
                    f"with paddle seq={match['sequence']} "
                    f"(dt={abs(forearm_sample['timestamp'] - match['timestamp']):.2f}ms)"
                )
            else:
                self.unmatched_count += 1
                self.logger.warning(
                    f"No paddle match for forearm seq={forearm_sample['sequence']} within {self.tolerance_ms}ms"
                )

    def _find_closest_paddle_match(self, target_ts: float):
        best_sample = None
        best_diff = float("inf")
        for sample in self.paddle_buffer:
            diff = abs(sample["timestamp"] - target_ts)
            if diff < best_diff:
                best_diff = diff
                best_sample = sample
        if best_sample is not None and best_diff <= self.tolerance_ms:
            return best_sample
        return None