"""Capture movement-gated CG4002 BLE telemetry. Requires bleak for live use."""
import argparse
import asyncio
import csv
import json
import math
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

SERVICE_UUID = "b26b1000-0ec1-4b8c-9f78-f25e5c9d4002"
NOTIFY_UUID = "b26b1001-0ec1-4b8c-9f78-f25e5c9d4002"
STATUS_UUID = "b26b1002-0ec1-4b8c-9f78-f25e5c9d4002"
HEADER = struct.Struct("<2sBBBBIII")
SAMPLE = struct.Struct("<III6fBB")
FIELDS = ["node", "boot", "session", "burst", "seq", "timestamp_us", "interval_us",
          "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps", "status", "event"]


def decode_packet(data):
    if len(data) < HEADER.size:
        raise ValueError("short header")
    magic, version, node, count, reserved, boot, session, burst = HEADER.unpack_from(data)
    if (magic != b"CG" or version != 1 or not node or reserved or not burst
            or not 1 <= count <= 4 or len(data) != HEADER.size + count*SAMPLE.size):
        raise ValueError("invalid protocol/header/length")
    rows = []
    for i in range(count):
        values = SAMPLE.unpack_from(data, HEADER.size+i*SAMPLE.size)
        if not all(math.isfinite(x) for x in values[3:9]):
            raise ValueError("nonfinite sensor value")
        if values[9] not in (14, 15) or values[10] not in (0, 1, 2):
            raise ValueError("invalid movement flags")
        row = dict(zip(FIELDS, (node, boot, session, burst, *values)))
        if rows and not 0 < ((row['seq']-rows[-1]['seq']) & 0xffffffff) < 0x80000000:
            raise ValueError("unordered batch")
        if (row['event'] == 1 and i != 0) or (row['event'] == 2 and i != count-1):
            raise ValueError("invalid boundary location")
        rows.append(row)
    return rows


class Capture:
    def __init__(self):
        self.bursts = {}
        self.seen = {}
        self.received = self.invalid = self.host_drops = 0

    def ingest(self, row):
        key = '/'.join(str(row[k]) for k in ('node', 'boot', 'session', 'burst'))
        b = self.bursts.setdefault(key, dict(received=0, duplicates=0, reordered=0,
            sequence_gaps=0, start_observed=False, end_observed=False, first_seq=row['seq'], last_seq=None))
        seen = self.seen.setdefault(key, set())
        if row['seq'] in seen:
            b['duplicates'] += 1
            return
        seen.add(row['seq'])
        previous = b['last_seq']
        delta = (row['seq']-previous) & 0xffffffff if previous is not None else 1
        if delta >= 0x80000000:
            b['reordered'] += 1
            if 0 < ((b['first_seq']-row['seq']) & 0xffffffff) < 0x80000000:
                b['first_seq'] = row['seq']
        else:
            b['last_seq'] = row['seq']
        b['sequence_gaps'] = ((b['last_seq']-b['first_seq']) & 0xffffffff)+1-len(seen)
        b['received'] += 1
        self.received += 1
        b['start_observed'] |= bool(row['event'] & 1)
        b['end_observed'] |= bool(row['event'] & 2)

    def summary(self):
        return dict(received_samples=self.received, invalid_notifications=self.invalid,
                    host_queue_drops=self.host_drops, bursts=self.bursts,
                    interpretation="Gaps are counted only within one boot/session/burst. "
                    "An absent boundary is incomplete coverage, not proof of delivery. "
                    "Device accepted counts mean BLE stack acceptance, not laptop receipt. "
                    "Sensor cadence uses device read timestamps, not host arrival timing.")


