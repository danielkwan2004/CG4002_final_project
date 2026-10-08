# Pair samples only within the same source (stream or dummy). Both sources use
# identical matching rules and produce the same MQTT payload schema.
import asyncio
import uuid
import time
from collections import deque
import _bootstrap
from utilities.constants import (PacketType, SENSOR_SOURCES)


def paired_sensor_packet(forearm, paddle, sensor_seq, session_id):
    """Shared payload for paired or single-sensor samples; absence is explicit."""
    if forearm is None and paddle is None:
        raise ValueError("At least one sensor is required")
    available = [sample for sample in (forearm, paddle) if sample is not None]
    if len(available) == 2 and forearm["source"] != paddle["source"]:
        raise ValueError("Cannot pair normal and dummy samples")
    return {
        "type": PacketType.SENSOR_DATA,
        "source": available[0]["source"],
        "sensor_seq": sensor_seq,
        "session_id": session_id,
        "timestamp": int(round(min(sample["common_timestamp"] for sample in available))),
        "forearm_seq": forearm["sequence"] if forearm is not None else None,
        "paddle_seq": paddle["sequence"] if paddle is not None else None,
        "forearm": {k: forearm[k] for k in ("acceleration", "gyroscope")} if forearm is not None else None,
        "paddle": {k: paddle[k] for k in ("acceleration", "gyroscope")} if paddle is not None else None,
    }


class Synchroniser:
    """Pair two timestamp-corrected streams on the laptop timebase."""

    def __init__(
        self, 
        forearm_queue,
        paddle_queue,
        output_queue,
        logger,
        tolerance_ms=2.5,
        pairing_timeout_ms=100,
    ):
        self.forearm_queue = forearm_queue
        self.paddle_queue = paddle_queue
        self.output_queue = output_queue
        self.logger = logger
        self.tolerance_ms = tolerance_ms
        if pairing_timeout_ms <= 0:
            raise ValueError("pairing_timeout_ms must be positive")
        self.pairing_timeout = pairing_timeout_ms / 1000
        self.sensor_seq = 0
        self.single_forearm = 0
        self.single_paddle = 0
        self.max_buffer_len = 200   # 1 sec worth of samples at 200Hz
        self.forearm_buffer = {source: deque(maxlen=self.max_buffer_len) for source in SENSOR_SOURCES.values()}
        self.paddle_buffer = {source: deque(maxlen=self.max_buffer_len) for source in SENSOR_SOURCES.values()}
        self.matched_count = 0
        self.session_id = uuid.uuid4().hex

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
                    timeout=self.pairing_timeout,
                )
                if forearm_get in done:
                    sample = dict(forearm_get.result(), _queued_at=time.monotonic())
                    self.forearm_buffer[sample["source"]].append(sample)
                    forearm_get = asyncio.create_task(self.forearm_queue.get())
                if paddle_get in done:
                    sample = dict(paddle_get.result(), _queued_at=time.monotonic())
                    self.paddle_buffer[sample["source"]].append(sample)
                    paddle_get = asyncio.create_task(self.paddle_queue.get())
                await self._match_available()
        finally:
            forearm_get.cancel()
            paddle_get.cancel()
            await asyncio.gather(forearm_get, paddle_get, return_exceptions=True)

    async def _match_available(self):
        for source in SENSOR_SOURCES.values():
            await self._match_source(source)

    async def _emit(self, forearm, paddle):
        self.sensor_seq += 1
        await self.output_queue.put(paired_sensor_packet(
            forearm, paddle, self.sensor_seq, self.session_id))
        if paddle is None:
            self.single_forearm += 1
        elif forearm is None:
            self.single_paddle += 1

    # Match the oldest available timestamp to the closest sample on the other
    # board. Unmatched older samples are published with the other sensor absent.
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
                await self._emit(forearm_sample, paddle_sample)
                self.matched_count += 1
                if self.matched_count == 1:
                    self.logger.info(
                        f"Synchroniser pairing begun: first forearm + paddle pair "
                        f"(timestamp difference = {diff:.2f}ms, tolerance = {self.tolerance_ms}ms)"
                    )
                continue

            # No match close enough: publish the older sample on its own.
            if anchor_is_forearm:
                await self._emit(anchor_buffer.popleft(), None)
            else:
                await self._emit(None, anchor_buffer.popleft())

        # A timer also flushes the final samples when both streams stop.
        now = time.monotonic()
        for buffer, is_forearm in ((forearm_buffer, True), (paddle_buffer, False)):
            while buffer:
                sample = buffer[0]
                if now - sample.setdefault("_queued_at", now) < self.pairing_timeout:
                    break
                buffer.popleft()
                await self._emit(sample if is_forearm else None, None if is_forearm else sample)

    def stats(self):
        # Each pair accounts for two sensor samples. Pending samples are
        # excluded until they are paired or emitted individually.
        paired_samples = 2 * self.matched_count
        total = paired_samples + self.single_forearm + self.single_paddle
        return {
            "matched": self.matched_count,
            "published": self.sensor_seq,
            "single_forearm": self.single_forearm,
            "single_paddle": self.single_paddle,
            "match_rate_percent": (
                100.0 * paired_samples / total if total else 0.0
            ),
            "received_forearm": self.matched_count + self.single_forearm,
            "received_paddle": self.matched_count + self.single_paddle,
            "forearm_buffer": sum(map(len, self.forearm_buffer.values())),
            "paddle_buffer": sum(map(len, self.paddle_buffer.values())),
        }
