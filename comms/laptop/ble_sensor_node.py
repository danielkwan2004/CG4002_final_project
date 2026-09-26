import asyncio
import logging
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
    PKT_SENSOR_BATCH,
    PKT_SYNC_START,
    PKT_SYNC_END,
    PKT_HAPTIC_RESP,
    PKT_SENSOR_DATA,
    PKT_DUMMY,
    PKT_DUMMY_REPLY,
    SENSOR_BATCH_SIZE,
    MAX_SYNC_RTT_MS,
    BLE_WRITE_TIMEOUT_SECONDS,
)


SENSOR_SAMPLE_STRUCT = struct.Struct("<II6f")


class BLESensorNode:
    """
    BLE sensor node that connects to FireBeetle ESP32 devices, receives IMU data, and pushes it onto an asyncio.Queue.
    """

    def __init__(self, node_id: str, clock_resync: bool, queue: asyncio.Queue, logger, dummy_callback=None, streaming=True):
        self.node_id = node_id
        self.clock_resync = clock_resync
        self.queue = queue
        self.logger = logging.LoggerAdapter(logger, {"device": node_id})
        self.client: BleakClient | None = None
        self.clock_offset_ms = 0.0 
        self._sync_lock = asyncio.Lock()
        self._periodic_sync_task = None
        self._sync_requests = {}
        self._sync_responses = {}
        self._sync_waiters = {}
        self._write_lock = asyncio.Lock()
        self.dummy_callback = dummy_callback
        self.streaming = streaming
        self.ready = asyncio.Event()
        self.rx_bytes = 0
        self.rx_packets = 0

    async def _write_char_unlocked(self, payload: str, response: bool = True):
        """Write after the caller has acquired any required ordering lock."""
        if self.client is None or not self.client.is_connected:
            raise ConnectionError(f"[BLE] {self.node_id} is not connected")

        await asyncio.wait_for(
            self.client.write_gatt_char(
                WRITE_CHAR_UUID,
                payload.encode(),
                response,
            ),
            timeout=BLE_WRITE_TIMEOUT_SECONDS,
        )

    async def _write_char(self, payload: str, response: bool = True):
        async with self._write_lock:
            # Recheck the connection after acquiring the lock. It may have
            # disconnected while this coroutine was waiting.
            await self._write_char_unlocked(payload, response)

    async def run(self):
        while True:
            device = await BleakScanner.find_device_by_name(self.node_id, timeout=10.0)
            if device is None:
                self.logger.error(f"[BLE] Device not found, retrying in 3s...")
                await asyncio.sleep(1)
                continue

            # Force state cleanup on new connection attempt
            self.clock_offset_ms = 0.0
            self._sync_requests = {}
            self._sync_responses = {}
            self._sync_waiters = {}
            self._sync_lock = asyncio.Lock()

            # Reset periodic sync task if it exists
            if self._periodic_sync_task and not self._periodic_sync_task.done():
                self._periodic_sync_task.cancel()
            self._periodic_sync_task = None

            self.client = BleakClient(device.address, use_services_cache=False)
            try:
                if self.client.is_connected:
                    self.logger.warning(f"[BLE] Already connected, disconnecting first...")
                    await self.client.disconnect()
                
                await self.client.connect(timeout=5.0)
                self.logger.info("BLE connected")
                self.logger.debug(f"Device {device.name} at {device.address}")
                await self.client.start_notify(NOTIFY_CHAR_UUID, self._handle_notification)

                hello_req = json.dumps({"type": PKT_HELLO_REQ}, separators=(",", ":"))
                await self._write_char(hello_req)
                self.logger.debug(f"[HELLO] Sent HELLO_REQ")

                while self.client.is_connected:
                    await asyncio.sleep(1)  

                self.logger.warning(f"[BLE] Connection lost, will attempt to reconnect...")
                

            except asyncio.CancelledError:
                self.logger.debug(f"[BLE] Task cancelled")
                raise
            except Exception as e:
                self.logger.error(f"[BLE] Connection error: {e!r}")
            finally:
                await self.disconnect()

            await asyncio.sleep(2)  # Wait before attempting to reconnect


    async def disconnect(self):
        self.ready.clear()
        if self._periodic_sync_task:
            self._periodic_sync_task.cancel()
            await asyncio.gather(self._periodic_sync_task, return_exceptions=True)
            self._periodic_sync_task = None

        if self.client and self.client.is_connected:
            self.logger.info(f"[BLE] Disconnected from device")
            try:
                # Disconnect tears down notifications too; avoid a separate
                # cancellable CoreBluetooth stop-notify operation at shutdown.
                await self.client.disconnect()
            except Exception as e:
                self.logger.debug(f"[BLE] stop_notify or disconnect skipped/failed on disconnect: {e!r}")


    async def _handle_notification(self, sender, data: bytearray):
        self.rx_bytes += len(data)
        self.rx_packets += 1
        if len(data) >= 2 and data[0] == PKT_SENSOR_BATCH:
            sample_count = data[1]
            if not 1 <= sample_count <= SENSOR_BATCH_SIZE:
                self.logger.warning(f"[DATA] Invalid batch count: {sample_count}")
                return
            
            expected_length = 2 + sample_count * SENSOR_SAMPLE_STRUCT.size
            if len(data) != expected_length:
                self.logger.warning(
                    f"[DATA] Invalid batch length: "
                    f"received={len(data)}, expected={expected_length}"
                )
                return

            for index in range(sample_count):
                offset = 2 + index * SENSOR_SAMPLE_STRUCT.size
                sample = SENSOR_SAMPLE_STRUCT.unpack_from(data, offset)
                self._enqueue_sensor_sample(*sample)
            return
    
        try:
            raw = json.loads(data.decode())
            packet_type = raw.get("type")

            if packet_type == PKT_DUMMY_REPLY:
                self.logger.debug(f"[DUMMY] Reply: {raw}")
                if self.dummy_callback:
                    self.dummy_callback(raw)
                return

            if packet_type == PKT_HELLO:
                self.logger.debug(f"[RECV - HELLO] Received HELLO: {raw}")
                self._hello_received = True
                config = json.dumps({
                    "type": PKT_CONFIG, 
                    "sample_rate_hz": SAMPLE_FREQ,
                    "sync_reference_time": 0
                }, separators=(",", ":"))
                await self._write_char(config)
                self.logger.debug(f"[CONFIG] Sent CONFIG")
                return 

            if packet_type == PKT_CONFIG_ACK:
                if not self.streaming:
                    asyncio.create_task(self._synchronise_clock(5))
                    return
                self.logger.debug(
                    f"[RECV - CONFIG] Received CONFIG_ACK - starting clock sync"
                )
                asyncio.create_task(self._synchronise_clock(5))
                return

            if packet_type == PKT_SYNC_RESP:
                request_id = raw.get("request_id")
                waiter = self._sync_waiters.get(request_id)
                if waiter is not None and not waiter.done():
                    node_ts = float(raw["node_timestamp"])
                    t4 = time.monotonic_ns() / 1e6
                    waiter.set_result((node_ts, t4))
                self.logger.debug(f"[RECV - SYNC] Received SYNC_RESP")
                return

            if packet_type == PKT_HAPTIC_RESP:
                self.logger.info(f"Haptic response: {raw.get('status', 'unknown')}")
                self.logger.debug(f"[RECV - HAPTIC] Received HAPTIC_RESP: {raw}")
                return

            self.logger.debug(f"[RECV - UNHANDLED] Unhandled packet: {data}")
        except json.JSONDecodeError:
            self.logger.error(f"[RECV - MALFORMED] Malformed packet: {data}")

    def _enqueue_sensor_sample(self, sequence, raw_ts, ax, ay, az, gx, gy, gz):
        """Convert one binary sample and enqueue it without spawning a task."""
        packet = {
            "type": PKT_SENSOR_DATA,
            "node": self.node_id,
            "sequence": sequence,
            "raw_timestamp": float(raw_ts),
            "common_timestamp": float(raw_ts) - self.clock_offset_ms,
            "clock_offset_ms": self.clock_offset_ms,
            "acceleration": {"x": ax, "y": ay, "z": az},
            "gyroscope": {"x": gx, "y": gy, "z": gz},
        }
        if not self.streaming:
            self.logger.debug(f"[DATA] Triggered sensor sample: {packet}")
            if self.dummy_callback:
                self.dummy_callback(packet)
        else:
            self.queue.put_nowait(packet)


    async def _synchronise_clock(self, rounds: int = 3):
        """Estimate node_clock - laptop_monotonic_clock using lowest RTT."""
        async with self._sync_lock:
            # Keep exclusive ownership of the BLE writer for the complete
            # pause/probe/resume session. Haptic writes cannot interleave with
            # clock synchronisation or leave the FireBeetle paused.
            async with self._write_lock:
                await self._synchronise_clock_locked(rounds)

    async def _synchronise_clock_locked(self, rounds: int):
        self._sync_requests = {}
        self._sync_responses = {request_id: None for request_id in range(rounds)}
        self._sync_waiters = {}

        pause_request = json.dumps({"type": PKT_SYNC_START}, separators=(",", ":"))
        resume_request = json.dumps({"type": PKT_SYNC_END if self.streaming else PKT_SYNC_START}, separators=(",", ":"))

        try:
            pause_started = time.monotonic_ns() / 1e6
            await self._write_char_unlocked(pause_request)
            pause_ms = time.monotonic_ns() / 1e6 - pause_started
            self.logger.debug(
                f"[CLOCK SYNC] Streaming paused "
                f"(control write={pause_ms:.2f}ms)"
            )

            for request_id in range(rounds):
                loop = asyncio.get_running_loop()
                waiter = loop.create_future()
                self._sync_waiters[request_id] = waiter

                t1 = time.monotonic_ns() / 1e6
                self._sync_requests[request_id] = t1
                request = json.dumps({
                    "type": PKT_SYNC_REQ,
                    "request_id": request_id,
                }, separators=(",", ":"))

                try:
                    await self._write_char_unlocked(request)
                    t2 = time.monotonic_ns() / 1e6
                except Exception as e:
                    self.logger.warning(
                        f"[CLOCK SYNC] "
                        f"SYNC_REQ #{request_id} write failed: {e}"
                    )
                    continue

                try:
                    node_ts, t4 = await asyncio.wait_for(waiter, timeout=0.5)
                except asyncio.TimeoutError:
                    self.logger.warning(
                        f"[CLOCK SYNC] "
                        f"SYNC_REQ #{request_id} timed out"
                    )
                    continue

                rtt = t4 - t1
                write_wait = t2 - t1
                response_wait = max(0.0, t4 - t2)
                self._sync_responses[request_id] = (
                    node_ts,
                    (t1 + t4) / 2.0,
                    rtt,
                    write_wait,
                    response_wait,
                )
                self.logger.debug(
                    f"[CLOCK SYNC] SYNC_REQ #{request_id}: "
                    f"RTT={rtt:.2f}ms, write_wait={write_wait:.2f}ms, "
                    f"response_wait={response_wait:.2f}ms"
                )
                # await asyncio.sleep(0.02)

            valid = [
                value for value in self._sync_responses.values()
                if value is not None and value[2] <= MAX_SYNC_RTT_MS
            ]

            if valid:
                node_ts, midpoint, rtt, write_wait, response_wait = min(
                    valid, key=lambda value: value[2]
                )
                new_offset = node_ts - midpoint

                if self.clock_offset_ms == 0.0:
                    self.clock_offset_ms = new_offset
                else:
                    alpha = 0.2
                    self.clock_offset_ms = (
                        alpha * new_offset
                        + (1 - alpha) * self.clock_offset_ms
                    )

                self.logger.info(f"Clock synchronised: best RTT={rtt:.2f}ms")
                self.logger.debug(
                    f"[CLOCK SYNC] Clock offset="
                    f"{self.clock_offset_ms:.2f}ms, best RTT={rtt:.2f}ms "
                    f"(write={write_wait:.2f}ms, response={response_wait:.2f}ms)"
                )
            else:
                received = sum(
                    value is not None for value in self._sync_responses.values()
                )
                self.logger.warning(
                    f"[CLOCK SYNC] Clock sync skipped: "
                    f"{received}/{rounds} responses, none below "
                    f"{MAX_SYNC_RTT_MS:.0f}ms RTT"
                )
        finally:
            try:
                await self._write_char_unlocked(resume_request)
                self.logger.info("[CLOCK SYNC] Streaming resumed" if self.streaming else "[CLOCK SYNC] Keyboard ready; streaming remains paused")
                self.ready.set()
            except Exception as e:
                self.logger.warning(
                    f"[CLOCK SYNC] Failed to resume streaming: {e}"
                )

        if self.clock_resync and (self._periodic_sync_task is None or self._periodic_sync_task.done()):
            self._periodic_sync_task = asyncio.create_task(
                self._periodic_clock_sync()
            )


    async def _periodic_clock_sync(self, interval_seconds: float = 60.0):
        # Keep the nodes half a period apart so they do not compete for the
        # laptop Bluetooth controller during clock synchronisation.
        first_delay = interval_seconds
        if self.node_id == "paddle":
            first_delay += interval_seconds / 2.0
        await asyncio.sleep(first_delay)

        while self.client and self.client.is_connected:
            if self.client and self.client.is_connected:
                try:
                    self.logger.debug(f"[CLOCK SYNC] Performing periodic clock sync...")
                    await self._synchronise_clock()
                except Exception as e:
                    self.logger.warning(
                        f"[CLOCK SYNC] Periodic clock sync failed: {e}"
                    )
            await asyncio.sleep(interval_seconds)


    async def send_haptic(self, haptic_json: str):
        try:
            await self._write_char(haptic_json)
            self.logger.debug(
                f"[HAPTIC] Sent HAPTIC_CMD: {haptic_json}"
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.warning(
                f"[HAPTIC] Failed to send haptic: {e!r}"
            )
            return False

    async def send_dummy(self, key: str, sequence: int):
        packet = json.dumps({
            "type": PKT_DUMMY, 
            "key": key, 
            "sequence": sequence,
            "sent_ms": time.monotonic_ns() // 1_000_000
            }, separators=(",", ":"))
        try:
            await self._write_char(packet)
            self.logger.debug(f"[DUMMY] Sent dummy packet: {packet}")
            return True
        except Exception as e:
            self.logger.warning(f"[DUMMY] Send failed: {e!r}")
            return False
