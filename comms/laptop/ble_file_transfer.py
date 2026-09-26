"""Request a text file from a FireBeetle and verify it with SHA-256."""

import argparse
import asyncio
import hashlib
import json
import struct
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner

import _bootstrap
from utilities.constants import (
    NOTIFY_CHAR_UUID,
    PKT_FILE_CHUNK,
    PKT_FILE_CHUNK_REQ,
    PKT_FILE_META,
    PKT_FILE_REQ,
    PKT_FILE_RESULT,
    SERVICE_UUID,
    WRITE_CHAR_UUID,
)

FILENAME = "/demo.txt"
CHUNK_HEADER = struct.Struct("<BHHB")   # B is 1 byte, H is 2 bytes
CHUNK_SIZE = 160
CHUNKS_PER_BATCH = 16
OUTPUT_DIR = Path(__file__).resolve().parent / "received_files"
MAX_RETRIES = 3
REPLY_TIMEOUT_SECONDS = 2.0
BATCH_FIRST_PACKET_TIMEOUT_SECONDS = 0.75
BATCH_IDLE_TIMEOUT_SECONDS = 0.075


async def write_json(client: BleakClient, packet: dict) -> None:
    data = json.dumps(packet, separators=(",", ":")).encode()
    await client.write_gatt_char(WRITE_CHAR_UUID, data, response=True)


async def wait_for_packet(queue: asyncio.Queue, timeout: float) -> bytes:
    return await asyncio.wait_for(queue.get(), timeout=timeout)


