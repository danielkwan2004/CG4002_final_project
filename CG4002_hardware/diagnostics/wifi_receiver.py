"""P1/P2 telemetry capture. Standard library only; firmware protocols v3/v4.

Data samples are CSV, control/diagnostic packets are JSON. Bursts come from the
device, never from host receive gaps. UDP acceptance is not delivery proof.
"""

import argparse
import csv
import json
import math
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


UINT32_MAX = (1 << 32) - 1
FIELD_NAMES = [
    "version", "node_id", "boot_id", "burst_id", "burst_index", "seq",
    "timestamp_us", "interval_us", "ax_raw", "ay_raw", "az_raw",
    "gx_raw", "gy_raw", "gz_raw", "ax_g", "ay_g", "az_g",
    "gx_dps", "gy_dps", "gz_dps", "ax_filtered_g", "ay_filtered_g",
    "az_filtered_g", "gx_filtered_dps", "gy_filtered_dps", "gz_filtered_dps",
    "status_flags",
]
HISTOGRAM_LABELS = ["<4000", "4000-4499", "4500-5499", "5500-5999", "6000-9999", ">=10000"]
STATES = {"BOOT", "CALIBRATING", "STREAMING", "FAULT"}


def integer(value, name, low=0, high=UINT32_MAX):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"invalid {name}: expected integer in [{low}, {high}]")
    return value


def vector(value, name, length=3):
    if not isinstance(value, list) or len(value) != length or any(
        isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
        for x in value
    ):
        raise ValueError(f"invalid {name}")


