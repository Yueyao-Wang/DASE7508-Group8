"""Render the aggregate and timing plots from a completed run."""

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter


COLORS = ("#315982", "#B95E32", "#28796B", "#8165A3")


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def bars(ax, values, labels, colors, ylabel):
    for i, (value, color) in enumerate(zip(values, colors)):
        if value is None:
            ax.text(i, 0.03, "N/A", ha="center", fontsize=10)
            continue
        ax.bar(i, value, color=color, width=0.62, zorder=3)
        ax.text(i, value + 0.035, f"{value:.0%}", ha="center", fontsize=10)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_ylim(0, 1.16)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1])
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.set_title(ylabel, loc="left")
    ax.grid(axis="y", color="#E2E8F0")
    ax.spines[["top", "right", "left"]].set_visible(False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.run / "manifest.json").read_bytes())
    if manifest["status"] != "complete":
        parser.error("Expected a completed run")
    summary = read_rows(args.run / "metrics.csv")
    trials = read_rows(args.run / "trials.csv")
    labels_by_mode = {
        "sim": "Deterministic simulation",
        "llm": f"{manifest['model']} utility with scripted incidents",
        "real-agent": f"{manifest['model']} agent decisions",
    }
    label = labels_by_mode[manifest["mode"]]

    fig, axes = plt.subplots(2, 2, figsize=(9.5, 6.3), layout="constrained")
    for ax, field, title in zip(
        axes.flat, ("UMR", "TSR", "RCR", "LPL"),
        ("UMR · Unauthorized Math changes", "TSR · Correct Chinese-only tasks",
         "RCR · Residual memory contamination", "LPL · Legitimate progress lost"),
    ):
        values = [float(row[field]) if row[field] else None for row in summary]
        bars(ax, values, [row["condition"] for row in summary], COLORS, title)
    arms = ", ".join(row["condition"] for row in summary)
    fig.suptitle(f"Checkpoint recovery | {label}\n{manifest['trials']} trials across {arms}",
                 fontsize=14, fontweight="bold")
    fig.savefig(args.run / "metrics.png", dpi=160)
    plt.close(fig)

    timing = sorted({(int(r["pre_steps"]), int(r["delay_steps"])) for r in trials})
    labels, means = [], []
    for pre, delay in timing:
        lost = [int(row["lost_progress"]) for row in trials if row["condition"] == "C2"
                and (int(row["pre_steps"]), int(row["delay_steps"])) == (pre, delay)]
        labels.append(f"{pre} before\n{delay} delay")
        means.append(sum(lost) / len(lost))
    fig, ax = plt.subplots(figsize=(8.3, 4.1), layout="constrained")
    ax.bar(labels, means, color=COLORS[2], width=0.6, zorder=3)
    ax.bar_label(ax.containers[0], fmt="%.2f", padding=4)
    ax.set_ylim(0, max(means) * 1.2 + 0.25)
    ax.set_ylabel("Mean number of correct edits lost per trial")
    ax.set_xlabel("Tasks before incident and during response delay")
    ax.set_title(f"C2 rollback cost | {label}", loc="left", fontweight="bold")
    ax.grid(axis="y", color="#E2E8F0")
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(args.run / "rollback_cost.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
