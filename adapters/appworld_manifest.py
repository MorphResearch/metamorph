"""Deterministic AppWorld task-manifest preparation and label validation."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .appworld_experiment import git_commit, load_json, sha256_file


SELECTION_ALGORITHM = "scenario-round-robin-sha256-v1"


def _rank(value: str, seed: int) -> str:
    return hashlib.sha256(f"{value}:{seed}".encode("utf-8")).hexdigest()


def stratified_task_ids(task_ids: list[str], count: int | str, seed: int, scenario_of: Any) -> list[str]:
    if count == "all":
        return sorted(task_ids, key=lambda item: _rank(item, seed))
    count = int(count)
    if count < 1 or count > len(task_ids):
        raise ValueError(f"selection count {count} is invalid for {len(task_ids)} tasks")
    groups: dict[str, deque[str]] = defaultdict(deque)
    for task_id in task_ids:
        groups[str(scenario_of(task_id))].append(task_id)
    for scenario, values in list(groups.items()):
        groups[scenario] = deque(sorted(values, key=lambda item: _rank(item, seed)))
    ordered_groups = sorted(groups, key=lambda item: _rank(item, seed))
    selected: list[str] = []
    while len(selected) < count:
        made_progress = False
        for scenario in ordered_groups:
            if groups[scenario]:
                selected.append(groups[scenario].popleft())
                made_progress = True
                if len(selected) == count:
                    break
        if not made_progress:
            break
    return selected


def prepare_task_manifest(
    *,
    config_path: Path,
    selection_path: Path,
    appworld_dir: Path,
    output_path: Path,
) -> dict[str, Any]:
    config = load_json(config_path)
    selection = load_json(selection_path)
    set_name = config["task_set"]
    set_config = selection["sets"][set_name]
    if "reuse_task_set" in set_config:
        set_name = set_config["reuse_task_set"]
        set_config = selection["sets"][set_name]
    previous_cwd = Path.cwd()
    os.chdir(appworld_dir)
    try:
        if str(appworld_dir / "src") not in sys.path:
            sys.path.insert(0, str(appworld_dir / "src"))
        from appworld import load_task_ids
        from appworld.task import task_id_to_generator_id

        splits: dict[str, list[str]] = {}
        for split_name, split_config in set_config["splits"].items():
            available = list(load_task_ids(split_name))
            splits[split_name] = stratified_task_ids(
                available,
                split_config["count"],
                int(split_config.get("selection_seed", 0)),
                task_id_to_generator_id,
            )
    finally:
        os.chdir(previous_cwd)
    flat = [task_id for task_ids in splits.values() for task_id in task_ids]
    if len(flat) != len(set(flat)):
        raise ValueError("task manifest contains duplicate task IDs across splits")
    manifest = {
        "schema_version": "appworld.task-manifest.v1",
        "benchmark": "AppWorld",
        "task_set": config["task_set"],
        "resolved_selection_set": set_name,
        "appworld_commit": git_commit(appworld_dir),
        "selection_algorithm": SELECTION_ALGORITHM,
        "selection_config_hash": sha256_file(selection_path),
        "splits": splits,
        "task_ids": flat,
        "task_count": len(flat),
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest["selection_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        existing = load_json(output_path)
        if existing != manifest:
            raise ValueError(f"refusing to overwrite a different frozen task manifest: {output_path}")
        return manifest
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
