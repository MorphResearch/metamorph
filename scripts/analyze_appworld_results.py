#!/usr/bin/env python3
"""Aggregate AppWorld results with task-clustered paired bootstrap intervals."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from pathlib import Path
from typing import Any


def load_results(root: Path) -> list[dict[str, Any]]:
    results = []
    for path in sorted((root / "runs").glob("*/*/*/result.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["result_path"] = str(path)
        results.append(value)
    return results


def metric(result: dict[str, Any], name: str) -> float:
    if name == "official_reward":
        return float(result.get(name, 0.0) or 0.0)
    budget = result.get("budget") or {}
    return float(budget.get(name, 0.0) or 0.0)


def paired_task_values(
    results: list[dict[str, Any]],
    left: str,
    right: str,
    metric_name: str,
    *,
    split: str | None = None,
) -> tuple[list[float], list[str]]:
    if split is not None:
        results = [result for result in results if result.get("split") == split]
    by_condition_task_seed: dict[tuple[str, str, int], float] = {}
    for result in results:
        key = (result["condition"], result["task_id"], int(result["seed"]))
        by_condition_task_seed[key] = metric(result, metric_name)
    tasks = sorted({result["task_id"] for result in results})
    differences: list[float] = []
    missing: list[str] = []
    for task_id in tasks:
        left_by_seed = {
            seed: value
            for (condition, task, seed), value in by_condition_task_seed.items()
            if condition == left and task == task_id
        }
        right_by_seed = {
            seed: value
            for (condition, task, seed), value in by_condition_task_seed.items()
            if condition == right and task == task_id
        }
        common_seeds = sorted(set(left_by_seed) & set(right_by_seed))
        if not common_seeds or set(left_by_seed) != set(right_by_seed):
            missing.append(task_id)
            continue
        differences.append(statistics.fmean(left_by_seed[seed] - right_by_seed[seed] for seed in common_seeds))
    return differences, missing


def bootstrap_ci(values: list[float], *, samples: int, seed: int) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples))
    return means[int(0.025 * (samples - 1))], means[int(0.975 * (samples - 1))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=1901)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    results = load_results(args.run_root)
    if not results:
        raise ValueError("no result.json files found")
    expected_conditions = [item["id"] for item in config.get("conditions", []) + config.get("component_conditions", []) + config.get("edge_conditions", [])]
    expected_tasks = set(json.loads((args.run_root / "manifest.json").read_text(encoding="utf-8")).get("task_ids", []))
    # Older manifests store task IDs in the separately hashed task manifest.
    if not expected_tasks:
        manifest = json.loads((args.run_root / "manifest.json").read_text(encoding="utf-8"))
        task_manifest = json.loads(Path(manifest["task_manifest_path"]).read_text(encoding="utf-8"))
        expected_tasks = set(task_manifest["task_ids"])
    expected_seeds = set(config["seeds"])
    observed = {(item["condition"], item["task_id"], int(item["seed"])) for item in results}
    missing_runs = sorted(
        (condition, task, seed)
        for condition in expected_conditions
        for task in expected_tasks
        for seed in expected_seeds
        if (condition, task, seed) not in observed
    )
    contaminated_runs = sorted(
        (item["condition"], item["task_id"], int(item["seed"]))
        for item in results
        if (item.get("replay") or {}).get("replay_contamination")
    )
    if args.require_complete and missing_runs:
        raise ValueError(f"result matrix is incomplete; first missing runs: {missing_runs[:10]}")
    if args.require_complete and contaminated_runs:
        raise ValueError(f"replay contamination detected; first affected runs: {contaminated_runs[:10]}")

    summaries = []
    splits = sorted({str(item["split"]) for item in results if item.get("split")})
    for condition in expected_conditions:
        for split_name in ["overall", *splits]:
            subset = [
                item for item in results
                if item["condition"] == condition and (split_name == "overall" or item.get("split") == split_name)
            ]
            summaries.append({
                "condition": condition,
                "split": split_name,
                "runs": len(subset),
                "failed_runs": sum(item.get("status") != "completed" for item in subset),
                "strict_successes": sum(bool(item.get("strict_success")) for item in subset),
                "missing_token_usage_runs": sum(
                    bool((item.get("budget") or {}).get("missing_token_usage_calls")) for item in subset
                ),
                "mean_official_reward": statistics.fmean(metric(item, "official_reward") for item in subset) if subset else 0.0,
                "budget_constrained_completion_rate": statistics.fmean(
                    float(bool(item.get("strict_success")) and not bool((item.get("budget") or {}).get("budget_exhausted")))
                    for item in subset
                ) if subset else 0.0,
                "mean_total_tokens": statistics.fmean(metric(item, "total_tokens") for item in subset) if subset else 0.0,
                "mean_latency_seconds": statistics.fmean(metric(item, "latency_seconds") for item in subset) if subset else 0.0,
                "mean_tool_calls": statistics.fmean(metric(item, "tool_calls") for item in subset) if subset else 0.0,
            })

    contrasts = []
    for expression in config.get("statistical_plan", {}).get("primary_contrasts", []):
        left, separator, right = expression.partition(" - ")
        if not separator:
            continue
        for split_name in ["overall", *splits]:
            for metric_name in ("official_reward", "total_tokens", "latency_seconds", "tool_calls"):
                values, missing_pairs = paired_task_values(
                    results,
                    left,
                    right,
                    metric_name,
                    split=None if split_name == "overall" else split_name,
                )
                low, high = bootstrap_ci(values, samples=args.bootstrap_samples, seed=args.bootstrap_seed)
                contrasts.append({
                    "contrast": expression,
                    "split": split_name,
                    "metric": metric_name,
                    "paired_tasks": len(values),
                    "missing_pairs": len(missing_pairs),
                    "mean_difference": statistics.fmean(values) if values else 0.0,
                    "ci95_low": low,
                    "ci95_high": high,
                })

    tables = args.run_root / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    output = {
        "summary": summaries,
        "contrasts": contrasts,
        "missing_runs": missing_runs,
        "contaminated_runs": contaminated_runs,
    }
    (tables / "summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, rows in (("conditions.csv", summaries), ("contrasts.csv", contrasts)):
        if not rows:
            continue
        with (tables / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({
        "results": len(results),
        "missing_runs": len(missing_runs),
        "contaminated_runs": len(contaminated_runs),
        "tables": str(tables),
    }, indent=2))


if __name__ == "__main__":
    main()
