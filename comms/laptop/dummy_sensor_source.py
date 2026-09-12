import asyncio
import time
import random


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
        self.logger.info(f"[{self.node_id}] Starting dummy sensor stream at {1/self.interval:.0f}Hz")
        while self._running:
            packet = self._generate_packet()
            await self.queue.put(packet)
            self.logger.debug(f"[{self.node_id}] seq={packet['sequence']} ts={packet['timestamp']}")
            await asyncio.sleep(self.interval)

    def _generate_packet(self) -> dict:
        self.seq += 1
        return {
            "node": self.node_id,
            "sequence": self.seq,
            "timestamp": time.time() * 1000,  # ms
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