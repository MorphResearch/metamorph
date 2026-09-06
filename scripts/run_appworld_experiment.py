#!/usr/bin/env python3
"""Run or preflight the frozen AppWorld E1/E2 experiment matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters.appworld_adapter import ProviderPhaseModel  # noqa: E402
from adapters.appworld_experiment import AppWorldExperimentRunner, load_json  # noqa: E402
from config import Settings  # noqa: E402
from llm.client import build_client  # noqa: E402


class NoCallModel:
    def __init__(self, provider: str, model_name: str) -> None:
        self.provider = provider
        self.model_name = model_name

    def complete(self, **kwargs):
        raise RuntimeError("model calls are disabled during preflight")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--appworld-dir", type=Path, default=PROJECT_ROOT / "benchmarks/appworld")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    task_manifest = load_json(args.task_manifest.resolve())
    task_ids = list(args.task_id or task_manifest["task_ids"])
    unknown_tasks = sorted(set(task_ids) - set(task_manifest["task_ids"]))
    if unknown_tasks:
        raise ValueError(f"task IDs are not in the frozen manifest: {unknown_tasks[:10]}")
    if args.limit is not None:
        task_ids = task_ids[: max(0, args.limit)]
    if not task_ids:
        raise ValueError("at least one frozen task must be selected")
    config = load_json(args.config.resolve())
    selected_conditions = set(args.condition) or None
    known_conditions = {
        item["id"]
        for item in (
            config.get("conditions", [])
            + config.get("component_conditions", [])
            + config.get("edge_conditions", [])
            + config.get("replay_conditions", [])
        )
    }
    if selected_conditions is not None and not selected_conditions <= known_conditions:
        raise ValueError(f"unknown conditions: {sorted(selected_conditions - known_conditions)}")
    settings = Settings.from_environment(data_dir=args.output_root.resolve() / "runtime")
    if args.formal and settings.provider == "mock":
        raise ValueError("formal AppWorld experiments cannot use the mock provider")
    if args.preflight_only and not args.formal:
        model = NoCallModel(settings.provider, settings.model_name)
    else:
        # Construction validates provider/model/API-key configuration but does
        # not issue a network request. Formal preflight therefore catches a
        # missing credential before creating an experiment manifest.
        model = ProviderPhaseModel(build_client(settings.provider, settings.model_name, settings.base_url, settings.api_key_env))
    runner = AppWorldExperimentRunner(
        config_path=args.config,
        task_manifest_path=args.task_manifest,
        appworld_dir=args.appworld_dir,
        output_root=args.output_root,
        model=model,
        formal=args.formal,
        resume=args.resume,
    )
    manifest_path = runner.write_manifest()
    if args.preflight_only:
        print(json.dumps({"status": "preflight_passed", "manifest": str(manifest_path), "task_count": len(task_ids)}, indent=2))
        return
    results = []
    for seed in config["seeds"]:
        for task_id in task_ids:
            results.extend(runner.run_task(task_id, int(seed), selected_conditions))
    failures = sum(item.get("status") != "completed" for item in results)
    print(json.dumps({"status": "completed", "runs": len(results), "failures": failures, "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