def parse_packet(payload):
    text = payload.decode("ascii").strip()
    if not text:
        raise ValueError("empty packet")
    if text.startswith("{"):
        p = json.loads(text)
        if not isinstance(p, dict) or p.get("v") not in (3, 4):
            raise ValueError("expected protocol v3 or v4")
        integer(p.get("node"), "node", 1, 255)
        integer(p.get("boot"), "boot")
        kind = p.get("type")
        pending = integer(p.get("pending", 0), "pending")
        if kind == "burst":
            if "interrupted" in p and not isinstance(p["interrupted"], bool):
                raise ValueError("invalid burst interruption flag")
            for key in ("id", "first_seq", "last_seq", "first_us", "last_us", "attempted", "accepted", "failed"):
                integer(p.get(key), key, 1 if key == "id" else 0)
            if (not isinstance(p.get("closed"), bool)
                    or p["accepted"] + p["failed"] + pending != p["attempted"]):
                raise ValueError("inconsistent burst counts")
            if p["v"] == 4 and ("pending" not in p or not isinstance(p.get("gate_closed"), bool)
                    or p["closed"] != (p["gate_closed"] and pending == 0)):
                raise ValueError("invalid burst finalization")
        elif kind == "timing":
            for key in ("imu_read_failures", "imu_consecutive", "imu_max_consecutive",
                        "imu_recovery_attempts", "imu_recoveries", "saturated_samples"):
                if key in p:
                    integer(p[key], key)
            if "max_diag_us" in p:
                integer(p["max_diag_us"], "max_diag_us")
            for key in ("produced", "intervals", "min_dt_us", "max_dt_us", "skipped_deadlines",
                        "max_late_us", "max_read_us", "max_processing_us", "max_wifi_us",
                        "dropped", "high_water", "attempted", "accepted", "failed", "diag_failed",
                        "bursts_started", "active_burst", "idle_samples"):
                integer(p.get(key), key)
            integer(p.get("sum_dt_us"), "sum_dt_us", high=(1 << 64) - 1)
            if not isinstance(p.get("hist"), list) or len(p["hist"]) != 6:
                raise ValueError("invalid interval histogram")
            for n in p["hist"]:
                integer(n, "histogram count")
            vector(p.get("idle_gyro_sum"), "idle_gyro_sum")
            vector(p.get("idle_accel_sum"), "idle_accel_sum")
            if (sum(p["hist"]) != p["intervals"] or p["intervals"] != max(0, p["produced"] - 1)
                    or p["accepted"] + p["failed"] + pending != p["attempted"]
                    or p["idle_samples"] > p["produced"] or p["active_burst"] > p["bursts_started"]
                    or p.get("state") not in STATES):
                raise ValueError("inconsistent timing counters/state")
        elif kind == "config":
            for key in ("produced", "period_us", "calibration_samples"):
                integer(p.get(key), key)
            for key in ("who", "gyro_config", "accel_config", "pwr_mgmt"):
                integer(p.get(key), key, high=255)
            for key in ("gyro_fs_dps", "accel_fs_g", "gyro_lsb_per_dps", "accel_lsb_per_g", "alpha",
                        "gyro_start_dps", "gyro_stop_dps", "accel_start_g", "accel_stop_g", "quiet_ms"):
                vector([p.get(key)], key, 1)
            vector(p.get("gyro_bias_counts"), "gyro_bias_counts")
            vector(p.get("accel_offset_g"), "accel_offset_g")
            if not isinstance(p.get("verified"), bool) or p.get("state") not in STATES:
                raise ValueError("invalid configuration state")
        elif kind == "transport":
            for key in ("produced", "report", "time_ms", "attempted", "accepted", "failed",
                        "data_failed", "control_failed", "last_ms", "last_bytes",
                        "last_rssi_age_ms", "last_heap", "disconnects",
                        "last_disconnect_reason", "last_disconnect_ms", "heap_free", "heap_min"):
                integer(p.get(key), key)
            for key in ("stages", "errors"):
                if not isinstance(p.get(key), list) or len(p[key]) != 4:
                    raise ValueError(f"invalid transport {key}")
                for count in p[key]:
                    integer(count, key)
                if sum(p[key]) != p["failed"]:
                    raise ValueError(f"inconsistent transport {key}")
            for key in ("last_wifi", "wifi_status"):
                integer(p.get(key), key, high=255)
            for key in ("last_rssi", "rssi_dbm"):
                integer(p.get(key), key, -200, 0)
            integer(p.get("last_errno"), "last_errno", high=65535)
            integer(p.get("last_stage"), "last_stage", high=4)
            integer(p.get("last_sent"), "last_sent", -1, 1460)
            if (p.get("backend") not in ("lwip_nonblocking_v1", "lwip_queued_v2") or not isinstance(p.get("last_data"), bool)
                    or p["accepted"] + p["failed"] != p["attempted"]
                    or p["data_failed"] + p["control_failed"] != p["failed"]
                    or bool(p["failed"]) != bool(p["last_stage"])):
                raise ValueError("inconsistent transport counters/backend")
        elif kind == "txqueue" and p["v"] == 4:
            for key in ("produced", "report", "offered", "accepted", "dropped", "pending",
                        "recovered", "overflow", "expired", "permanent", "cancelled",
                        "calls", "errors", "retries", "datagrams", "high_water", "max_age_ms",
                        "oldest_ms", "capacity", "batch_size", "flush_ms", "max_age_limit_ms", "retry_ms"):
                integer(p.get(key), key)
            if (p["offered"] != p["accepted"] + p["dropped"] + pending
                    or p["dropped"] != sum(p[k] for k in ("overflow", "expired", "permanent", "cancelled"))
                    or p["calls"] != p["datagrams"] + p["errors"]
                    or p["recovered"] > p["accepted"] or p["retries"] > p["calls"]
                    or not 0 < p["batch_size"] <= 5 or not 0 < p["capacity"] <= 4096
                    or not pending <= p["high_water"] <= p["capacity"]):
                raise ValueError("inconsistent transmit queue counters")
        else:
            raise ValueError(f"unknown diagnostic type {kind!r}")
        return p

    values = next(csv.reader([text]))
    if values[0] not in ("3", "4"):
        raise ValueError("old/unknown firmware: flash the current P1/P2 sketch")
    if len(values) != len(FIELD_NAMES):
        raise ValueError(f"expected {len(FIELD_NAMES)} sample fields, got {len(values)}")
    p = dict(zip(FIELD_NAMES, values))
    for key in FIELD_NAMES[:14] + ["status_flags"]:
        p[key] = int(p[key])
        if key.endswith("_raw"):
            integer(p[key], key, -32768, 32767)
        else:
            integer(p[key], key, high=255 if key in ("node_id", "status_flags") else UINT32_MAX)
    if p["node_id"] == 0 or p["burst_id"] == 0:
        raise ValueError("sample has no node/burst identity")
    for key in FIELD_NAMES[14:-1]:
        p[key] = float(p[key])
        if not math.isfinite(p[key]):
            raise ValueError(f"nonfinite {key}")
    p.update(type="sample", node=p["node_id"], boot=p["boot_id"])
    return p


