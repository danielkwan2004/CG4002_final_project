# One instance manages one FireBeetle: connect, configure, synchronise its clock,
# decode notifications, and enqueue samples for the shared laptop synchroniser.
import asyncio
import logging
import json
import time

from bleak import BleakClient, BleakScanner
import _bootstrap
from utilities.constants import (
    PacketType,
    BLE_WRITE_TIMEOUT_SECONDS,
    MAX_SYNC_RTT_MS,
    NOTIFY_CHAR_UUID,
    packet_type_name,
    SENSOR_BATCH_SIZE,
    SENSOR_SAMPLE_STRUCT,
    SENSOR_SOURCES,
    WRITE_CHAR_UUID,
)


from utilities.logger_setup import format_packet_for_log

# Maximum attempt durations, not fixed startup delays. A successful step returns
# immediately; the outer connection budget also leaves time for native cleanup.
BLE_CONNECT_TIMEOUT_SECONDS = 5.0
BLE_SETUP_TIMEOUT_SECONDS = 5.0
BLE_CLEANUP_TIMEOUT_SECONDS = 2.0


# Wire layout: type/count/source (one byte each), then count little-endian
# <II6f samples: sequence, node uptime in ms, acceleration XYZ, gyroscope XYZ.
def decode_sensor_batch(payload):
    """Validate a binary batch and unpack sequence, timestamp and six IMU axes."""
    if len(payload) < 3 or payload[0] != PacketType.SENSOR_BATCH:
        raise ValueError("expected SENSOR_BATCH (0x09)")

    count = payload[1]
    if not 1 <= count <= SENSOR_BATCH_SIZE or len(payload) != 3 + count * SENSOR_SAMPLE_STRUCT.size:
        raise ValueError("invalid count/length (expected 3 + 32 * count bytes)")
    source = payload[2]

    if source not in SENSOR_SOURCES:
        raise ValueError("unknown sensor source (expected 0 = normal or 1 = dummy)")

    # Append the source to each unpacked sample for later identification.
    return [(*SENSOR_SAMPLE_STRUCT.unpack_from(payload, 3 + i * SENSOR_SAMPLE_STRUCT.size), source)
            for i in range(count)]


