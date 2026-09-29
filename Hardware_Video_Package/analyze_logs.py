#!/usr/bin/env python3
"""Reproduce presentation plots from the supplied, partial output.txt capture.

Usage: python analyze_logs.py /path/to/output.txt [--out-dir /path/to/output]
No interpolation, invented timestamps, or inferred action labels are used.
Serial accel columns are [raw counts, calibrated g, filtered g]; gyro columns
are [raw counts, corrected counts, filtered counts, filtered dps]. Corrected
gyro counts are divided by the firmware's 16.4 counts/(degree/second).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def parse(path):
    serial, stats, receiver, events = [], [], [], []
    lines = path.read_text().splitlines()
    for line_no, line in enumerate(lines, 1):
        if re.match(r"^\d+ \|", line):
            fields = [f.strip() for f in line.split("|")]
            assert len(fields) == 8, (line_no, fields)
            axes = [[float(v) for v in f.split(",")] for f in fields[1:7]]
            assert [len(v) for v in axes] == [3, 3, 3, 4, 4, 4]
            serial.append(dict(
                seq=int(fields[0]), line=line_no,
                accel_raw=[v[0] for v in axes[:3]],
                accel_cal=[v[1] for v in axes[:3]],
                accel_filtered=[v[2] for v in axes[:3]],
                gyro_raw=[v[0] for v in axes[3:]],
                gyro_corrected=[v[1]/16.4 for v in axes[3:]],
                gyro_filtered=[v[3] for v in axes[3:]],
                status=int(fields[7].split("=")[1]),
                chars=len(line)+2,  # CRLF on serial output
            ))
        elif line.startswith("[stats]"):
            item = {k: int(v) if v.isdigit() else v
                    for k, v in re.findall(r"(\w+)=(\S+)", line)}
            item["line"] = line_no
            stats.append(item)
        elif line.startswith("[move]"):
            match = re.fullmatch(r"\[move\] (start|end) seq=(\d+)", line)
            assert match, (line_no, line)
            events.append(dict(event=match[1], seq=int(match[2]), line=line_no))
        elif line.startswith("node="):
            match = re.fullmatch(
                r"node=(\d+) seq=(\d+) accel=\(([^)]+)\)g gyro=\(([^)]+)\)dps "
                r"status=(\d+) from=(\S+)(?: GAP\(expected=(\d+)\))?", line)
            assert match, (line_no, line)
            receiver.append(dict(node=int(match[1]), seq=int(match[2]),
                accel_filtered=[float(v) for v in match[3].split(",")],
                gyro_filtered=[float(v) for v in match[4].split(",")],
                status=int(match[5]), gap_expected=int(match[7]) if match[7] else None,
                line=line_no))
    return serial, stats, receiver, events, lines


def norm(v):
    return float(np.linalg.norm(v))


def contiguous_segments(rows):
    segments = []
    for row in rows:
        if not segments or row["seq"] != segments[-1][-1]["seq"] + 1:
            segments.append([])
        segments[-1].append(row)
    return segments


def style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
        "axes.titlesize": 15, "axes.labelsize": 12, "figure.facecolor": "#f7f9fc",
        "axes.facecolor": "#ffffff", "axes.spines.top": False,
        "axes.spines.right": False, "axes.edgecolor": "#aeb7c5",
        "axes.labelcolor": "#23334b", "text.color": "#182b46",
        "xtick.color": "#43546d", "ytick.color": "#43546d",
        "grid.color": "#dae1ea", "grid.alpha": 0.75,
        "legend.frameon": False, "savefig.facecolor": "#f7f9fc"})


def finish(fig, out, footnote):
    fig.text(.07, .025, footnote, fontsize=10.5, color="#526279", va="bottom")
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_filter(rows, out):
    selected = [r for r in rows if 5084 <= r["seq"] <= 5187]
    assert len(selected) == 104 and len(contiguous_segments(selected)) == 1
    seq = [r["seq"] for r in selected]
    fig, axes = plt.subplots(2, 1, figsize=(12.8, 7.2), sharex=True)
    fig.subplots_adjust(top=.86, bottom=.17, left=.09, right=.97, hspace=.25)
    fig.suptitle("Measured filtering during a recorded movement burst", x=.07, ha="left", fontsize=20, fontweight="bold")
    fig.text(.07, .9, "Actual Serial values  •  sequence 5084–5187  •  exponential filter α = 0.2", color="#526279")
    for ax, before, after, col, label in [
        (axes[0], "accel_cal", "accel_filtered", 1, "Y acceleration (g)"),
        (axes[1], "gyro_corrected", "gyro_filtered", 2, "Z angular rate (reported °/s)")]:
        ax.plot(seq, [r[before][col] for r in selected], color="#a5b0c2", lw=1.4,
                label="Calibrated / bias-corrected input")
        ax.plot(seq, [r[after][col] for r in selected], color="#067c86", lw=2.4,
                label="Filtered output")
        ax.set_ylabel(label)
        ax.grid(axis="y")
        ax.set_xlim(5084, 5187)
    axes[0].legend(loc="upper left", ncol=2, fontsize=10)
    axes[1].set_xlabel("Acquisition sequence number (not elapsed time)")
    finish(fig, out, "Source: output.txt, Serial movement-only excerpt. Peaks are attenuated and delayed; noise-only reduction is not quantified.\nTime / action markers are absent. Gyro units use the firmware conversion; absolute scale needs independent verification.")


def plot_transient(rows, out):
    selected = [r for r in rows if 7097 <= r["seq"] <= 7124]
    assert len(selected) == 28 and len(contiguous_segments(selected)) == 1
    seq = [r["seq"] for r in selected]
    fig, axes = plt.subplots(2, 1, figsize=(12.8, 7.4), sharex=True)
    fig.subplots_adjust(top=.86, bottom=.18, left=.09, right=.97, hspace=.31)
    fig.suptitle("Recorded transient, settling, and end-of-move boundary", x=.07, ha="left", fontsize=20, fontweight="bold")
    fig.text(.07, .9, "Actual Serial values  •  sequence 7097–7124  •  action timestamps were not annotated", color="#526279")
    axes[0].plot(seq, [r["accel_cal"][2] for r in selected], "o-", ms=3,
                 color="#a5b0c2", lw=1.6, label="Calibrated Z acceleration")
    axes[0].plot(seq, [r["accel_filtered"][2] for r in selected], "o-", ms=3,
                 color="#067c86", lw=2.4, label="Filtered Z acceleration")
    axes[0].axhline(1, color="#68778b", ls="--", lw=1, label="1 g reference")
    axes[0].annotate("8.2128 g input\n1.8289 g filtered at the same sample", xy=(7103, 8.2128),
                     xytext=(7107, 6.2), fontsize=11, arrowprops=dict(arrowstyle="->", color="#526279"))
    axes[0].set_ylabel("Z acceleration (g)")
    axes[0].legend(loc="upper right", fontsize=9)
    axes[1].plot(seq, [norm(r["gyro_filtered"]) for r in selected], "o-", ms=3,
                 color="#067c86", lw=2.4, label="Filtered gyro magnitude")
    axes[1].axhline(40, color="#c47420", ls="--", lw=1, label="Start threshold: 40°/s")
    axes[1].axhline(15, color="#68778b", ls=":", lw=1.3, label="Stop threshold: 15°/s")
    axes[1].set_ylabel("Gyro magnitude (reported °/s)")
    axes[1].legend(loc="upper right", fontsize=9)
    axes[1].set_ylim(bottom=0)
    axes[1].annotate("[move] end at 7124", xy=(7124, norm(selected[-1]["gyro_filtered"])),
                     xytext=(7115, 31), fontsize=11, arrowprops=dict(arrowstyle="->", color="#526279"))
    for ax in axes:
        ax.grid(axis="y")
        ax.set_xlim(7097, 7124.6)
    axes[1].set_xlabel("Acquisition sequence number (not elapsed time)")
    finish(fig, out, "Source: output.txt. Start uses gyro OR acceleration deviation; stop requires BOTH below threshold for 150 ms.\nGyro scale is firmware-reported. The transient is consistent with impact / settling; table-contact timing was not annotated.")


def plot_timing(stats, out):
    report = np.arange(1, len(stats)+1)
    jitter = [abs(r["maxProducerJitterUs"])/1000 for r in stats]
    wifi = [r["maxWifiSendUs"]/1000 for r in stats]
    processing = [r["maxProcessingUs"]/1000 for r in stats]
    fig, axes = plt.subplots(2, 1, figsize=(12.8, 7.2), sharex=True)
    fig.subplots_adjust(top=.86, bottom=.18, left=.09, right=.97, hspace=.3)
    fig.suptitle("Timing evidence: the 200 Hz target still needs validation", x=.07, ha="left", fontsize=20, fontweight="bold")
    fig.text(.07, .9, f"{len(stats)} diagnostic reports in the supplied capture  •  counters cover different scopes", color="#526279")
    axes[0].bar(report, jitter, color="#bd6c30", width=.72, label="Maximum producer-cadence deviation")
    axes[0].axhline(5, color="#526279", ls="--", lw=1.2, label="5 ms nominal sample period (scale reference)")
    axes[0].set_ylabel("Jitter magnitude (ms)")
    axes[0].legend(loc="upper right", fontsize=9)
    maximum = int(np.argmax(jitter))
    axes[0].annotate(f"Largest logged deviation: {jitter[maximum]:.3f} ms", xy=(report[maximum], jitter[maximum]),
                     xytext=(2, 27), fontsize=11,
                     arrowprops=dict(arrowstyle="->", color="#526279"))
    axes[0].set_ylim(0, 31)
    axes[1].plot(report, processing, "o-", color="#067c86", lw=2,
                 label="Maximum measured processing")
    axes[1].plot(report, wifi, "s-", color="#657493", lw=1.7,
                 label="Maximum WiFi send-call duration")
    axes[1].set_ylabel("Duration (ms)")
    axes[1].set_ylim(0, 1.8)
    axes[1].legend(loc="upper right", fontsize=9)
    for ax in axes:
        ax.grid(axis="y")
        ax.set_xlim(.3, len(stats)+.7)
    axes[1].set_xticks(report)
    axes[1].set_xlabel("Stats-report index in the excerpt (not an exact time axis)")
    finish(fig, out, "Source: output.txt. Processing excludes the bulk per-sample Serial print and WiFi send; send duration is not network latency.\nZero WiFi duration means no send was measured in that report. Per-report maxima cannot be summed into end-to-end latency.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir/"plots").mkdir(exist_ok=True)
    serial, stats, receiver, events, lines = parse(args.log)
    assert serial and stats and receiver and events
    serial_by_seq = {r["seq"]: r for r in serial}
    matches = []
    for row in receiver:
        if row["seq"] in serial_by_seq:
            other = serial_by_seq[row["seq"]]
            diffs = [abs(a-b) for key in ("accel_filtered", "gyro_filtered")
                     for a,b in zip(row[key], other[key])]
            assert max(diffs) <= .000051, (row["seq"], diffs)
            matches.append(dict(seq=row["seq"], serial_line=other["line"],
                                receiver_line=row["line"], max_rounding_difference=max(diffs)))
    segments = contiguous_segments(serial)
    summaries = {key: dict(min=min(r[key] for r in stats), max=max(r[key] for r in stats))
                 for key in ("maxProducerJitterUs", "maxQueueLatencyUs", "maxProcessingUs", "avgProcessingUs",
                             "cpuMarginUs", "maxWifiSendUs", "avgWifiSendUs", "dropped", "sequenceGaps", "saturatedSamples")}
    peak = max(serial, key=lambda r: abs(r["accel_cal"][2]))
    serial_characters = np.array([r["chars"] for r in serial])
    summary = dict(
        source=args.log.name, source_line_count=len(lines), serial_sample_count=len(serial),
        stats_report_count=len(stats), receiver_printed_sample_count=len(receiver),
        serial_bursts=[dict(start=s[0]["seq"], end=s[-1]["seq"], count=len(s),
                            first_line=s[0]["line"], last_line=s[-1]["line"]) for s in segments],
        serial_move_events=events, receiver_moves_started=sum("move started" in x for x in lines),
        receiver_moves_ended=sum("move ended" in x for x in lines),
        receiver_gaps=[r for r in receiver if r["gap_expected"] is not None],
        cross_channel_matches=matches, stats_ranges=summaries,
        status_values=sorted(set(r["status"] for r in serial+receiver)),
        buffer_high_water_marks=sorted(set(r["highWaterMark"] for r in stats)),
        maximum_z_calibrated=peak,
        final_row=serial[-1], final_filtered_accel_norm=norm(serial[-1]["accel_filtered"]),
        final_filtered_gyro_norm=norm(serial[-1]["gyro_filtered"]),
        serial_line_bytes=dict(min=int(serial_characters.min()), max=int(serial_characters.max()),
            mean=float(serial_characters.mean()),
            mean_wire_time_ms_at_115200_8N1=float(serial_characters.mean()*10/115200*1000)),
        caveats=[
            "Console extract has no sample timestamps or annotated physical-action times.",
            "Serial rows are emitted only during movement and include the end boundary; idle absence is not proof of zero motion.",
            "Python console output is throttled; printed-row sequence differences are not packet-loss counts.",
            "GAP 6550->6560 matches known firmware stop/restart; GAP 861->921 lacks corresponding serial coverage.",
            "No end-to-end loss percentage, sample-rate distribution, or network latency can be calculated from this extract.",
            "No saturation flags in this capture does not positively test the saturation branch.",
            "Measured processing excludes bulk Serial prints and WiFi send; jitter is relative to a 5000 us target.",
        ],
    )
    (args.out_dir/"log_metrics.json").write_text(json.dumps(summary, indent=2)+"\n")
    style()
    plot_filter(serial, args.out_dir/"plots/02_filter_response.png")
    plot_transient(serial, args.out_dir/"plots/01_motion_bursts.png")
    plot_timing(stats, args.out_dir/"plots/03_timing_diagnostics.png")
    print(json.dumps({k:summary[k] for k in ("serial_sample_count", "stats_report_count",
        "receiver_printed_sample_count", "serial_bursts", "stats_ranges", "serial_line_bytes",
        "final_filtered_accel_norm", "final_filtered_gyro_norm")}, indent=2))


if __name__ == "__main__":
    main()