def parse_datagram(payload):
    """Validate the ENTIRE batch before ingesting any samples. v3 stays readable."""
    lines = payload.strip().splitlines()
    if not lines or len(lines) > 5:
        raise ValueError("expected one diagnostic or up to five sample rows")
    packets = [parse_packet(line) for line in lines]
    if len(packets) > 1:
        first = packets[0]
        for i, p in enumerate(packets):
            if (p["type"] != "sample" or p.get("version") != 4
                    or any(p[k] != first[k] for k in ("node", "boot", "burst_id"))
                    or p["burst_index"] != first["burst_index"] + i):
                raise ValueError("invalid/mixed v4 sample batch")
    return packets


def missing_ranges(indices, expected, limit=20):
    """Compact absent index ranges without allocating range(expected)."""
    ranges = []
    previous = -1
    total_ranges = 0
    for index in sorted(i for i in indices if i < expected) + [expected]:
        if index > previous + 1:
            total_ranges += 1
            if len(ranges) < limit:
                ranges.append([previous + 1, index - 1])
        previous = index
    return {"ranges": ranges, "range_count": total_ranges, "truncated": total_ranges > limit}


@dataclass
class Burst:
    # Unique per-burst send-attempt indexes, not differences in acquisition seq.
    samples: dict = field(default_factory=dict)
    duplicates: int = 0
    reordered: int = 0
    conflicts: int = 0
    max_index: int = -1
    sender: dict | None = None

    def add_sample(self, p):
        index = p["burst_index"]
        fingerprint = tuple(p[key] for key in FIELD_NAMES)
        if index in self.samples:
            self.duplicates += 1
            if self.samples[index] != fingerprint:
                self.conflicts += 1
            return
        if index < self.max_index:
            self.reordered += 1
        self.max_index = max(self.max_index, index)
        self.samples[index] = fingerprint

    def add_summary(self, p):
        if self.sender is not None:
            if self.sender["closed"]:
                if p["closed"] and p != self.sender:
                    self.conflicts += 1
                return
            if (p["attempted"], p["accepted"] + p["failed"], p.get("gate_closed", p["closed"])) < (
                    self.sender["attempted"], self.sender["accepted"] + self.sender["failed"],
                    self.sender.get("gate_closed", self.sender["closed"])):
                return  # delayed earlier progress snapshot
        self.sender = p

    def summary(self):
        result = dict(received_unique=len(self.samples), duplicates=self.duplicates,
                      reordered=self.reordered, conflicting_packets=self.conflicts,
                      complete_sender_summary=bool(self.sender and self.sender["closed"]))
        result["pending_samples"] = self.sender.get("pending", 0) if self.sender else None
        result["gate_closed"] = self.sender.get("gate_closed", self.sender["closed"]) if self.sender else None
        result["interrupted"] = self.sender.get("interrupted", False) if self.sender else None
        if not result["complete_sender_summary"]:
            result.update(accepted_not_received=None, explanation="No final sender counts yet; delivery is incomplete evidence.")
            return result
        expected = self.sender["attempted"]
        received_in_range = sum(i < expected for i in self.samples)
        unreceived = self.sender["accepted"] - received_in_range
        consistent = unreceived >= 0 and received_in_range == len(self.samples) and self.conflicts == 0
        result.update(sender_attempted=expected, sender_accepted=self.sender["accepted"],
                      local_send_failures=self.sender["failed"], counts_consistent=consistent,
                      accepted_not_received=unreceived if consistent else None,
                      unreceived_attempt_indexes=missing_ranges(self.samples, expected),
                      first_seq=self.sender["first_seq"], last_seq=self.sender["last_seq"],
                      first_us=self.sender["first_us"], last_us=self.sender["last_us"])
        result["explanation"] = (
            "Accepted by the device UDP API but not captured here; may include receiver downtime. "
            "Absent attempt indexes include local send failures. Late UDP packets may revise this count."
            if consistent else "Conflicting/out-of-range data or received > accepted; do not infer loss.")
        return result


