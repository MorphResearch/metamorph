#!/usr/bin/env python3
"""Prepare an immutable, outcome-independent AppWorld task manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters.appworld_manifest import prepare_task_manifest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--selection", type=Path, default=PROJECT_ROOT / "experiments/appworld/task_selection.json")
    parser.add_argument("--appworld-dir", type=Path, default=PROJECT_ROOT / "benchmarks/appworld")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare_task_manifest(
        config_path=args.config.resolve(),
        selection_path=args.selection.resolve(),
        appworld_dir=args.appworld_dir.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps({"output": str(args.output.resolve()), "task_count": result["task_count"], "selection_hash": result["selection_hash"]}, indent=2))


if __name__ == "__main__":
    main()
