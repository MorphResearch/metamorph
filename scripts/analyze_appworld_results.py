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


def metric(result: dict[str, Any], name: str) -> float | None:
    if name == "strict_success":
        return float(bool(result.get("strict_success", False)))
    if name == "official_reward":
        return float(result.get(name, 0.0) or 0.0)
    if name == "cost_usd":
        value = result.get("cost_usd")
        return float(value) if value is not None else None
    budget = result.get("budget") or {}
    if name not in budget or budget.get(name) is None:
        return None
    return float(budget[name])


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
    by_condition_task_seed: dict[tuple[str, str, int], float | None] = {}
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
        if not common_seeds or set(left_by_seed) != set(right_by_seed) or any(
            left_by_seed[seed] is None or right_by_seed[seed] is None for seed in common_seeds
        ):
            missing.append(task_id)
            continue
        differences.append(statistics.fmean(
            float(left_by_seed[seed]) - float(right_by_seed[seed]) for seed in common_seeds
        ))
    return differences, missing


def bootstrap_ci(values: list[float], *, samples: int, seed: int) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples))
    return means[int(0.025 * (samples - 1))], means[int(0.975 * (samples - 1))]


def e3_profile_rows(results: list[dict[str, Any]], profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply a frozen task-family routing rule to already-observed P3 arms.

    This does not choose a DAG from test outcomes: the profile must provide a
    task-to-family mapping and a family-to-DAG mapping committed before P3.
    Reusing the matching E1 arm avoids an unpaired duplicate model run.
    """

    task_family = profile.get("task_family", {})
    family_to_dag = profile.get("family_to_dag", {})
    lambdas = [float(value) for value in profile.get("lambda_cost_usd", [])]
    indexed = {(item["condition"], item["task_id"], int(item["seed"])): item for item in results}
    task_seed_pairs = sorted({(item["task_id"], int(item["seed"])) for item in results})
    rows: list[dict[str, Any]] = []
    for task_id, seed in task_seed_pairs:
        family = task_family.get(task_id)
        selected = family_to_dag.get(family)
        profile_result = indexed.get((selected, task_id, seed)) if selected else None
        g0 = indexed.get(("G0", task_id, seed))
        g3 = indexed.get(("G3", task_id, seed))
        row: dict[str, Any] = {
            "task_id": task_id,
            "seed": seed,
            "family": family,
            "profile_condition": selected,
            "profile_available": profile_result is not None,
            "g0_available": g0 is not None,
            "g3_available": g3 is not None,
        }
        for prefix, item in (("profile", profile_result), ("g0", g0), ("g3", g3)):
            row[f"{prefix}_strict_success"] = metric(item, "strict_success") if item else None
            row[f"{prefix}_cost_usd"] = metric(item, "cost_usd") if item else None
            row[f"{prefix}_protocol_valid"] = item.get("protocol_valid") if item else None
        for value in lambdas:
            for prefix in ("profile", "g0", "g3"):
                success = row[f"{prefix}_strict_success"]
                cost = row[f"{prefix}_cost_usd"]
                row[f"{prefix}_utility_lambda_{value:g}"] = None if success is None or cost is None else success - value * cost
        rows.append(row)

    summaries = []
    for value in lambdas:
        key = f"utility_lambda_{value:g}"
        complete = [row for row in rows if all(row.get(f"{prefix}_{key}") is not None for prefix in ("profile", "g0", "g3"))]
        summaries.append({
            "lambda_cost_usd": value,
            "paired_tasks": len(complete),
            "mean_profile_utility": statistics.fmean(row[f"profile_{key}"] for row in complete) if complete else None,
            "mean_g0_utility": statistics.fmean(row[f"g0_{key}"] for row in complete) if complete else None,
            "mean_g3_utility": statistics.fmean(row[f"g3_{key}"] for row in complete) if complete else None,
        })
    return rows, summaries


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
    invalid_protocol_runs = sorted(
        (item["condition"], item["task_id"], int(item["seed"]))
        for item in results
        if item.get("protocol_valid") is False
    )
    if args.require_complete and missing_runs:
        raise ValueError(f"result matrix is incomplete; first missing runs: {missing_runs[:10]}")
    if args.require_complete and contaminated_runs:
        raise ValueError(f"replay contamination detected; first affected runs: {contaminated_runs[:10]}")
    if args.require_complete and invalid_protocol_runs:
        raise ValueError(f"protocol-invalid runs detected; first affected runs: {invalid_protocol_runs[:10]}")

    summaries = []
    splits = sorted({str(item["split"]) for item in results if item.get("split")})
    for condition in expected_conditions:
        for split_name in ["overall", *splits]:
            subset = [
                item for item in results
                if item["condition"] == condition and (split_name == "overall" or item.get("split") == split_name)
            ]
            def observed(name: str) -> list[float]:
                return [value for item in subset if (value := metric(item, name)) is not None]

            summaries.append({
                "condition": condition,
                "split": split_name,
                "runs": len(subset),
                "failed_runs": sum(item.get("status") != "completed" for item in subset),
                "strict_successes": sum(bool(item.get("strict_success")) for item in subset),
                "missing_token_usage_runs": sum(
                    bool((item.get("budget") or {}).get("missing_token_usage_calls")) for item in subset
                ),
                "mean_strict_success": statistics.fmean(observed("strict_success")) if subset else 0.0,
                "budget_constrained_completion_rate": statistics.fmean(
                    float(bool(item.get("strict_success")) and not bool((item.get("budget") or {}).get("budget_exhausted")))
                    for item in subset
                ) if subset else 0.0,
                "mean_input_tokens": statistics.fmean(observed("input_tokens")) if observed("input_tokens") else None,
                "mean_output_tokens": statistics.fmean(observed("output_tokens")) if observed("output_tokens") else None,
                "mean_total_tokens": statistics.fmean(observed("total_tokens")) if observed("total_tokens") else None,
                "mean_latency_seconds": statistics.fmean(observed("latency_seconds")) if observed("latency_seconds") else None,
                "mean_tool_calls": statistics.fmean(observed("tool_calls")) if observed("tool_calls") else None,
                "mean_cost_usd": statistics.fmean(observed("cost_usd")) if observed("cost_usd") else None,
                "unknown_cost_runs": sum(metric(item, "cost_usd") is None for item in subset),
            })

    contrasts = []
    for expression in config.get("statistical_plan", {}).get("primary_contrasts", []):
        left, separator, right = expression.partition(" - ")
        if not separator:
            continue
        for split_name in ["overall", *splits]:
            for metric_name in ("strict_success", "input_tokens", "output_tokens", "total_tokens", "latency_seconds", "tool_calls", "cost_usd"):
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
        "invalid_protocol_runs": invalid_protocol_runs,
    }
    profile_rows: list[dict[str, Any]] = []
    profile_summary: list[dict[str, Any]] = []
    if config.get("e3_profile"):
        profile_rows, profile_summary = e3_profile_rows(results, config["e3_profile"])
        output["e3_profile"] = {"summary": profile_summary, "rows": profile_rows}
    (tables / "summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_rows = [
        {
            "condition": item.get("condition"), "task_id": item.get("task_id"), "split": item.get("split"),
            "seed": item.get("seed"), "status": item.get("status"), "strict_success": item.get("strict_success"),
            "protocol_valid": item.get("protocol_valid"), "failure_category": item.get("failure_category"),
            "input_tokens": metric(item, "input_tokens"), "output_tokens": metric(item, "output_tokens"),
            "total_tokens": metric(item, "total_tokens"), "latency_seconds": metric(item, "latency_seconds"),
            "tool_calls": metric(item, "tool_calls"), "cost_usd": metric(item, "cost_usd"),
            "replay_contamination": (item.get("replay") or {}).get("replay_contamination"),
            "result_path": item["result_path"],
        }
        for item in results
    ]
    for name, rows in (
        ("conditions.csv", summaries),
        ("contrasts.csv", contrasts),
        ("task_results.csv", raw_rows),
        ("e3_profile.csv", profile_rows),
        ("e3_profile_summary.csv", profile_summary),
    ):
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