def timing_summary(t):
    if not t:
        return None
    n = t["intervals"]
    total = t["sum_dt_us"]
    idle = t["idle_samples"]
    return dict(
        produced=t["produced"], interval_count=n,
        acquisition_span_s=total / 1e6,
        achieved_hz=n * 1e6 / total if total else None,
        mean_interval_us=total / n if n else None,
        min_interval_us=t["min_dt_us"] if n else None,
        max_interval_us=t["max_dt_us"] if n else None,
        interval_histogram_us=dict(zip(HISTOGRAM_LABELS, t["hist"])),
        within_4500_5499_percent=100 * t["hist"][2] / n if n else None,
        skipped_deadlines=t["skipped_deadlines"], max_lateness_us=t["max_late_us"],
        max_read_us=t["max_read_us"], max_processing_us=t["max_processing_us"],
        max_wifi_send_us=t["max_wifi_us"], buffer_drops=t["dropped"],
        max_diagnostic_service_us=t.get("max_diag_us"),
        buffer_high_water=t["high_water"], diagnostic_send_failures=t["diag_failed"],
        idle_samples=idle,
        gate_idle_mean_corrected_gyro_dps=[x / idle for x in t["idle_gyro_sum"]] if idle else None,
        gate_idle_mean_calibrated_accel_g=[x / idle for x in t["idle_accel_sum"]] if idle else None,
        scope="All completed device acquisitions since boot, through the latest received timing report; includes idle.",
    )


def configuration_verified(c):
    return bool(c and c["verified"] and c["who"] == 0x44 and
                c["gyro_config"] == 0x27 and c["accel_config"] == 0x27 and
                c["pwr_mgmt"] & 15 == 15 and c["gyro_lsb_per_dps"] == 16.4 and
                c["accel_lsb_per_g"] == 2048 and c["gyro_fs_dps"] == 2000 and
                c["accel_fs_g"] == 16 and c["period_us"] == 5000)


