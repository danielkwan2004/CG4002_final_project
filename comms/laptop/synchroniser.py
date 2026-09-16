import asyncio
from collections import deque
from constants import PKT_SENSOR_DATA


class Synchroniser:
    """Pair two timestamp-corrected streams on the laptop timebase."""

    def __init__(
        self, 
        forearm_queue, 
        paddle_queue, 
        output_queue, 
        logger,
        tolerance_ms=2.5,      # 2.5ms
        buffer_window_ms=50.0  # 50ms
    ):
        self.forearm_queue = forearm_queue
        self.paddle_queue = paddle_queue
        self.output_queue = output_queue
        self.logger = logger
        self.tolerance_ms = tolerance_ms
        self.buffer_window_ms = buffer_window_ms
        self.max_buffer_len = 200   # 1 sec worth of samples at 200Hz
        self.forearm_buffer = deque(maxlen=self.max_buffer_len)
        self.paddle_buffer = deque(maxlen=self.max_buffer_len)
        self.matched_count = 0
        self.unmatched_forearm = 0
        self.unmatched_paddle = 0

    @staticmethod
    def _ts(sample):
        return float(sample.get("common_timestamp"))

    async def run(self):
        self.logger.info(
            f"Synchroniser started: tolerance={self.tolerance_ms}ms, "
            f"window={self.buffer_window_ms}ms"
        )
        forearm_get = asyncio.create_task(self.forearm_queue.get())
        paddle_get = asyncio.create_task(self.paddle_queue.get())
        try:
            while True:
                done, _ = await asyncio.wait(
                    (forearm_get, paddle_get),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if forearm_get in done:
                    self.forearm_buffer.append(forearm_get.result())
                    forearm_get = asyncio.create_task(self.forearm_queue.get())
                if paddle_get in done:
                    self.paddle_buffer.append(paddle_get.result())
                    paddle_get = asyncio.create_task(self.paddle_queue.get())
                await self._match_available()
        finally:
            forearm_get.cancel()
            paddle_get.cancel()

    async def _match_available(self):
        while self.forearm_buffer and self.paddle_buffer:
            # anchor on whichever side's oldest sample is older
            if self._ts(self.forearm_buffer[0]) <= self._ts(self.paddle_buffer[0]):
                anchor_buffer, search_buffer = self.forearm_buffer, self.paddle_buffer
                anchor_is_forearm = True
            else:
                anchor_buffer, search_buffer = self.paddle_buffer, self.forearm_buffer
                anchor_is_forearm = False

            anchor = anchor_buffer[0]
            target = self._ts(anchor)
            index, match, diff = min(
                ((i, s, abs(self._ts(s) - target)) for i, s in enumerate(search_buffer)),
                key=lambda item: item[2],
            )

            if diff <= self.tolerance_ms:
                anchor_buffer.popleft()
                del search_buffer[index]
                forearm_sample = anchor if anchor_is_forearm else match
                paddle_sample = match if anchor_is_forearm else anchor
                await self.output_queue.put({
                    "type": PKT_SENSOR_DATA,
                    "timestamp": int(round(target)),
                    "forearm_seq": forearm_sample.get("sequence"),
                    "paddle_seq": paddle_sample.get("sequence"),
                    "forearm": {
                        "acceleration": forearm_sample["acceleration"],
                        "gyroscope": forearm_sample["gyroscope"],
                    },
                    "paddle": {
                        "acceleration": paddle_sample["acceleration"],
                        "gyroscope": paddle_sample["gyroscope"],
                    },
                })
                self.matched_count += 1
                continue

            # no match close enough — evict whichever side is stale
            if anchor_is_forearm:
                anchor_buffer.popleft()
                self.unmatched_forearm += 1
            else:
                anchor_buffer.popleft()
                self.unmatched_paddle += 1

    def stats(self):
        total = self.matched_count + self.unmatched_forearm
        return {
            "matched": self.matched_count,
            "unmatched_forearm": self.unmatched_forearm,
            "unmatched_paddle": self.unmatched_paddle,
            "match_rate_percent": (
                100.0 * self.matched_count / total if total else 0.0
            ),
            "forearm_buffer": len(self.forearm_buffer),
            "paddle_buffer": len(self.paddle_buffer),
        }