async def run(args):
    from bleak import BleakClient, BleakScanner
    directory = args.output / datetime.now().strftime("ble_%Y%m%d_%H%M%S_%f")
    directory.mkdir(parents=True)
    started = time.monotonic()
    capture = Capture()
    packets = asyncio.Queue(maxsize=2048)
    stop = asyncio.Event()
    metadata = dict(started_utc=datetime.now(timezone.utc).isoformat(), name=args.name,
                    operator_reported_power_source=args.power_source)
    (directory/'metadata.json').write_text(json.dumps(metadata, indent=2))
    with (directory/'capture.log').open('w', encoding='utf-8') as log, \
         (directory/'samples.csv').open('w', newline='') as samples, \
         (directory/'status.jsonl').open('w') as statuses:
        writer = csv.DictWriter(samples, fieldnames=['host_elapsed_s', *FIELDS])
        writer.writeheader()

        def emit(message):
            line = f"[{time.monotonic()-started:8.2f}s] {message}"
            print(line, flush=True); log.write(line+'\n'); log.flush()

        def notification(_, data):
            try:
                packets.put_nowait((time.monotonic()-started, bytes(data)))
            except asyncio.QueueFull:
                capture.host_drops += 1

        async def consume():
            last_print = 0
            while not stop.is_set() or not packets.empty():
                try:
                    elapsed, data = await asyncio.wait_for(packets.get(), .2)
                except asyncio.TimeoutError:
                    continue
                try:
                    rows = decode_packet(data)
                except ValueError as error:
                    capture.invalid += 1; emit(f"[invalid] {error}"); continue
                for row in rows:
                    capture.ingest(row)
                    writer.writerow(dict(host_elapsed_s=elapsed, **row))
                    if row['event']:
                        emit(f"[move] {'start' if row['event']==1 else 'end'} burst={row['burst']} seq={row['seq']}")
                if elapsed-last_print >= .5:
                    last_print = elapsed
                    r = rows[-1]
                    emit(f"[sample] burst={r['burst']} seq={r['seq']} dt={r['interval_us']} us "
                         f"accel=({r['ax_g']:+.3f},{r['ay_g']:+.3f},{r['az_g']:+.3f}) g "
                         f"gyro=({r['gx_dps']:+.2f},{r['gy_dps']:+.2f},{r['gz_dps']:+.2f}) dps")
                    samples.flush()

        def remaining():
            return args.duration-(time.monotonic()-started) if args.duration else float('inf')

        emit(f"Saving to {directory.resolve()}. Keep the IMU flat and still during boot calibration.")
        consumer = asyncio.create_task(consume())
        try:
            while remaining() > 0:
                emit(f"[ble] scanning for {args.address or args.name}")
                timeout = min(10, remaining())
                if args.address:
                    device = await BleakScanner.find_device_by_address(args.address, timeout=timeout)
                else:
                    device = await BleakScanner.find_device_by_filter(
                        lambda d, a: (a.local_name or d.name) == args.name
                        and SERVICE_UUID in [u.lower() for u in a.service_uuids], timeout=timeout)
                if device is None:
                    continue
                disconnected = asyncio.Event()
                try:
                    async with BleakClient(device, disconnected_callback=lambda _: disconnected.set()) as client:
                        await client.start_notify(NOTIFY_UUID, notification)
                        emit("[ble] subscribed; movement samples will arrive automatically")
                        connected_at = time.monotonic()
                        while remaining() > 0 and not disconnected.is_set():
                            data = await asyncio.wait_for(client.read_gatt_char(STATUS_UUID), timeout=5)
                            status = json.loads(data)
                            statuses.write(json.dumps(dict(host_elapsed_s=time.monotonic()-started, status=status))+'\n')
                            statuses.flush()
                            emit(f"[status] {json.dumps(status, separators=(',', ':'))}")
                            if time.monotonic()-connected_at > 5 and status.get('mtu', 23) < 59:
                                raise RuntimeError("Negotiated BLE MTU is below 59; samples cannot fit. "
                                                   "Use an adapter/OS that negotiates a larger MTU.")
                            try:
                                await asyncio.wait_for(disconnected.wait(), timeout=min(1, max(.001, remaining())))
                            except asyncio.TimeoutError:
                                pass
                        if disconnected.is_set():
                            emit("[ble] disconnected; motion state unknown; rescanning")
                except RuntimeError:
                    raise
                except Exception as error:
                    emit(f"[ble] {type(error).__name__}: {error}; retrying")
                    await asyncio.sleep(min(2, max(0, remaining())))
        finally:
            stop.set()
            await consumer
            result = capture.summary()
            result.update(metadata=metadata, duration_s=time.monotonic()-started)
            (directory/'summary.json').write_text(json.dumps(result, indent=2))
            emit(f"[saved] {capture.received} samples; invalid={capture.invalid}; host_queue_drops={capture.host_drops}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', default='CG4002-Forearm')
    parser.add_argument('--address', help='Select a specific Bluetooth address instead of the name')
    parser.add_argument('--duration', type=float, default=0, help='Seconds; 0 runs until Ctrl+C')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent/'captures')
    parser.add_argument('--power-source', choices=['unknown', 'usb', 'lipo-usb-disconnected'], default='unknown')
    args = parser.parse_args()
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error('--duration must be finite and nonnegative')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except ImportError:
        parser.exit(1, 'Install the receiver dependency: python -m pip install bleak\n')
    except Exception as error:
        parser.exit(1, f'{type(error).__name__}: {error}\n')


if __name__ == '__main__':
    main()
