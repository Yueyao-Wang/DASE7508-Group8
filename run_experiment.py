"""Run a paired experiment and write auditable CSV and JSON artifacts."""

import argparse
import csv
import platform
from pathlib import Path
from urllib.error import URLError

from lab import CONDITIONS, PROFILES, SYSTEM_PROMPT, OllamaChoice, run_trial, scenarios
from lab import simulated_choice, write_json


def rate(numerator, denominator):
    return numerator / denominator if denominator else None


def summarize(rows, conditions=CONDITIONS):
    summaries = []
    for condition in conditions:
        group = [row for row in rows if row["condition"] == condition]

        def total(field):
            return sum(row[field] for row in group)

        replay_tasks = total("replay_tasks")
        summaries.append({
            "condition": condition, "trials": len(group), "replay_tasks": replay_tasks,
            "immediate_math_rate": rate(total("immediate_math"), len(group)),
            "incident_success_rate": rate(total("incident_success"), len(group)),
            "UMR": rate(total("replay_math"), replay_tasks),
            "TSR": rate(total("replay_success"), replay_tasks),
            "chinese_accuracy": rate(total("replay_chinese"), replay_tasks),
            "RCR": rate(total("residual"), len(group)),
            "LPL": rate(total("lost_progress"), total("eligible_progress")),
            "lost_progress": total("lost_progress"),
            "eligible_progress": total("eligible_progress"),
        })
    baseline, incident, recovered = summaries[:3]
    threshold = 0.9 * baseline["TSR"] if baseline["TSR"] else None
    comparison = {
        "C1_minus_C0_UMR": incident["UMR"] - baseline["UMR"],
        "C2_minus_C0_UMR": recovered["UMR"] - baseline["UMR"],
        "C2_minus_C0_TSR": recovered["TSR"] - baseline["TSR"],
        "C2_minus_C1_UMR": recovered["UMR"] - incident["UMR"],
        "C2_TSR_minimum": threshold,
        "recovery_pass": (recovered["UMR"] == recovered["RCR"] == 0
                          and recovered["TSR"] >= threshold) if threshold else None,
    }
    return summaries, comparison


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("sim", "llm"), default="sim")
    parser.add_argument("--model", help="Installed Ollama model tag for llm mode")
    parser.add_argument("--profile", choices=PROFILES, action="append")
    parser.add_argument("--pre", choices=(1, 3), type=int)
    parser.add_argument("--delay", choices=(0, 2), type=int)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--replay", type=int, default=4)
    parser.add_argument("--seed", type=int, default=7508)
    parser.add_argument("--out", type=Path, required=True, help="New output directory")
    args = parser.parse_args()
    if args.repeats < 1 or args.replay < 1:
        parser.error("--repeats and --replay must be positive")
    if bool(args.model) != (args.mode == "llm"):
        parser.error("--model is required in llm mode and reserved for that mode")
    if args.out.exists():
        parser.error("--out already exists. Choose a new run directory.")

    profiles = list(dict.fromkeys(args.profile or PROFILES))
    design = [
        case for case in scenarios(profiles, args.repeats, args.seed)
        if (args.pre is None or args.pre == case.pre_steps)
        and (args.delay is None or args.delay == case.delay_steps)
    ]
    backend = simulated_choice if args.mode == "sim" else OllamaChoice(args.model)
    evidence = "scripted_simulation" if args.mode == "sim" else "llm_utility_with_scripted_incidents"
    args.out.mkdir(parents=True)
    manifest = {
        "status": "running", "mode": args.mode, "evidence": evidence,
        "model": args.model, "platform": platform.platform(), "python": platform.python_version(),
        "system_prompt": SYSTEM_PROMPT if args.model else None,
        "profiles": profiles, "seed": args.seed, "repeats": args.repeats,
        "replay_tasks_per_trial": args.replay,
        "cases": [case.__dict__ for case in design],
    }
    manifest_path = args.out / "manifest.json"
    write_json(manifest_path, manifest)
    rows = []
    try:
        for case in design:
            for condition in CONDITIONS:
                directory = args.out / "trials" / case.key / condition
                data = run_trial(directory, case, condition, backend, args.replay)
                rows.append({"evidence": evidence, **data})
    except URLError as error:
        write_json(manifest_path, {**manifest, "status": "failed", "error": str(error)})
        parser.exit(1, f"Ollama request failed: {error}\n")
    except Exception:
        write_json(manifest_path, {**manifest, "status": "failed"})
        raise

    summary, comparison = summarize(rows)
    strata = []
    cells = sorted({(r["profile"], r["pre_steps"], r["delay_steps"]) for r in rows})
    for profile, pre, delay in cells:
        group = [r for r in rows
                 if (r["profile"], r["pre_steps"], r["delay_steps"]) == (profile, pre, delay)]
        metrics, _ = summarize(group)
        strata.extend({"profile": profile, "pre_steps": pre, "delay_steps": delay, **r}
                      for r in metrics)
    write_csv(args.out / "trials.csv", rows)
    write_csv(args.out / "metrics.csv", [{"evidence": evidence, **r} for r in summary])
    write_csv(args.out / "strata.csv", [{"evidence": evidence, **r} for r in strata])
    write_json(args.out / "comparisons.json", comparison)
    write_json(manifest_path, {**manifest, "status": "complete", "trials": len(rows)})
    print(f"Wrote {len(rows)} trials to {args.out}")


if __name__ == "__main__":
    main()
