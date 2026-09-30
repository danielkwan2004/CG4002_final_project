"""Rebuild presentation figures from the two final, unmodified LiPo captures.

Requires numpy and matplotlib. Never changes source evidence or legacy plots.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RUNS = {
    "Console A": "p1_p2_20260930_213118_596228",
    "Dashboard B": "p1_p2_20260930_213429_016641",
}
INK, BLUE, ORANGE, MUTED = "#162b3f", "#116a89", "#cd562c", "#526578"


def read_run(root, label, folder):
    path = root / folder
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    assert summary["invalid_packets"] == 0, f"{label}: invalid packets"
    assert len(summary["sessions"]) == 1, f"{label}: ambiguous session"
    session = summary["sessions"][0]
    config, timing = session["configuration"], session["timing"]
    assert config["verified"] and config["gyro_config"] == 0x27
    assert config["accel_config"] == 0x27 and config["pwr_mgmt"] == 0x0F
    assert config["gyro_lsb_per_dps"] == 16.4 and config["accel_lsb_per_g"] == 2048
    assert config["diag_scheduler"] == "staggered_v1"
    with (path / "samples.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    data = {key: np.array([float(row[key]) for row in rows])
            for key in rows[0] if key != "sender_ip"}
    assert set(data["boot_id"]) == {session["boot"]}
    assert len(set(zip(data["burst_id"], data["burst_index"]))) == len(rows)
    delivery = session["capture_delivery"]
    assert delivery["sender_attempted"] == delivery["sender_accepted"] == delivery["received_unique"] == len(rows)
    assert not delivery["partial_burst_ids"] and not delivery["pending_burst_ids"]
    assert not delivery["historical_burst_ids"] and delivery["unseen_burst_count"] == 0
    for burst in session["bursts"].values():
        assert burst["gate_closed"] and burst["complete_sender_summary"] and burst["counts_consistent"]
        assert all(burst[key] == 0 for key in (
            "duplicates", "reordered", "conflicting_packets", "pending_samples", "accepted_not_received"))
    assert timing["interval_count"] == timing["produced"] - 1
    assert sum(timing["interval_histogram_us"].values()) == timing["interval_count"]
    assert timing["interval_histogram_us"]["4500-5499"] == timing["interval_count"]
    assert timing["skipped_deadlines"] == timing["buffer_drops"] == 0
    assert session["transport"]["failed"] == session["txqueue"]["dropped"] == session["txqueue"]["pending"] == 0
    # CSV contains movement frames only. Use the first transmitted frame as
    # the plotting origin; do not reconstruct untransmitted idle timestamps.
    data["plot_s"] = (data["timestamp_us"] - data["timestamp_us"][0]) / 1e6
    return {"label": label, "folder": folder, "session": session, "data": data,
            "sha256": {name: hashlib.sha256((path / name).read_bytes()).hexdigest()
                       for name in ("metadata.json", "summary.json", "samples.csv", "diagnostics.jsonl")}}


def style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 14,
                         "axes.titlesize": 16, "axes.labelsize": 14,
                         "text.color": INK, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#c1ced8", "grid.color": "#dbe3ea",
                         "figure.facecolor": "white", "axes.facecolor": "white"})


def finish(fig, path, footer):
    fig.text(.075, .035, footer, fontsize=10, color=MUTED)
    fig.savefig(path, dpi=160, facecolor="white")
    plt.close(fig)


def motion_plot(run, output):
    data = run["data"]
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    fig.subplots_adjust(left=.105, right=.97, top=.84, bottom=.17, hspace=.30)
    fig.suptitle("Movement packets follow the gate", x=.075, y=.96, ha="left", fontsize=23, weight="bold")
    fig.text(.075, .895, "Dashboard B  |  16 closed bursts  |  5,405 movement samples", color=MUTED, fontsize=14)
    gyro = np.sqrt(sum(data[f"g{axis}_filtered_dps"] ** 2 for axis in "xyz"))
    accel = abs(np.sqrt(sum(data[f"a{axis}_filtered_g"] ** 2 for axis in "xyz")) - 1)
    for burst in sorted(set(data["burst_id"])):
        mask = data["burst_id"] == burst
        time = data["plot_s"][mask]
        for ax, values in zip(axes, (gyro, accel)):
            ax.axvspan(time[0], time[-1], color=BLUE, alpha=.07)
            ax.plot(time, values[mask], color=BLUE, linewidth=1.15)
    for ax, start, stop in zip(axes, (40, .30), (15, .15)):
        ax.axhline(start, color=ORANGE, linestyle="--", linewidth=1.3, label=f"Start: {start:g}")
        ax.axhline(stop, color=MUTED, linestyle=":", linewidth=1.3, label=f"Stop: {stop:g}")
        ax.grid(axis="y", alpha=.65)
        ax.legend(loc="lower right", bbox_to_anchor=(1, 1.01), fontsize=11, frameon=False, ncol=2)
        ax.set_xlim(0, data["plot_s"][-1] + .6)
    axes[0].set_ylabel("Filtered gyro\nmagnitude (deg/s)")
    axes[1].set_ylabel("Filtered acceleration\n|magnitude − 1| (g)")
    axes[1].set_xlabel("Device time since first transmitted movement sample (s)")
    finish(fig, output / "04_verified_motion.png",
           "30 Sep 2026 · Run B · Shading spans transmitted bursts, including boundary frames.\n"
           "Blank gaps contain no transmitted waveform; they do not mean zero motion. Physical actions were not timestamp-labelled.")


def filter_plot(run, output):
    data, config = run["data"], run["session"]["configuration"]
    # First two seconds of the longest received burst, selected reproducibly,
    # not by maximizing a favourable attenuation or timing statistic.
    ids, counts = np.unique(data["burst_id"], return_counts=True)
    burst_id = ids[np.argmax(counts)]
    burst = data["burst_id"] == burst_id
    origin = data["timestamp_us"][burst][0]
    time = (data["timestamp_us"] - origin) / 1e6
    mask = burst & (time <= 2.0)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    fig.subplots_adjust(left=.105, right=.97, top=.84, bottom=.17, hspace=.32)
    fig.suptitle("Low-pass filtering smooths — and softens peaks", x=.075, y=.96,
                 ha="left", fontsize=23, weight="bold")
    fig.text(.075, .895, f"Dashboard B  |  Burst {int(burst_id)}: first 2 seconds  |  alpha = 0.2", color=MUTED)
    gyro_input = (data["gz_raw"] - config["gyro_bias_counts"][2]) / config["gyro_lsb_per_dps"]
    inputs = (data["az_g"], gyro_input)
    filtered = (data["az_filtered_g"], data["gz_filtered_dps"])
    for ax, before, after, label in zip(axes, inputs, filtered, ("Z acceleration (g)", "Z angular rate (deg/s)")):
        ax.plot(time[mask], before[mask], color=MUTED, alpha=.7, linewidth=1.2, label="Calibrated input")
        ax.plot(time[mask], after[mask], color=BLUE, linewidth=2.1, label="Filtered output")
        ax.set_ylabel(label)
        ax.grid(axis="y", alpha=.6)
        ax.legend(loc="lower right", bbox_to_anchor=(1, 1.01), fontsize=11, frameon=False, ncol=2)
    axes[1].set_xlabel(f"Device time since start of burst {int(burst_id)} (s)")
    axes[1].set_xlim(0, 2)
    finish(fig, output / "05_verified_filter.png",
           "30 Sep 2026 · Run B · Gyro input = (raw counts − measured bias) / 16.4; acceleration input includes offset correction.\n"
           "A measured processing example, not a ground-truth motion reference or a noise-reduction accuracy test.")
    return {"run": run["folder"], "burst_id": int(burst_id), "window_seconds": [0, 2],
            "selection": "First two seconds of the longest received burst", "samples": int(mask.sum())}


def timing_plot(runs, output):
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.subplots_adjust(left=.20, right=.96, top=.74, bottom=.29)
    fig.suptitle("Both captures stayed close to the 5 ms target", x=.075, y=.96,
                 ha="left", fontsize=23, weight="bold")
    total = sum(run["session"]["timing"]["interval_count"] for run in runs)
    fig.text(.075, .89, f"{total:,} device intervals, including idle  |  0 skipped deadlines  |  0 acquisition-buffer drops", fontsize=14)
    ax.axvspan(4.5, 5.5, color=BLUE, alpha=.06)
    ax.axvline(5, color=ORANGE, linestyle="--", linewidth=1.4, label="5 ms target")
    for y, run in zip((1, 0), runs):
        timing = run["session"]["timing"]
        low, mean, high = [timing[key] / 1000 for key in ("min_interval_us", "mean_interval_us", "max_interval_us")]
        ax.plot([low, high], [y, y], color=BLUE, linewidth=5, solid_capstyle="round")
        ax.scatter([mean], [y], color=INK, s=85, zorder=3)
        ax.text(low, y+.15, f"{low:.3f} ms", ha="center", fontsize=13)
        ax.text(high, y+.15, f"{high:.3f} ms", ha="center", fontsize=13)
        ax.text(4.51, y-.23, f"{timing['produced']:,} acquisitions · {timing['acquisition_span_s']:.2f} s · mean {mean:.3f} ms", fontsize=12, color=MUTED)
    ax.set_yticks([1, 0], ["Console A", "Dashboard B"])
    ax.set_ylim(-.55, 1.55)
    ax.set_xlim(4.5, 5.5)
    ax.set_xlabel("Completed-read interval (ms) · bars = observed min–max · dots = mean")
    ax.grid(axis="x", alpha=.55)
    ax.legend(loc="upper right", frameon=False, fontsize=12)
    finish(fig, output / "06_verified_timing.png",
           "30 Sep 2026 · Final cumulative timing reports: A 21:31:18; B 21:34:29. Timing covers all acquisitions, not just movement CSV rows.\n"
           "Observed intervals all fit 4.5–5.5 ms. Software read timestamps do not verify every distinct IMU hardware update.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, default=Path(__file__).resolve().parent.parent / "captures")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    runs = [read_run(args.captures, label, folder) for label, folder in RUNS.items()]
    output = args.output / "plots"
    output.mkdir(parents=True, exist_ok=True)
    style()
    motion_plot(runs[1], output)
    example = filter_plot(runs[1], output)
    timing_plot(runs, output)
    metrics = {"evidence_date": "2026-09-30", "power_source": "LiPo, USB disconnected; operator-reported",
               "filter_example": example, "runs": []}
    for run in runs:
        session = run["session"]
        metrics["runs"].append({"label": run["label"], "source_folder": run["folder"],
            "source_sha256": run["sha256"], "boot": session["boot"],
            "timing": session["timing"], "capture_delivery": session["capture_delivery"],
            "transport": session["transport"], "txqueue": session["txqueue"]})
    (args.output / "verified_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"Validated both captures; wrote 3 figures and verified_metrics.json to {args.output}")


if __name__ == "__main__":
    main()