class BLESensorNode:
    """
    BLE sensor node that connects to FireBeetle ESP32 devices, receives IMU data, and pushes it onto an asyncio.Queue.
    """

    def __init__(self, node_id: str, clock_resync: bool, queue: asyncio.Queue, logger, streaming=True, connection_lock=None):
        self.node_id = node_id
        self.clock_resync = clock_resync
        self.queue = queue
        self.logger = logging.LoggerAdapter(logger, {"device": node_id})
        self.client: BleakClient | None = None
        self._last_device = None
        self.clock_offset_ms = 0.0
        self._clock_valid = False
        self._setup_task = None
        self._connection_lock = connection_lock or asyncio.Lock()
        self._sync_lock = asyncio.Lock()
        self._periodic_sync_task = None
        self._sync_responses = {}
        self._sync_waiters = {}
        self._write_lock = asyncio.Lock()
        self._capture_until = 0.0
        self.streaming = streaming
        self.ready = asyncio.Event()
        self.rx_bytes = 0
        self.rx_packets = 0
        self._latency_request_id = 1_000_000

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
        self.logger.debug("[BLE TX] %s", format_packet_for_log(payload))

    async def _write_char(self, payload: str, response: bool = True):
        async with self._write_lock:
            # Recheck the connection after acquiring the lock. It may have
            # disconnected while this coroutine was waiting.
            await self._write_char_unlocked(payload, response)

    async def run(self):
        while True:
            stage = "discovery"
            try:
                # Only setup is serialised; both established connections run together.
                async with self._connection_lock:
                    self.ready.clear()
                    self.clock_offset_ms = 0.0
                    self._clock_valid = False
                    self._capture_until = 0.0
                    self._sync_responses.clear()
                    self.logger.debug("[BLE] Discovering device")
                    device = await BleakScanner.find_device_by_name(self.node_id, timeout=10.0)
                    if device is None:
                        if self._last_device is None:
                            raise ConnectionError("device not found")
                        self.logger.warning("[BLE] No fresh advertisement; retrying previously discovered %s", self.node_id)
                        device = self._last_device
                        
                    self._last_device = device
                    stage = "connect/service discovery"
                    self.logger.debug("[BLE] Connecting to discovered device")
                    self.client = BleakClient(device, timeout=BLE_CONNECT_TIMEOUT_SECONDS)
                    # Bleak's native timeout must fire first so CoreBluetooth can
                    # cancel its pending connection. Also bound service discovery.
                    await asyncio.wait_for(self.client.connect(),
                        BLE_CONNECT_TIMEOUT_SECONDS + BLE_SETUP_TIMEOUT_SECONDS + BLE_CLEANUP_TIMEOUT_SECONDS)
                    self.logger.info("BLE connected")
                    stage = "notification subscription/HELLO/configuration/clock sync"
                    await asyncio.wait_for(self._complete_setup(), timeout=BLE_SETUP_TIMEOUT_SECONDS)
                    self.logger.debug("[BLE] Setup complete")
                stage = "sampling"
                while self.client.is_connected:
                    await asyncio.sleep(0.5)

                self.logger.warning("[BLE] Connection lost; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.error("[BLE] Connection error during %s: %r", stage, exc)
            finally:
                await self.disconnect()
            await asyncio.sleep(2)

    async def _complete_setup(self):
        await self.client.start_notify(NOTIFY_CHAR_UUID, self._handle_notification)
        await self._write_char(json.dumps({"type": PacketType.HELLO_REQ}))
        await self.ready.wait()

    async def disconnect(self):
        self.ready.clear()
        if self._setup_task:
            self._setup_task.cancel()
            await asyncio.gather(self._setup_task, return_exceptions=True)
            self._setup_task = None
        if self._periodic_sync_task:
            self._periodic_sync_task.cancel()
            await asyncio.gather(self._periodic_sync_task, return_exceptions=True)
            self._periodic_sync_task = None

        self.ready.clear()
        for waiter in self._sync_waiters.values():
            if not waiter.done():
                waiter.set_exception(ConnectionError("BLE disconnected during request"))
        self._sync_waiters.clear()
        client, self.client = self.client, None
        if client:
            self.logger.debug("[BLE] Cleaning up connection attempt")
            try:
                # Disconnect tears down notifications too; avoid a separate
                # cancellable CoreBluetooth stop-notify operation at shutdown.
                await asyncio.wait_for(client.disconnect(), timeout=BLE_CLEANUP_TIMEOUT_SECONDS)
            except Exception as e:
                self.logger.debug(f"[BLE] stop_notify or disconnect skipped/failed on disconnect: {e!r}")


    async def _handle_notification(self, sender, data: bytearray):
        self.rx_bytes += len(data)
        self.rx_packets += 1
        if data and data[0] == PacketType.SENSOR_BATCH:
            try:
                samples = decode_sensor_batch(data)
            except ValueError as exc:
                self.logger.warning(f"[DATA] Rejected sensor batch: {exc}")
                return

            self.logger.debug(
                "[SENSOR RX] type=%s source=%s count=%d bytes=%d",
                packet_type_name(data[0]), SENSOR_SOURCES[data[2]], len(samples), len(data),
            )
            for sample in samples:
                self.logger.debug(
                    "[SENSOR RX] source=%s sequence=%d timestamp_ms=%d "
                    "acceleration=(x=%.6g, y=%.6g, z=%.6g) "
                    "gyroscope=(x=%.6g, y=%.6g, z=%.6g)", SENSOR_SOURCES[sample[-1]], *sample[:-1],
                )
                self._enqueue_sensor_sample(*sample)
            return

        try:
            raw = json.loads(data.decode())
            packet_type = raw.get("type")
            self.logger.debug("[BLE RX] %s", format_packet_for_log(raw))

            if packet_type == PacketType.HELLO:
                if raw.get("node_id", self.node_id) != self.node_id:
                    self.logger.error("[BLE] Expected %s, received HELLO from %s", self.node_id, raw.get("node_id"))
                    await self.client.disconnect()
                    return
                self.logger.debug(f"[RECV - HELLO] Received HELLO: {format_packet_for_log(raw)}")
                config = json.dumps({
                    "type": PacketType.CONFIG,
                    "continuous": self.streaming
                }, separators=(",", ":"))
                await self._write_char(config)
                self.logger.debug(f"[CONFIG] Sent CONFIG")
                return

            if packet_type == PacketType.CONFIG_ACK:
                self.logger.debug(
                    f"[RECV - CONFIG] Received CONFIG_ACK - starting clock sync"
                )
                if self._setup_task is None or self._setup_task.done():
                    self._setup_task = asyncio.create_task(self._initial_clock_sync())
                return

            if packet_type == PacketType.SYNC_RESP:
                request_id = raw.get("request_id")
                waiter = self._sync_waiters.get(request_id)
                if waiter is not None and not waiter.done():
                    node_ts = float(raw["node_timestamp"])
                    t4 = time.monotonic_ns() / 1e6
                    waiter.set_result((node_ts, t4))
                self.logger.debug(f"[RECV - SYNC] Received SYNC_RESP")
                return

            if packet_type == PacketType.HAPTIC_RESP:
                self.logger.info(f"Haptic response: {raw.get('status', 'unknown')}")
                self.logger.debug(f"[RECV - HAPTIC] Received HAPTIC_RESP: {format_packet_for_log(raw)}")
                return

            self.logger.debug(f"[RECV - UNHANDLED] Unhandled packet: {format_packet_for_log(raw)}")
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            self.logger.error(f"[RECV - MALFORMED] Malformed packet: {data}")

    # Offset = node clock minus laptop clock, so subtract it to pair both boards
    # on the laptop monotonic timebase. Neither clock is a UTC timestamp.
    def _enqueue_sensor_sample(self, sequence, raw_ts, ax, ay, az, gx, gy, gz, source):
        """Convert one binary sample and enqueue it without spawning a task."""
        packet = {
            "type": PacketType.SENSOR_DATA,
            "node": self.node_id,
            "source": SENSOR_SOURCES[source],
            "sequence": sequence,
            "raw_timestamp": float(raw_ts),
            "common_timestamp": float(raw_ts) - self.clock_offset_ms,
            "clock_offset_ms": self.clock_offset_ms,
            "acceleration": {"x": ax, "y": ay, "z": az},
            "gyroscope": {"x": gx, "y": gy, "z": gz},
        }
        self.queue.put_nowait(packet)


    async def _initial_clock_sync(self):
        try:
            for _ in range(3):
                await self._synchronise_clock(5)
                if self.ready.is_set():
                    return
                await asyncio.sleep(0.2)
            self.logger.error("[CLOCK SYNC] Setup has no valid clock; reconnecting after setup timeout")
        except Exception as exc:
            self.logger.error("[CLOCK SYNC] Setup failed: %r", exc)

    async def _synchronise_clock(self, rounds: int = 3):
        """Estimate node_clock - laptop_monotonic_clock using lowest RTT."""
        async with self._sync_lock:
            # Keep exclusive ownership of the BLE writer for the complete
            # pause/probe/resume session. Haptic writes cannot interleave with
            # clock synchronisation or leave the FireBeetle paused.
            async with self._write_lock:
                # Recheck after acquiring the lock: a capture may have been
                # scheduled while this resync was waiting behind a BLE write.
                if time.monotonic() < self._capture_until:
                    return
                self.ready.clear()
                await self._synchronise_clock_locked(rounds)

    async def _synchronise_clock_locked(self, rounds: int):
        self._sync_responses = {request_id: None for request_id in range(rounds)}
        pause_request = json.dumps({"type": PacketType.SYNC_START}, separators=(",", ":"))
        resume_request = json.dumps({"type": PacketType.SYNC_END}, separators=(",", ":"))

        try:
            pause_started = time.monotonic_ns() / 1e6
            await self._write_char_unlocked(pause_request)
            pause_ms = time.monotonic_ns() / 1e6 - pause_started
            self.logger.debug(
                f"[CLOCK SYNC] Streaming paused "
                f"(control write={pause_ms:.2f}ms)"
            )

            for request_id in range(rounds):
                try:
                    node_ts, t1, t2, t4 = await self._request_sync_reply(
                        request_id, self._write_char_unlocked, timeout=0.5)
                except Exception as exc:
                    self.logger.warning("[CLOCK SYNC] SYNC_REQ #%d failed: %r", request_id, exc)
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

                self._clock_valid = True
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
                if self._clock_valid:
                    await self._write_char_unlocked(resume_request)
                    self.logger.info("[CLOCK SYNC] Streaming resumed" if self.streaming else "[CLOCK SYNC] Keyboard ready; sampler idle until capture")
                    self.ready.set()
            except Exception as e:
                self.logger.warning(
                    f"[CLOCK SYNC] Failed to resume streaming: {e}"
                )

        if self._clock_valid and self.clock_resync and (self._periodic_sync_task is None or self._periodic_sync_task.done()):
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
            if self.client and self.client.is_connected and time.monotonic() >= self._capture_until:
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
                f"[HAPTIC] Sent HAPTIC_CMD: {format_packet_for_log(haptic_json)}"
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.warning(
                f"[HAPTIC] Failed to send haptic: {e!r}"
            )
            return False

    async def send_capture(self, start_ms: float):
        """Schedule a one-second burst, decoded just like continuous samples."""
        try:
            async with self._write_lock:
                if not self.ready.is_set() or time.monotonic_ns() / 1e6 >= start_ms:
                    return False
                self._capture_until = start_ms / 1000 + 1.1
                packet = json.dumps({
                    "type": PacketType.DUMMY,
                    "start_timestamp": round(start_ms + self.clock_offset_ms) & 0xFFFFFFFF,
                }, separators=(",", ":"))
                await self._write_char_unlocked(packet)
            return True
        except Exception as exc:
            self.logger.warning(f"[CAPTURE] Send failed: {exc!r}")
            return False

    # Register before writing: a notification may arrive before the write await
    # returns. Request IDs keep clock-sync and diagnostic replies separate.
    async def _request_sync_reply(self, request_id, write, timeout):
        """Shared timed request/reply for clock synchronisation and BLE RTT."""
        waiter = asyncio.get_running_loop().create_future()
        self._sync_waiters[request_id] = waiter
        try:
            started = time.monotonic_ns() / 1e6
            await write(json.dumps({"type": PacketType.SYNC_REQ, "request_id": request_id}))
            written = time.monotonic_ns() / 1e6
            node_ts, received = await asyncio.wait_for(waiter, timeout)
            return node_ts, started, written, received
        finally:
            self._sync_waiters.pop(request_id, None)
            if not waiter.done():
                waiter.cancel()
            elif not waiter.cancelled():
                waiter.exception()  # Consume a disconnect error even if the write failed first.

    async def measure_latency(self):
        """Ping the node; RTT is reply time minus send time on the laptop clock."""
        if not self.ready.is_set() or time.monotonic() < self._capture_until:
            return
        self._latency_request_id += 1
        try:
            # _write_char locks only the write, not the wait for the reply.
            _, started, _, received = await self._request_sync_reply(
                self._latency_request_id, self._write_char, timeout=1.0)
            self.logger.debug("[LATENCY] laptop <-> %s BLE: RTT=%.2fms",
                             self.node_id, received - started)
        except Exception as exc:
            self.logger.debug("[LATENCY] BLE probe failed: %r", exc)