async def request_metadata(
    client: BleakClient,
    queue: asyncio.Queue,
    transfer_id: int,
    filename: str,
) -> dict:
    for _attempt in range(MAX_RETRIES):
        await write_json(
            client,
            {
                "type": PKT_FILE_REQ,
                "transfer_id": transfer_id,
                "filename": filename,
            },
        )
        try:
            data = await wait_for_packet(queue, REPLY_TIMEOUT_SECONDS)
            packet = json.loads(data.decode())
            if (
                packet.get("type") == PKT_FILE_META
                and packet.get("transfer_id") == transfer_id
            ):
                return packet
        except (asyncio.TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    raise RuntimeError("FireBeetle did not return valid file metadata")


def decode_chunk(packet: bytes, transfer_id: int):
    """Return (chunk_index, payload), or None for an unrelated/invalid packet."""
    if len(packet) < CHUNK_HEADER.size:
        return None

    packet_type, packet_transfer_id, chunk_index, data_length = (
        CHUNK_HEADER.unpack_from(packet)
    )
    expected_length = CHUNK_HEADER.size + data_length
    if (
        packet_type != PKT_FILE_CHUNK
        or packet_transfer_id != transfer_id
        or len(packet) != expected_length
    ):
        return None

    return chunk_index, packet[CHUNK_HEADER.size:expected_length]


async def request_chunk_batch(
    client: BleakClient,
    queue: asyncio.Queue,
    transfer_id: int,
    start_index: int,
    count: int,
) -> tuple[list[bytes], int]:
    """Request one burst, then repair only chunks missing from that burst."""
    received: dict[int, bytes] = {}
    end_index = start_index + count

    await write_json(
        client,
        {
            "type": PKT_FILE_CHUNK_REQ,
            "transfer_id": transfer_id,
            "chunk_index": start_index,
            "count": count,
        },
    )
    # GATT notifications are ordered. Once the final index arrives, the burst
    # is complete and any absent indices can be repaired immediately. If the
    # final packet is lost, stop after a short quiet period instead of waiting
    # the full first-packet timeout for every batch.
    while True:
        timeout = (
            BATCH_FIRST_PACKET_TIMEOUT_SECONDS
            if not received
            else BATCH_IDLE_TIMEOUT_SECONDS
        )
        try:
            packet = await wait_for_packet(queue, timeout)
        except asyncio.TimeoutError:
            break

        decoded = decode_chunk(packet, transfer_id)
        if decoded is None:
            continue

        chunk_index, payload = decoded
        if not start_index <= chunk_index < end_index:
            continue

        received[chunk_index] = payload
        if chunk_index == end_index - 1:
            break

    missing = [
        index for index in range(start_index, end_index)
        if index not in received
    ]
    repair_count = len(missing)
    for chunk_index in missing:
        received[chunk_index] = await request_single_chunk(
            client,
            queue,
            transfer_id,
            chunk_index,
        )

    return (
        [received[index] for index in range(start_index, end_index)],
        repair_count,
    )


async def request_single_chunk(
    client: BleakClient,
    queue: asyncio.Queue,
    transfer_id: int,
    chunk_index: int,
) -> bytes:
    """Reliably repair one chunk that was absent from a notification burst."""
    for _attempt in range(MAX_RETRIES):
        await write_json(
            client,
            {
                "type": PKT_FILE_CHUNK_REQ,
                "transfer_id": transfer_id,
                "chunk_index": chunk_index,
                "count": 1,
            },
        )
        deadline = asyncio.get_running_loop().time() + REPLY_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            remaining = deadline - asyncio.get_running_loop().time()
            try:
                packet = await wait_for_packet(queue, remaining)
            except asyncio.TimeoutError:
                break

            decoded = decode_chunk(packet, transfer_id)
            if decoded is None:
                continue

            received_index, payload = decoded
            if received_index == chunk_index:
                return payload

    raise RuntimeError(f"Could not repair missing chunk {chunk_index}")


def show_progress(completed: int, total: int) -> None:
    width = 30
    ratio = completed / total if total else 1.0
    filled = min(width, int(ratio * width))
    bar = "#" * filled + "-" * (width - filled)
    print(f"\rReceiving [{bar}] {completed}/{total} bytes", end="", flush=True)


async def receive_file(
    device_name: str,
    output_dir: Path,
    hash_only: bool = False,
):
    print(f"Scanning for {device_name!r}...")
    seen_names = set()
    service_candidates = {}

    def matches_device(device, advertisement) -> bool:
        advertised_name = advertisement.local_name or device.name or "<unnamed>"
        seen_names.add(advertised_name)
        service_candidates[device.address] = device
        return advertised_name == device_name

    device = await BleakScanner.find_device_by_filter(
        matches_device,
        timeout=15.0,
        service_uuids=[SERVICE_UUID],
    )
    if device is None and len(service_candidates) == 1:
        device = next(iter(service_candidates.values()))
        print(
            "The service UUID was found but its advertised name did not match; "
            "using the only matching FireBeetle."
        )

    if device is None:
        visible = ", ".join(sorted(seen_names)) if seen_names else "none"
        raise RuntimeError(
            f"Could not find {device_name!r}. "
            f"Found {len(service_candidates)} device(s) advertising the service; "
            f"names seen: {visible}"
        )

    print(f"Found {device_name!r} at {device.address}", flush=True)

    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def notification_handler(_sender, data: bytearray) -> None:
        queue.put_nowait(bytes(data))

    transfer_id = int(time.time()) & 0xFFFF
    print("Connecting and discovering services...", flush=True)
    async with BleakClient(device.address, use_services_cache=False) as client:
        print(f"Connected to {device_name}", flush=True)
        print("Enabling encrypted notifications...", flush=True)
        await client.start_notify(NOTIFY_CHAR_UUID, notification_handler)
        print("Notifications enabled; allowing BLE link to settle...", flush=True)
        # Give pairing and the FireBeetle's requested connection-interval update 
        # time to complete before the first high-rate notification burst.
        await asyncio.sleep(0.5)
        print("Requesting file metadata...", flush=True)

        metadata = await request_metadata(
            client,
            queue,
            transfer_id,
            FILENAME,
        )
        file_size = int(metadata["size"])
        total_chunks = int(metadata["total_chunks"])
        expected_sha256 = str(metadata["sha256"])
        filename = Path(str(metadata["filename"])).name
        expected_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        valid_hash = (
            len(expected_sha256) == 64
            and all(character in "0123456789abcdef" for character in expected_sha256)
        )
        if (
            not filename
            or file_size < 0
            or file_size > 10_000_000
            or total_chunks != expected_chunks
            or not valid_hash
        ):
            raise RuntimeError("Invalid file metadata")

        print(f"Original SHA-256: {expected_sha256}")
        if hash_only:
            print("Hash calculated on the FireBeetle; no file was transferred")
            return None

        print(f"Receiving {filename}: {file_size} bytes in {total_chunks} chunks")
        started_at = time.monotonic()
        contents = bytearray()
        repaired_chunks = 0

        for batch_start in range(0, total_chunks, CHUNKS_PER_BATCH):
            batch_count = min(CHUNKS_PER_BATCH, total_chunks - batch_start)
            chunks, batch_repairs = await request_chunk_batch(
                client,
                queue,
                transfer_id,
                batch_start,
                batch_count,
            )
            repaired_chunks += batch_repairs
            for batch_offset, chunk in enumerate(chunks):
                chunk_index = batch_start + batch_offset
                expected_length = min(
                    CHUNK_SIZE,
                    file_size - chunk_index * CHUNK_SIZE,
                )
                if len(chunk) != expected_length:
                    raise RuntimeError(
                        f"Invalid payload length for chunk {chunk_index}: "
                        f"received={len(chunk)}, expected={expected_length}"
                    )
                contents.extend(chunk)
            show_progress(len(contents), file_size)

        print()
        actual_sha256 = hashlib.sha256(contents).hexdigest()
        verified = (
            len(contents) == file_size
            and actual_sha256 == expected_sha256
        )
        await write_json(
            client,
            {
                "type": PKT_FILE_RESULT,
                "transfer_id": transfer_id,
                "status": "OK" if verified else "ERROR",
            },
        )
        if not verified:
            raise RuntimeError(
                f"Verification failed: bytes={len(contents)}/{file_size}, "
                f"SHA-256={actual_sha256}/{expected_sha256}"
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        output_path.write_bytes(contents)
        elapsed = max(time.monotonic() - started_at, 1e-9)

        print(f"Received SHA-256: {actual_sha256}")
        print("Hashes match")
        print(f"Burst repair count: {repaired_chunks}/{total_chunks} chunks")
        print(f"Transfer speed: {len(contents) * 8 / elapsed / 1000:.2f} kbps")
        print(f"Saved file: {output_path.resolve()}")
        return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Receive demo.txt over BLE")
    parser.add_argument("--device", default="file-trf")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--hash-only",
        action="store_true",
        help="display the FireBeetle file hash only",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await receive_file(args.device, args.output_dir, hash_only=args.hash_only)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTransfer cancelled")
    except Exception as exc:
        print(f"\nTransfer failed: {exc}")
        raise SystemExit(1)
