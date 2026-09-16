import asyncio
import json
import struct
import time
from bleak import BleakClient, BleakScanner
from constants import (
    NOTIFY_CHAR_UUID,
    WRITE_CHAR_UUID, 
    SAMPLE_FREQ,
    PKT_HELLO_REQ, 
    PKT_HELLO, 
    PKT_CONFIG, 
    PKT_CONFIG_ACK, 
    PKT_SYNC_REQ, 
    PKT_SYNC_RESP,
    PKT_SENSOR_DATA
)


class BLESensorNode:
    """
    BLE sensor node that connects to FireBeetle ESP32 devices, receives IMU data, and pushes it onto an asyncio.Queue.
    """

    def __init__(self, node_id: str, queue: asyncio.Queue, logger):
        self.node_id = node_id
        self.queue = queue
        self.logger = logger
        self.client: BleakClient | None = None
        self.clock_offset_ms = 0.0  # node clock minus laptop monotonic clock
        self._sync_lock = asyncio.Lock()
        self._periodic_sync_task = None
        self._sync_requests = {}
        self._sync_responses = {}
        self._sync_event = asyncio.Event()


    async def run(self):
        while True:
            device = await BleakScanner.find_device_by_name(self.node_id, timeout=10.0)
            if device is None:
                self.logger.error(f"[BLE - {self.node_id}] Device not found, retrying in 3s...")
                await asyncio.sleep(3)
                continue

            self.client = BleakClient(device.address, use_services_cache=False)
            try:
                if self.client.is_connected:
                    self.logger.warning(f"[BLE - {self.node_id}] Already connected, disconnecting first...")
                    await self.client.disconnect()
                
                await self.client.connect(timeout=5.0)
                self.logger.info(f"[BLE - {self.node_id}] Connected to {device.name} at {device.address}")
                await self.client.start_notify(NOTIFY_CHAR_UUID, self._handle_notification)

                hello_req = json.dumps({"type": PKT_HELLO_REQ}, separators=(",", ":"))
                await self.client.write_gatt_char(WRITE_CHAR_UUID, hello_req.encode(), response=True)
                self.logger.info(f"[BLE - {self.node_id}] Sent HELLO_REQ")

                while self.client.is_connected:
                    await asyncio.sleep(1)  

                self.logger.warning(f"[BLE - {self.node_id}] Connection lost, will attempt to reconnect...")
                

            except asyncio.CancelledError:
                self.logger.info(f"[BLE - {self.node_id}] Task cancelled")
                await self.disconnect()
                raise
            except Exception as e:
                self.logger.error(f"[BLE - {self.node_id}] Connection error: {e}")
            finally:
                if self.client and self.client.is_connected:
                    await self.disconnect()

            await asyncio.sleep(2)  # Wait before attempting to reconnect


    async def disconnect(self):
        if self._periodic_sync_task:
            self._periodic_sync_task.cancel()
            await asyncio.gather(self._periodic_sync_task, return_exceptions=True)
            self._periodic_sync_task = None

        if self.client and self.client.is_connected:
            self.logger.info(f"[BLE - {self.node_id}] Disconnected from device")
            await self.client.stop_notify(NOTIFY_CHAR_UUID)
            await self.client.disconnect()


    async def _handle_notification(self, sender, data: bytearray):
        if len(data) == 33 and data[0] == PKT_SENSOR_DATA:
            _, sequence, raw_ts, ax, ay, az, gx, gy, gz = struct.unpack("<BII6f", data)

            packet = {
                "type": PKT_SENSOR_DATA,
                "node": self.node_id,
                "sequence": sequence,
                "raw_timestamp": float(raw_ts),
                "common_timestamp": float(raw_ts) - self.clock_offset_ms,
                "clock_offset_ms": self.clock_offset_ms,
                "acceleration": {"x": ax, "y": ay, "z": az},
                "gyroscope": {"x": gx, "y": gy, "z": gz}
            }
            asyncio.create_task(self.queue.put(packet))
            self.logger.debug(f"[BLE - {self.node_id}] Received packet: {packet}")
            return
    
        try:
            raw = json.loads(data.decode())
            packet_type = raw.get("type")

            if packet_type == PKT_HELLO:
                self.logger.info(f"[BLE - {self.node_id}] Received HELLO: {raw}")
                self._hello_received = True
                config = json.dumps({
                    "type": PKT_CONFIG, 
                    "sample_rate_hz": SAMPLE_FREQ,
                    "sync_reference_time": 0
                }, separators=(",", ":"))
                await self.client.write_gatt_char(WRITE_CHAR_UUID, config.encode(), response=True)
                self.logger.info(f"[BLE - {self.node_id}] Sent CONFIG")
                return 

            if packet_type == PKT_CONFIG_ACK:
                self.logger.info(f"[BLE - {self.node_id}] Received CONFIG_ACK - now streaming")
                asyncio.create_task(self._synchronise_clock())
                return

            if packet_type == PKT_SYNC_RESP:
                request_id = raw.get("request_id")
                if request_id in self._sync_responses:
                    node_ts = float(raw["node_timestamp"])
                    t4 = time.monotonic_ns() / 1_000_000.0
                    t1 = self._sync_requests[request_id]
                    self._sync_responses[request_id] = (
                        node_ts, (t1 + t4) / 2.0, t4 - t1
                    )
                    self._sync_event.set()
                self.logger.info(f"[BLE - {self.node_id}] Received SYNC_RESP")
                return

            self.logger.debug(f"[BLE - {self.node_id}] Unhandled packet: {data}")
        except json.JSONDecodeError:
            self.logger.error(f"[BLE - {self.node_id}] Malformed packet: {data}")


    async def _synchronise_clock(self, rounds: int = 5):
        """Estimate node_clock - laptop_monotonic_clock using lowest RTT."""
        async with self._sync_lock:
            self._sync_requests = {}
            self._sync_responses = {request_id: None for request_id in range(rounds)}
            self._sync_event = asyncio.Event()
            for request_id in range(rounds):
                t1 = time.monotonic_ns() / 1_000_000.0
                self._sync_requests[request_id] = t1
                request = json.dumps({
                    "type": PKT_SYNC_REQ, 
                    "request_id": request_id
                }, separators=(",", ":"))
                await self.client.write_gatt_char(
                    WRITE_CHAR_UUID, request.encode(), response=True
                )
                self.logger.info(f"[BLE - {self.node_id}] Sent SYNC_REQ")
                try:
                    await asyncio.wait_for(self._sync_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                self._sync_event.clear()
                await asyncio.sleep(0.02)

            valid = [v for v in self._sync_responses.values() if v is not None and len(v) == 3]
            if valid:
                node_ts, midpoint, rtt = min(valid, key=lambda v: v[2])
                self.clock_offset_ms = node_ts - midpoint
                self.logger.info(
                    f"[BLE - {self.node_id}] Clock offset="
                    f"{self.clock_offset_ms:.2f}ms, best RTT={rtt:.2f}ms"
                )

                if self._periodic_sync_task is None:
                    self._periodic_sync_task = asyncio.create_task(self._periodic_clock_sync(30.0))
            else:
                self.logger.warning(f"[BLE - {self.node_id}] Clock sync failed")


    async def _periodic_clock_sync(self, interval_seconds: float = 30.0):
        while self.client and self.client.is_connected:
            await asyncio.sleep(interval_seconds)

            if self.client and self.client.is_connected:
                try:
                    await self._synchronise_clock()
                except Exception as exc:
                    self.logger.warning(
                        f"[BLE - {self.node_id}] Periodic clock sync failed: {exc}"
                    )


    async def send_haptic(self, haptic_json: str):
        if self.client and self.client.is_connected:
            try:
                await self.client.write_gatt_char(WRITE_CHAR_UUID, haptic_json.encode(), response=True)
                self.logger.info(f"[BLE - {self.node_id}] Sent HAPTIC_CMD: {haptic_json}")
            except Exception as e:
                self.logger.warning(f"[BLE - {self.node_id}] Failed to send haptic (likely shutting down): {e}")
        else:
            self.logger.warning(f"[BLE - {self.node_id}] Cannot send haptic, not connected")
