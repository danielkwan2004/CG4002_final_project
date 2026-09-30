# Pair samples only within the same source (stream or dummy). Both sources use
# identical matching rules and produce the same MQTT payload schema.
import asyncio
import uuid
from collections import deque
import _bootstrap
from utilities.constants import (PacketType, SENSOR_SOURCES)


def paired_sensor_packet(forearm, paddle, sensor_seq, session_id):
    """Shared payload for continuous and keyboard-triggered sensor pairs."""
    if forearm["source"] != paddle["source"]:
        raise ValueError("Cannot pair normal and dummy samples")
    return {
        "type": PacketType.SENSOR_DATA,
        "source": forearm["source"],
        "sensor_seq": sensor_seq,
        "session_id": session_id,
        "timestamp": int(round(min(forearm["common_timestamp"], paddle["common_timestamp"]))),
        "forearm_seq": forearm["sequence"],
        "paddle_seq": paddle["sequence"],
        "forearm": {k: forearm[k] for k in ("acceleration", "gyroscope")},
        "paddle": {k: paddle[k] for k in ("acceleration", "gyroscope")},
    }


class Synchroniser:
    """Pair two timestamp-corrected streams on the laptop timebase."""

    def __init__(
        self, 
        forearm_queue,
        paddle_queue,
        output_queue,
        logger,
        tolerance_ms=2.5
    ):
        self.forearm_queue = forearm_queue
        self.paddle_queue = paddle_queue
        self.output_queue = output_queue
        self.logger = logger
        self.tolerance_ms = tolerance_ms
        self.max_buffer_len = 200   # 1 sec worth of samples at 200Hz
        self.forearm_buffer = {source: deque(maxlen=self.max_buffer_len) for source in SENSOR_SOURCES.values()}
        self.paddle_buffer = {source: deque(maxlen=self.max_buffer_len) for source in SENSOR_SOURCES.values()}
        self.matched_count = 0
        self.session_id = uuid.uuid4().hex
        self.unmatched_forearm = 0
        self.unmatched_paddle = 0

    @staticmethod
    def _ts(sample):
        return float(sample.get("common_timestamp"))

    async def run(self):
        self.logger.debug(
            f"FireBeetle synchroniser waiting for samples: tolerance = {self.tolerance_ms}ms"
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
                    sample = forearm_get.result()
                    self.forearm_buffer[sample["source"]].append(sample)
                    forearm_get = asyncio.create_task(self.forearm_queue.get())
                if paddle_get in done:
                    sample = paddle_get.result()
                    self.paddle_buffer[sample["source"]].append(sample)
                    paddle_get = asyncio.create_task(self.paddle_queue.get())
                await self._match_available()
        finally:
            forearm_get.cancel()
            paddle_get.cancel()

    async def _match_available(self):
        for source in SENSOR_SOURCES.values():
            await self._match_source(source)

    # Match the oldest available timestamp to the closest sample on the other
    # board. Unmatched older samples are discarded rather than interpolated.
    async def _match_source(self, source):
        forearm_buffer = self.forearm_buffer[source]
        paddle_buffer = self.paddle_buffer[source]
        while forearm_buffer and paddle_buffer:
            # anchor on whichever side's oldest sample is older
            if self._ts(forearm_buffer[0]) <= self._ts(paddle_buffer[0]):
                anchor_buffer, search_buffer = forearm_buffer, paddle_buffer
                anchor_is_forearm = True
            else:
                anchor_buffer, search_buffer = paddle_buffer, forearm_buffer
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
                await self.output_queue.put(paired_sensor_packet(forearm_sample, paddle_sample, self.matched_count + 1, self.session_id))
                self.matched_count += 1
                if self.matched_count == 1:
                    self.logger.info(
                        f"Synchroniser pairing begun: first forearm + paddle pair "
                        f"(timestamp difference = {diff:.2f}ms, tolerance = {self.tolerance_ms}ms)"
                    )
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
            "match_rate_percent": (
                100.0 * self.matched_count / total if total else 0.0
            ),
            "received_forearm": self.matched_count + self.unmatched_forearm,
            "received_paddle": self.matched_count + self.unmatched_paddle,
            "unmatched_forearm": self.unmatched_forearm,
            "unmatched_paddle": self.unmatched_paddle,
            "forearm_buffer": sum(map(len, self.forearm_buffer.values())),
            "paddle_buffer": sum(map(len, self.paddle_buffer.values())),
        }