@dataclass
class Session:
    node: int
    boot: int
    bursts: dict = field(default_factory=dict)
    protocol_versions: set = field(default_factory=set)
    config: dict | None = None
    timing: dict | None = None
    transport: dict | None = None
    txqueue: dict | None = None
    capture_start_seq: int | None = None
    prior_bursts: int | None = None
    first_timing: dict | None = None
    first_transport: dict | None = None
    first_txqueue: dict | None = None
    observed_startup: bool = False
    last_receive_s: float = 0.0
    latest_state: str = "UNKNOWN"
    state_produced: int = -1

    def ingest(self, p, now):
        self.last_receive_s = now
        kind = p["type"]
        self.protocol_versions.add(p["version"] if kind == "sample" else p["v"])
        # Replayed burst summaries are historical evidence, not a capture start.
        # Freeze the boundary at the first acquisition-bearing packet. Later
        # delayed packets must not widen the window and invent historical loss.
        if self.capture_start_seq is None and kind != "burst":
            self.capture_start_seq = p["seq"] if kind == "sample" else p["produced"]
            if self.capture_start_seq == 0:
                self.prior_bursts = 0
            elif kind == "timing":
                self.prior_bursts = p["bursts_started"]
            elif kind == "sample":
                self.prior_bursts = p["burst_id"] - (p["burst_index"] == 0)
        ranks = {"UNKNOWN": -1, "BOOT": 0, "CALIBRATING": 1, "STREAMING": 2, "FAULT": 3}
        if kind in ("config", "timing") and (p["produced"], ranks[p["state"]]) >= (
                self.state_produced, ranks[self.latest_state]):
            self.state_produced = p["produced"]
            self.latest_state = p["state"]
        if kind == "sample":
            self.bursts.setdefault(p["burst_id"], Burst()).add_sample(p)
        elif kind == "burst":
            self.bursts.setdefault(p["id"], Burst()).add_summary(p)
        elif kind == "config":
            self.observed_startup |= p["produced"] == 0
            if self.config is None or (p["produced"], ranks[p["state"]]) >= (
                    self.config["produced"], ranks[self.config["state"]]):
                self.config = p
        elif kind == "timing":
            if self.first_timing is None:
                self.first_timing = p
                if self.prior_bursts is None and p["produced"] == self.capture_start_seq:
                    self.prior_bursts = p["bursts_started"]
            if self.timing is None or p["produced"] >= self.timing["produced"]:
                self.timing = p
        elif kind == "transport":
            if self.first_transport is None:
                self.first_transport = p
            if self.transport is None or p["report"] > self.transport["report"]:
                self.transport = p
        elif kind == "txqueue":
            if self.first_txqueue is None:
                self.first_txqueue = p
            if self.txqueue is None or p["report"] > self.txqueue["report"]:
                self.txqueue = p

    def capture_delivery(self, bursts):
        groups = {k: [] for k in ("current", "historical", "partial", "unscoped")}
        for i, b in self.bursts.items():
            p = b.sender
            if self.capture_start_seq is None or not p:
                group = "unscoped"
            elif p["first_seq"] >= self.capture_start_seq:
                group = "current"
            elif p["last_seq"] < self.capture_start_seq:
                group = "historical"
            else:
                group = "partial"
            groups[group].append(str(i))
        eligible = [i for i in groups["current"] if bursts[i]["complete_sender_summary"]
                    and bursts[i].get("counts_consistent")]
        totals = {k: sum(bursts[i][k] for i in eligible) for k in (
            "sender_attempted", "sender_accepted", "local_send_failures", "received_unique", "accepted_not_received")}
        totals["not_captured"] = totals["sender_attempted"] - totals["received_unique"]
        totals["received_percent_of_attempted"] = (100 * totals["received_unique"] / totals["sender_attempted"]
                                                   if totals["sender_attempted"] else None)
        totals.update(start_seq=self.capture_start_seq, finalized_burst_ids=eligible,
                      historical_burst_ids=groups["historical"], partial_burst_ids=groups["partial"],
                      pending_burst_ids=[i for i in groups["current"] if i not in eligible] + groups["unscoped"],
                      scope="Final consistent bursts starting at/after the first observed acquisition boundary; historical and partial bursts excluded.")
        if self.prior_bursts is not None and self.timing:
            started = max(0, self.timing["bursts_started"] - self.prior_bursts)
            known = sum(self.prior_bursts < i <= self.timing["bursts_started"] for i in self.bursts)
            totals.update(bursts_started=started, unseen_burst_count=max(0, started-known))
        else:
            totals.update(bursts_started=None, unseen_burst_count=None)
        return totals

    def counter_delta(self, latest, first, keys):
        if latest is None or first is None:
            return None
        # A capture begun at startup has a known zero baseline. Otherwise the
        # first report establishes a baseline, not newly incurred errors.
        zero = self.capture_start_seq == 0
        return {k: max(0, latest[k] - (0 if zero else first[k])) for k in keys}

    def summary(self):
        bursts = {str(i): b.summary() for i, b in sorted(self.bursts.items())}
        declared = max(max(self.bursts, default=0), self.timing["bursts_started"] if self.timing else 0)
        unseen = declared - len(self.bursts)
        unseen_ids = missing_ranges({i - 1 for i in self.bursts}, declared)
        unseen_ids["ranges"] = [[first + 1, last + 1] for first, last in unseen_ids["ranges"]]
        closed = [b for b in bursts.values() if b["complete_sender_summary"] and b.get("counts_consistent")]
        totals = {k: sum(b[k] for b in closed) for k in
                  ("sender_attempted", "sender_accepted", "local_send_failures", "received_unique", "accepted_not_received")}
        totals["scope"] = "Only bursts with final, consistent sender summaries. Counts can include a partial receiver capture."
        totals["not_captured"] = totals["sender_attempted"] - totals["received_unique"]
        totals["received_percent_of_attempted"] = (
            100 * totals["received_unique"] / totals["sender_attempted"] if totals["sender_attempted"] else None)
        return dict(node=self.node, boot=self.boot, state=self.latest_state,
                    protocol_versions=sorted(self.protocol_versions),
                    observed_startup=self.observed_startup, configuration=self.config,
                    range_readback_verified=configuration_verified(self.config),
                    timing=timing_summary(self.timing), latest_device_counters=self.timing,
                    transport=self.transport, txqueue=self.txqueue,
                    capture_delivery=self.capture_delivery(bursts),
                    capture_counter_changes=self.counter_delta(self.timing, self.first_timing,
                        ("produced", "skipped_deadlines", "dropped", "failed", "diag_failed")),
                    capture_transport_changes=self.counter_delta(self.transport, self.first_transport,
                        ("attempted", "accepted", "failed", "data_failed", "control_failed", "disconnects")),
                    capture_queue_changes=self.counter_delta(self.txqueue, self.first_txqueue,
                        ("offered", "accepted", "dropped", "recovered", "overflow", "expired", "permanent",
                         "cancelled", "calls", "errors", "retries", "datagrams")),
                    bursts=bursts, finalized_burst_totals=totals,
                    unseen_burst_count=unseen,
                    unseen_burst_ids=unseen_ids,
                    bursts_without_final_summary=[i for i, b in bursts.items() if not b["complete_sender_summary"]])


