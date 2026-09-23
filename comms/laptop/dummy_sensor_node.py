import asyncio
import random
import time


class DummySensorNode:
    """
    Simulates a single FireBeetle node generating fake 6-axis IMU packets
    at ~200Hz, pushing them onto an asyncio.Queue.
    """

    def __init__(self, node_id: str, queue: asyncio.Queue, logger, sample_rate_hz: int = 200):
        self.node_id = node_id
        self.queue = queue
        self.logger = logger
        self.interval = 1.0 / sample_rate_hz
        self.seq = 0
        self._running = True

    async def run(self):
        await asyncio.sleep(3)
        self.logger.info(f"[{self.node_id}] Starting dummy sensor stream at {1/self.interval:.0f}Hz")
        while self._running:
            packet = self._generate_packet()
            await self.queue.put(packet)
            self.logger.debug(f"[{self.node_id}] Dummy packet : {packet}")
            await asyncio.sleep(self.interval)

    def _generate_packet(self) -> dict:
        self.seq += 1
        timestamp = time.monotonic_ns() / 1e6  # timestamp in milliseconds
        return {
            "node": self.node_id,
            "sequence": self.seq,
            # dummy source already uses laptop monotonic clock, so no need to adjust for clock offset
            "timestamp": timestamp,
            "raw_timestamp": timestamp,
            "common_timestamp": timestamp,
            "acceleration": {
                "x": round(random.uniform(-2, 2), 2),
                "y": round(random.uniform(-2, 2), 2),
                "z": round(random.uniform(8, 11), 2),  # dummy acceleration data
            },
            "gyroscope": {
                "x": round(random.uniform(-50, 50), 2),
                "y": round(random.uniform(-50, 50), 2),
                "z": round(random.uniform(-50, 50), 2), # dummy gyroscope data
            },
        }

    def stop(self):
        self._running = False