class Capture:
    def __init__(self):
        self.sessions = {}
        self.invalid_packets = 0

    def ingest(self, p, now):
        key = (p["node"], p["boot"])
        session = self.sessions.setdefault(key, Session(*key))
        session.ingest(p, now)
        return session

    def summary(self):
        versions = sorted({v for s in self.sessions.values() for v in s.protocol_versions})
        return dict(protocol=max(versions, default=4), protocol_versions=versions,
                    invalid_packets=self.invalid_packets,
                    sessions=[s.summary() for s in self.sessions.values()],
                    interpretation=[
                        "Device and laptop clocks are not synchronized; no one-way latency is calculated.",
                        "Timing is completed register-read cadence, not proof that every sensor ODR update is unique/captured.",
                        "A missing final burst summary is incomplete evidence, not zero loss.",
                        "A timeout indicates silence/staleness, not a movement boundary.",
                        "Configuration readback aligns conversion with the selected range; it is not reference-rate calibration.",
                        "Gate-idle averages require the operator to confirm the sensor was stationary.",
                    ])


def describe_timing(session):
    t = timing_summary(session.timing)
    prefix = f"Node {session.node} boot={session.boot:08x}"
    if t is None or t["achieved_hz"] is None:
        return f"[timing] {prefix} state={session.latest_state}; awaiting acquisition intervals"
    return (f"[timing] {prefix} state={session.latest_state} acquired={t['produced']} "
            f"rate={t['achieved_hz']:.2f} Hz dt[min/mean/max]="
            f"{t['min_interval_us']}/{t['mean_interval_us']:.1f}/{t['max_interval_us']} us "
            f"within4.5-5.5ms={t['within_4500_5499_percent']:.2f}% "
            f"skipped_slots={t['skipped_deadlines']} buffer_drops={t['buffer_drops']}"
            + (f" max_diagnostic_us={t['max_diagnostic_service_us']}"
               if t['max_diagnostic_service_us'] is not None else "")
            + (f" imu_read_failures={session.timing['imu_read_failures']}"
               f" imu_recoveries={session.timing.get('imu_recoveries', 0)}"
               f" saturated={session.timing.get('saturated_samples', 0)}"
               if 'imu_read_failures' in session.timing else ""))


def describe_burst(session, burst_id):
    b = session.bursts[burst_id].summary()
    prefix = f"[burst] Node {session.node} boot={session.boot:08x} burst={burst_id}"
    if not b["complete_sender_summary"]:
        return f"{prefix} received={b['received_unique']} awaiting final sender summary"
    return (f"{prefix} attempted={b['sender_attempted']} accepted={b['sender_accepted']} "
            f"local_fail={b['local_send_failures']} received_unique={b['received_unique']} "
            f"accepted_not_received={b['accepted_not_received']} duplicates={b['duplicates']} "
            f"reordered={b['reordered']}"
            + (" interrupted_by_imu_outage=True" if b['interrupted'] else ""))


def describe_transport(session):
    t = session.transport
    if not t:
        return f"[transport] Node {session.node}: diagnostics unavailable with older firmware"
    stages = ("none", "format", "not-ready", "sendto", "short-send")
    return (f"[transport] Node {session.node} report={t['report']} wifi_status={t['wifi_status']} "
            f"rssi={t['rssi_dbm']} dBm (0=unavailable) disconnects={t['disconnects']} "
            f"reason={t['last_disconnect_reason']} heap={t['heap_free']} "
            f"failed[data/control]={t['data_failed']}/{t['control_failed']} "
            f"errors[ENOMEM/busy/network/other]={t['errors']} "
            f"last={stages[t['last_stage']]} errno={t['last_errno']} "
            f"at_uptime_ms={t['last_ms']} last_wifi={t['last_wifi']} "
            f"cached_failure_rssi={t['last_rssi']} age_ms={t['last_rssi_age_ms']}")


def describe_queue(session):
    q = session.txqueue
    if not q:
        return "[txqueue] unavailable (v3 firmware has no retry queue)"
    return (f"[txqueue] offered={q['offered']} accepted={q['accepted']} pending={q['pending']} "
            f"FINAL_DROPS={q['dropped']} recovered_samples={q['recovered']} "
            f"retry_calls={q['retries']} high_water={q['high_water']}/{q['capacity']} "
            f"oldest_ms={q['oldest_ms']} max_age_ms={q['max_age_ms']} "
            f"drop_causes[overflow/expiry/permanent/cancel]={q['overflow']}/{q['expired']}/{q['permanent']}/{q['cancelled']}")


def describe_capture_scope(session):
    d = session.summary()["capture_delivery"]
    return (f"[this-capture] offered={d['sender_attempted']} accepted={d['sender_accepted']} "
            f"received={d['received_unique']} final_local_drops={d['local_send_failures']} "
            f"accepted_not_received={d['accepted_not_received']} "
            f"excluded_historical_bursts={d['historical_burst_ids']} partial_bursts={d['partial_burst_ids']} "
            f"pending_bursts={d['pending_burst_ids']}; {d['scope']}")


def main(argv=None, *, observer=None, quiet=False):
    """Capture evidence; optional UI observer never replaces the capture files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4210)
    parser.add_argument("--sender-ip")
    parser.add_argument("--refresh-interval", type=float, default=0.5)
    parser.add_argument("--duration", type=float, help="optional capture duration in seconds")
    parser.add_argument("--output", type=Path, help="new capture directory (must not already exist)")
    parser.add_argument("--power-source", choices=["unknown", "lipo-usb-disconnected", "usb"], default="unknown")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)
    if args.refresh_interval <= 0 or (args.duration is not None and args.duration <= 0):
        parser.error("duration and refresh interval must be positive")

    directory = args.output or Path("captures") / datetime.now().strftime("p1_p2_%Y%m%d_%H%M%S_%f")
    directory.mkdir(parents=True, exist_ok=False)
    capture = Capture()
    start = time.monotonic()
    last_display = {}
    shown_configs = {}
    shown_closed = set()
    next_report = start + 5
    next_flush = start + 1
    metadata = dict(started_utc=datetime.now(timezone.utc).isoformat(),
                    operator_reported_power_source=args.power_source, notes=args.notes)
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    with (directory / "samples.csv").open("w", newline="", encoding="utf-8") as samples, \
         (directory / "diagnostics.jsonl").open("w", encoding="utf-8") as diagnostics, \
         (directory / "capture.log").open("w", encoding="utf-8") as log, \
         socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        # Deliberately do not enable SO_REUSEADDR: a second monitor should fail
        # visibly rather than divide/intercept the packets in a loss experiment.
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        receiver.bind((args.bind, args.port))
        receiver.settimeout(0.1)
        writer = csv.DictWriter(samples, fieldnames=["host_elapsed_s", "sender_ip"] + FIELD_NAMES)
        writer.writeheader()

        def emit(message):
            line = f"[{time.monotonic() - start:8.2f}s] {message}"
            if not quiet:
                print(line, flush=True)
            log.write(line + "\n")

        if observer is not None:
            observer.on_start(metadata, directory.resolve(), start)
        emit(f"Listening on {args.bind}:{args.port}; firmware v3/v4 supported (v4 batches + retry queue)")
        emit(f"Capture directory: {directory.resolve()}")
        emit(f"Operator-reported power: {args.power_source}. Start/reset the node now and keep it flat and still.")
        try:
            while args.duration is None or time.monotonic() - start < args.duration:
                try:
                    payload, address = receiver.recvfrom(4096)
                except socket.timeout:
                    payload = None
                now = time.monotonic()
                if payload is not None and (not args.sender_ip or address[0] == args.sender_ip):
                    try:
                        packets = parse_datagram(payload)
                    except (ValueError, UnicodeDecodeError, csv.Error, OverflowError) as error:
                        capture.invalid_packets += 1
                        if observer is not None:
                            observer.on_invalid(error, now)
                        diagnostics.write(json.dumps(dict(host_elapsed_s=now - start,
                            sender_ip=address[0], invalid=str(error), payload=payload.decode("ascii", errors="replace"))) + "\n")
                        if capture.invalid_packets <= 10:
                            emit(f"[invalid] {error}")
                    else:
                        for p in packets:
                            session = capture.ingest(p, now)
                            if observer is not None:
                                observer.on_packet(p, now)
                            key = (p["node"], p["boot"])
                            if p["type"] == "sample":
                                writer.writerow(dict(host_elapsed_s=f"{now - start:.6f}", sender_ip=address[0],
                                                     **{k: p[k] for k in FIELD_NAMES}))
                                if now - last_display.get(key, 0) >= args.refresh_interval:
                                    last_display[key] = now
                                    emit(f"[sample] Node {p['node']} burst={p['burst_id']} seq={p['seq']} "
                                         f"t_us={p['timestamp_us']} dt_us={p['interval_us']} "
                                         f"accel=({p['ax_filtered_g']:+.3f},{p['ay_filtered_g']:+.3f},{p['az_filtered_g']:+.3f}) g "
                                         f"gyro=({p['gx_filtered_dps']:+.2f},{p['gy_filtered_dps']:+.2f},{p['gz_filtered_dps']:+.2f}) dps")
                            else:
                                diagnostics.write(json.dumps(dict(host_elapsed_s=now - start, sender_ip=address[0], packet=p)) + "\n")
                                if p["type"] == "config":
                                    signature = (p["state"], p["verified"], p["gyro_config"], tuple(p["gyro_bias_counts"]))
                                    if shown_configs.get(key) != signature:
                                        shown_configs[key] = signature
                                        emit(f"[config] Node {p['node']} boot={p['boot']:08x} state={p['state']} "
                                             f"WHO=0x{p['who']:02X} GYRO_CONFIG0=0x{p['gyro_config']:02X} "
                                             f"ACCEL_CONFIG0=0x{p['accel_config']:02X} "
                                             f"range_readback_verified={configuration_verified(p)}"
                                             + (f" diag_scheduler={p['diag_scheduler']}"
                                                if "diag_scheduler" in p else ""))
                                        if p["state"] == "STREAMING":
                                            emit(f"[calibration] gyro_bias_counts={p['gyro_bias_counts']} accel_offset_g={p['accel_offset_g']}")
                                elif p["type"] == "burst" and p["closed"] and (*key, p["id"]) not in shown_closed:
                                    shown_closed.add((*key, p["id"]))
                                    emit(describe_burst(session, p["id"]) + " (boot evidence; may predate this capture)")
                if observer is not None:
                    observer.on_tick(now)
                if now >= next_report:
                    for session in capture.sessions.values():
                        emit(describe_timing(session))
                        if session.transport:
                            emit(describe_transport(session))
                        if session.txqueue:
                            emit(describe_queue(session))
                        emit(describe_capture_scope(session))
                        if now - session.last_receive_s > 3:
                            emit(f"[stale] Node {session.node} boot={session.boot:08x}: "
                                 f"no packets for {now - session.last_receive_s:.1f}s; not a burst boundary")
                    next_report = now + 5
                if now >= next_flush:
                    samples.flush()
                    diagnostics.flush()
                    log.flush()
                    next_flush = now + 1
        except KeyboardInterrupt:
            emit("Capture stopped by user.")
        finally:
            summary = capture.summary()
            summary.update(metadata=metadata, duration_s=time.monotonic() - start)
            (directory / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
            emit("FINAL CAPTURE SUMMARY")
            if not capture.sessions:
                emit("No valid v3/v4 packets captured. Check flashed firmware, hotspot, destination IP and firewall.")
            for session in capture.sessions.values():
                emit(describe_timing(session))
                emit(describe_transport(session))
                emit(describe_queue(session))
                emit(describe_capture_scope(session))
                for burst_id in sorted(session.bursts):
                    emit(describe_burst(session, burst_id))
                result = session.summary()
                emit(f"[coverage] startup_observed={session.observed_startup} "
                     f"range_readback_verified={result['range_readback_verified']} "
                     f"unseen_bursts={result['unseen_burst_count']} "
                     f"bursts_without_final_summary={result['bursts_without_final_summary']}")
                if result["timing"]:
                    emit(f"[gate-idle] mean_corrected_gyro_dps={result['timing']['gate_idle_mean_corrected_gyro_dps']}")
            emit(f"Saved samples.csv, diagnostics.jsonl, summary.json, metadata.json and capture.log in {directory.resolve()}")
            if observer is not None:
                observer.on_finish(summary, time.monotonic())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
