#!/usr/bin/env python3
"""Offline-only Formal Experiment V1 source freeze and receiver materializer.

This program deliberately imports neither provider nor evaluator code.  It reads
only the frozen formal-source manifests, authorizations, records, snapshots, and
RAW records; it refuses to overwrite an existing freeze directory.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import stat
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "artifacts/experience_value/formal_source"
FREEZE_ROOT = ROOT / "artifacts/experience_value/formal_freeze"
RESOURCE_ROOT = ROOT / "artifacts/experience_value/formal_receiver_resources_v1"

RUN_IDS = (
    "e0-e808a2e0f18a4eccad1e69f0d5d70f9c",
    "e0-53015e067721498eb3e8835b5dd3411d",
    "e0-9794526fea7b42f0906109faa8839faf",
    "e0-3430b92d62f0472aac17f2f07a917052",
    "e0-dc6e03395e4a4aa7b86c52430d97bda2",
    "e0-dbae883e65154899b20be4a9d9cd20ba",
    "e0-3298ad04692e43a99ebcb57ba71ccb48",
    "e0-915ba68f669343ecb1f1cad12f738881",
)
CONDITIONS = ("F0", "U0", "F1", "U1")
SOURCE_TASKS = tuple(range(7, 15))


class FreezeError(RuntimeError):
    """An integrity check failed before any new frozen output was written."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read JSON: {path}") from exc
    if not isinstance(result, dict):
        raise FreezeError(f"JSON root is not an object: {path}")
    return result


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def must_within(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise FreezeError(f"{label} escapes its allowed root: {path}") from exc
    return resolved


def regular_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise FreezeError(f"missing directory: {root}")
    result: list[Path] = []
    for item in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_symlink() or (item.exists() and not item.is_file() and not item.is_dir()):
            raise FreezeError(f"snapshot/package has an unsupported entry: {item}")
        if item.is_file():
            result.append(item)
    return result


def hash_tree(root: Path) -> tuple[str, list[str]]:
    """The frozen workspace snapshot hash algorithm (names, exec bit, bytes)."""
    digest = hashlib.sha256()
    files: list[str] = []
    for item in regular_files(root):
        name = item.relative_to(root).as_posix()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0file\0")
        digest.update(b"x" if item.stat().st_mode & stat.S_IXUSR else b"-")
        digest.update(b"\0")
        digest.update(hashlib.sha256(item.read_bytes()).digest())
        files.append(name)
    return digest.hexdigest(), files


def authorized_file(block_number: int) -> Path:
    stem = f"formal_source_block_{block_number:02d}.authorization.authorized_"
    candidates = sorted((ROOT / "experiments/experience_value").glob(stem + "*.json"))
    if len(candidates) != 1:
        raise FreezeError(f"expected exactly one consumed authorization for block {block_number}, found {len(candidates)}")
    return candidates[0]


def snapshot_directory(run_id: str, expected_hash: str, expected_files: list[str]) -> tuple[Path, str]:
    run_root = SOURCE_ROOT / run_id
    snapshots = run_root / "frozen_snapshots"
    candidates: list[tuple[Path, str]] = []
    if not snapshots.is_dir():
        raise FreezeError(f"frozen snapshot directory is missing for {run_id}")
    for candidate in sorted(snapshots.iterdir(), key=lambda value: value.name):
        if not candidate.is_dir() or candidate.is_symlink():
            raise FreezeError(f"invalid snapshot directory entry: {candidate}")
        observed_hash, observed_files = hash_tree(candidate)
        if observed_hash == expected_hash and observed_files == expected_files:
            candidates.append((candidate, candidate.name))
    if len(candidates) != 1:
        raise FreezeError(
            f"expected exactly one snapshot matching record in {run_id}; found {len(candidates)} "
            f"for hash {expected_hash}"
        )
    return candidates[0]


def source_token(task_id: str, condition: str) -> str:
    return f"t{int(task_id):02d}-{condition}"


def serializable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination, follow_symlinks=False)
    os.chmod(destination, stat.S_IMODE(source.stat().st_mode))


def immutable_tree(root: Path) -> None:
    for item in regular_files(root):
        os.chmod(item, stat.S_IRUSR | (stat.S_IXUSR if item.stat().st_mode & stat.S_IXUSR else 0))
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        os.chmod(directory, stat.S_IRUSR | stat.S_IXUSR)
    os.chmod(root, stat.S_IRUSR | stat.S_IXUSR)


def assert_raw_schema(raw: dict[str, Any], episode: dict[str, Any]) -> None:
    allowed = {"condition", "evaluator_or_reference_visible", "kind", "messages", "source_episode", "source_label"}
    if set(raw) != allowed:
        raise FreezeError(f"RAW schema drift for {episode['episode_id']}: {sorted(raw)}")
    if raw["kind"] != "RAW_source_episode" or raw["condition"] != episode["condition"]:
        raise FreezeError(f"RAW identity mismatch for {episode['episode_id']}")
    if raw["source_episode"] != episode["episode_id"] or raw["source_label"] != episode["episode_id"]:
        raise FreezeError(f"RAW source label mismatch for {episode['episode_id']}")
    if raw["evaluator_or_reference_visible"] is not False or not isinstance(raw["messages"], list):
        raise FreezeError(f"RAW visibility/schema check failed for {episode['episode_id']}")


def validate_historical_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    source_manifest_path = ROOT / "FORMAL_SOURCE_MANIFEST_V1.json"
    blocks_path = ROOT / "FORMAL_SOURCE_BLOCKS_V1.json"
    protocol_path = ROOT / "FORMAL_EXPERIMENT_PROTOCOL_V1.md"
    receiver_manifest_path = ROOT / "FORMAL_RECEIVER_MANIFEST_V1.json"
    source = read_json(source_manifest_path)
    blocks = read_json(blocks_path)
    receiver = read_json(receiver_manifest_path)
    source_hash, blocks_hash, protocol_hash = sha256_file(source_manifest_path), sha256_file(blocks_path), sha256_file(protocol_path)
    if source.get("formal_eligible", {}).get("source_task_ids") != list(SOURCE_TASKS):
        raise FreezeError("frozen source task set is not exactly 7..14")
    if source.get("development_contacted_ids") != list(range(1, 7)):
        raise FreezeError("development exclusion is not exactly IDs 1..6")
    if source.get("execution_order") is None or len(source["execution_order"]) != 32:
        raise FreezeError("frozen source execution order is not length 32")
    if receiver.get("receiver_conditions") != ["EMPTY", "M_F", "M_U", "RAW_F", "RAW_U"]:
        raise FreezeError("receiver resources differ from frozen receiver manifest")
    # Only schema-level receiver fields are used; no probe task content is opened.
    if receiver.get("probe_task_ids") != list(range(15, 21)):
        raise FreezeError("receiver manifest probe-ID guard is inconsistent")

    episodes: list[dict[str, Any]] = []
    run_metadata: list[dict[str, Any]] = []
    for index, run_id in enumerate(RUN_IDS, start=1):
        authorization_path = authorized_file(index)
        authorization = read_json(authorization_path)
        expected_block = blocks.get("blocks", [])[index - 1]
        if authorization.get("consumption_run_id") != run_id:
            raise FreezeError(f"authorization/run binding mismatch for block {index}")
        if authorization.get("study_kind") != "formal_source_v1" or authorization.get("included_in_primary_analysis") is not True:
            raise FreezeError(f"authorization eligibility mismatch for block {index}")
        if authorization.get("source_manifest", {}).get("sha256") != source_hash:
            raise FreezeError(f"source manifest hash mismatch in authorization for block {index}")
        if authorization.get("formal_protocol", {}).get("sha256") != protocol_hash:
            raise FreezeError(f"formal protocol hash mismatch in authorization for block {index}")
        if authorization.get("block_definition", {}).get("sha256") != blocks_hash:
            raise FreezeError(f"source block hash mismatch in authorization for block {index}")
        block_auth = authorization.get("block_definition", {})
        if block_auth.get("allowed_manifest_positions") != expected_block.get("manifest_positions") or block_auth.get("allowed_tokens") != expected_block.get("expected_tokens"):
            raise FreezeError(f"authorization block contents mismatch for block {index}")
        entry = authorization.get("entry_code", {})
        entry_path = ROOT / str(entry.get("path", ""))
        if not entry_path.is_file() or sha256_file(entry_path) != entry.get("sha256"):
            raise FreezeError(f"historical runner entry hash mismatch for block {index}")
        pending = authorization.get("frozen_pending_config", {})
        pending_path = ROOT / str(pending.get("path", ""))
        if not pending_path.is_file() or sha256_file(pending_path) != pending.get("sha256"):
            raise FreezeError(f"frozen pending configuration hash mismatch for block {index}")
        if authorization.get("development_exclusion", {}).get("task_ids") != list(range(1, 7)) or authorization.get("development_exclusion", {}).get("development_objects_may_mount") is not False:
            raise FreezeError(f"development exclusion mismatch for block {index}")

        record_path = SOURCE_ROOT / run_id / "research_records/formal_source_block_run.json"
        record = read_json(record_path)
        if record.get("study_kind") != "formal_source_v1" or record.get("included_in_primary_analysis") is not True or record.get("status") != "COMPLETED":
            raise FreezeError(f"formal source run record is ineligible/incomplete: {run_id}")
        record_episodes = record.get("episodes")
        if not isinstance(record_episodes, list) or len(record_episodes) != 4:
            raise FreezeError(f"formal source run must contain four episodes: {run_id}")
        for row, position, token in zip(record_episodes, expected_block["manifest_positions"], expected_block["expected_tokens"], strict=True):
            task_token, condition = token.split("-")
            expected_task = str(int(task_token.removeprefix("t")))
            if row.get("manifest_position") != position or str(row.get("task_id")) != expected_task or row.get("condition") != condition:
                raise FreezeError(f"record/manifest mismatch at position {position}")
            if row.get("episode_id") != f"formal-{token.lower()}":
                raise FreezeError(f"episode identity mismatch at position {position}")
            copied = dict(row)
            copied["run_id"] = run_id
            copied["run_record_path"] = relative(record_path)
            copied["authorization_path"] = relative(authorization_path)
            copied["runner_entry_path"] = entry["path"]
            copied["runner_entry_hash"] = entry["sha256"]
            copied["runner_version"] = "V1" if index == 1 else "V2" if index <= 6 else "V3"
            copied["block_id"] = expected_block["id"]
            copied["provider_transcript_path"] = relative(record_path.parent / "provider_transcripts.jsonl")
            snapshot_hash = copied.get("snapshot_hash")
            snapshot_files = copied.get("snapshot_files")
            if not isinstance(snapshot_hash, str) or not isinstance(snapshot_files, list):
                raise FreezeError(f"snapshot fields missing at position {position}")
            snapshot_path, snapshot_id = snapshot_directory(run_id, snapshot_hash, snapshot_files)
            copied["output_snapshot_id"] = snapshot_id
            copied["output_snapshot_path"] = relative(snapshot_path)
            copied["output_snapshot_hash_verified"] = hash_tree(snapshot_path)[0]
            raw_info = copied.get("raw_experience")
            if not isinstance(raw_info, dict):
                raise FreezeError(f"RAW reference missing at position {position}")
            raw_path = must_within(Path(str(raw_info.get("path", ""))), SOURCE_ROOT / run_id, "RAW path")
            if not raw_path.is_file() or sha256_file(raw_path) != raw_info.get("sha256"):
                raise FreezeError(f"RAW hash mismatch at position {position}")
            assert_raw_schema(read_json(raw_path), copied)
            copied["raw_trajectory_path"] = relative(raw_path)
            copied["raw_trajectory_hash"] = raw_info["sha256"]
            if copied.get("contamination_checks", {}).get("development_source_mounted") is not False:
                raise FreezeError(f"development contamination check failed at position {position}")
            if copied.get("contamination_checks", {}).get("evaluator_reference_visible") is not False:
                raise FreezeError(f"evaluator visibility check failed at position {position}")
            if copied.get("leakage_checks", {}).get("reference_or_evaluator_feedback_visible_to_agent") is not False:
                raise FreezeError(f"leakage check failed at position {position}")
            episodes.append(copied)
        run_metadata.append({
            "block_number": index,
            "block_id": expected_block["id"],
            "run_id": run_id,
            "run_record_path": relative(record_path),
            "run_record_sha256": sha256_file(record_path),
            "authorization_path": relative(authorization_path),
            "authorization_sha256": sha256_file(authorization_path),
            "runner_version": "V1" if index == 1 else "V2" if index <= 6 else "V3",
            "runner_entry_path": entry["path"],
            "runner_entry_hash": entry["sha256"],
            "provider_attempts": record.get("provider_attempts"),
            "provider_responses": record.get("provider_responses"),
            "known_cost_estimate": record.get("known_cost_estimate"),
            "status": record.get("status"),
        })

    episodes.sort(key=lambda row: int(row["manifest_position"]))
    if [row["manifest_position"] for row in episodes] != list(range(1, 33)):
        raise FreezeError("source manifest positions are not exactly 1..32")
    observed_tokens = [source_token(str(row["task_id"]), row["condition"]) for row in episodes]
    if observed_tokens != source["execution_order"]:
        raise FreezeError("source execution order differs from frozen manifest")
    for task_id in SOURCE_TASKS:
        found = {row["condition"] for row in episodes if int(row["task_id"]) == task_id}
        if found != set(CONDITIONS):
            raise FreezeError(f"source condition matrix incomplete for task {task_id}")

    # Verify direct same-condition cumulative lineage and byte continuity.
    by_token = {source_token(str(row["task_id"]), row["condition"]): row for row in episodes}
    for condition in ("F1", "U1"):
        for task_id in range(8, 15):
            previous = by_token[f"t{task_id - 1:02d}-{condition}"]
            current = by_token[f"t{task_id:02d}-{condition}"]
            if current.get("input_snapshot_hash") != previous["output_snapshot_id"] or current.get("inheritance_source") != previous["output_snapshot_id"]:
                raise FreezeError(f"immediate cumulative lineage mismatch at t{task_id:02d}-{condition}")
            # V3 CASE B records a resource-limited inherited-memory episode
            # without a new artifact.  It can contain a runner-local byte copy
            # for audit, while the logical output identity remains the direct
            # predecessor snapshot used by the next authorized block.
            if not current.get("artifact_paths"):
                if current["snapshot_hash"] != previous["snapshot_hash"] or current["snapshot_files"] != previous["snapshot_files"]:
                    raise FreezeError(f"unexpected no-new-artifact continuity at t{task_id:02d}-{condition}")
                current["output_snapshot_id"] = previous["output_snapshot_id"]
                current["output_snapshot_path"] = previous["output_snapshot_path"]
                current["output_snapshot_hash_verified"] = previous["output_snapshot_hash_verified"]
                current["no_new_artifact_continuity"] = True
            previous_root = ROOT / previous["output_snapshot_path"]
            current_root = ROOT / current["output_snapshot_path"]
            for name in previous["snapshot_files"]:
                before, after = previous_root / name, current_root / name
                if not after.is_file() or sha256_file(before) != sha256_file(after):
                    raise FreezeError(f"inherited file changed at t{task_id:02d}-{condition}: {name}")
    return source, blocks, receiver, episodes, run_metadata


def master_row(episode: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "manifest_position", "task_id", "condition", "episode_id", "run_id", "block_id",
        "runner_version", "runner_entry_path", "runner_entry_hash", "started", "native_answer_submitted",
        "correct", "native_accuracy", "native_score", "analysis_score", "analysis_status", "main_stop_reason",
        "sql_queries", "main_model_decisions", "provider_attempts", "provider_responses", "transport_retries",
        "prompt_tokens", "completion_tokens", "reasoning_tokens", "estimated_cost", "billing_unknown",
        "consolidation_executed", "consolidation", "artifact_paths", "artifact_provenance", "input_snapshot_hash",
        "inheritance_source", "output_snapshot_id", "output_snapshot_hash_verified", "output_snapshot_path",
        "snapshot_hash", "snapshot_files", "raw_trajectory_path", "raw_trajectory_hash", "contamination_checks",
        "leakage_checks", "native_evaluator_ran", "provider_transcript_path", "exception_chain",
    )
    return {key: episode.get(key) for key in keys}


def condition_summary(episodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for condition in CONDITIONS:
        rows = [row for row in episodes if row["condition"] == condition]
        answer_rows = [row for row in rows if row.get("native_answer_submitted") is True]
        correct_rows = [row for row in rows if row.get("correct") == 1]
        score_rows = [Decimal(str(row["native_score"])) for row in rows if row.get("native_score") is not None]
        artifact_count = sum(len(row.get("artifact_paths", [])) for row in rows)
        result[condition] = {
            "episode_count": len(rows),
            "native_answer_count": len(answer_rows),
            "correct_count": len(correct_rows),
            "mean_native_score": float(sum(score_rows) / len(score_rows)) if score_rows else None,
            "mean_native_score_denominator": len(score_rows),
            "mean_native_score_missing_semantics": "only recorded native_score values; missing native evaluator results are excluded, not imputed as zero",
            "resource_limited_count": sum(row.get("analysis_status") == "RESOURCE_LIMITED_FAILURE" for row in rows),
            "artifact_count": artifact_count,
            "provider_attempts": sum(int(row.get("provider_attempts", 0)) for row in rows),
            "provider_responses": sum(int(row.get("provider_responses", 0)) for row in rows),
            "prompt_tokens": sum(int(row.get("prompt_tokens", 0)) for row in rows),
            "completion_tokens": sum(int(row.get("completion_tokens", 0)) for row in rows),
            "reasoning_tokens": sum(int(row.get("reasoning_tokens", 0)) for row in rows),
            "estimated_total_cost": str(sum((Decimal(str(row.get("estimated_cost", "0"))) for row in rows), Decimal("0"))),
        }
    return result


def materialize_memory(resource_id: str, episode: dict[str, Any], condition: str) -> dict[str, Any]:
    if episode["condition"] != condition or int(episode["task_id"]) != 14 or episode["episode_id"] != f"formal-t14-{condition.lower()}":
        raise FreezeError(f"{resource_id} source episode identity is invalid")
    if episode.get("analysis_status") != "EVALUATED_NATIVE":
        raise FreezeError(f"{resource_id} final source was not a completed native-evaluated episode")
    source_root = ROOT / episode["output_snapshot_path"]
    destination = RESOURCE_ROOT / resource_id
    destination.mkdir(parents=True, exist_ok=False)
    files: list[dict[str, Any]] = []
    for source in regular_files(source_root):
        name = source.relative_to(source_root)
        target = destination / name
        copy_file(source, target)
        source_hash, materialized_hash = sha256_file(source), sha256_file(target)
        if source_hash != materialized_hash:
            raise FreezeError(f"{resource_id} byte mismatch after copy: {name}")
        files.append({
            "relative_path": name.as_posix(), "byte_size": source.stat().st_size,
            "source_sha256": source_hash, "materialized_sha256": materialized_hash, "equality_verified": True,
        })
    tree_hash, tree_files = hash_tree(destination)
    if tree_hash != episode["snapshot_hash"] or tree_files != episode["snapshot_files"]:
        raise FreezeError(f"{resource_id} materialized tree differs from formal source snapshot")
    return {
        "resource_id": resource_id, "resource_kind": "cumulative_memory_snapshot", "source_conditions": [condition],
        "source_tasks": list(range(7, 15)), "source_run_ids": [episode["run_id"]], "source_episode_ids": [episode["episode_id"]],
        "source_snapshot_id": episode["output_snapshot_id"], "source_snapshot_hash": episode["snapshot_hash"],
        "source_snapshot_path": episode["output_snapshot_path"], "materialized_path": relative(destination), "file_list": files,
        "total_bytes": sum(item["byte_size"] for item in files), "resource_tree_sha256": tree_hash,
        "construction_rule": f"byte-for-byte copy of final task-14 {condition} frozen /memory snapshot; no rewrite, merge, deletion, or renumbering",
        "construction_version": "formal_receiver_resource_materialization_v1", "immutable": True, "agent_mountable": False,
        "contains_evaluator_feedback": False, "contains_reference_answer": False, "contains_reference_sql": False,
        "contains_development_data": False, "contains_consolidation_output": True, "contains_raw_trajectory": False,
        "source_lineage_verified": True, "contamination_checks": {"development_source_mounted": False, "evaluator_reference_visible": False, "reference_or_evaluator_feedback_visible_to_agent": False},
    }


def materialize_raw(resource_id: str, condition: str, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted((row for row in episodes if row["condition"] == condition), key=lambda row: int(row["task_id"]))
    if [int(row["task_id"]) for row in rows] != list(SOURCE_TASKS):
        raise FreezeError(f"{resource_id} does not have exactly the 8 required source tasks")
    destination = RESOURCE_ROOT / resource_id
    destination.mkdir(parents=True, exist_ok=False)
    payloads: list[bytes] = []
    components: list[dict[str, Any]] = []
    for row in rows:
        source = ROOT / row["raw_trajectory_path"]
        payload = source.read_bytes()
        if sha256_bytes(payload) != row["raw_trajectory_hash"]:
            raise FreezeError(f"{resource_id} source RAW changed before materialization: {source}")
        payloads.append(payload)
        components.append({
            "task_id": int(row["task_id"]), "source_run_id": row["run_id"], "source_episode_id": row["episode_id"],
            "source_path": row["raw_trajectory_path"], "source_sha256": row["raw_trajectory_hash"], "byte_size": len(payload),
        })
    # Frozen source manifest explicitly defines exact UTF-8 source payloads with one LF delimiter.
    aggregate = b"\n".join(payloads)
    filename = "raw_f.txt" if resource_id == "RAW_F" else "raw_u.txt"
    target = destination / filename
    target.write_bytes(aggregate)
    materialized_hash = sha256_file(target)
    expected_hash = sha256_bytes(aggregate)
    if materialized_hash != expected_hash:
        raise FreezeError(f"{resource_id} aggregate payload hash mismatch")
    tree_hash, tree_files = hash_tree(destination)
    return {
        "resource_id": resource_id, "resource_kind": "pre_consolidation_raw_aggregate", "source_conditions": [condition],
        "source_tasks": list(SOURCE_TASKS), "source_run_ids": [row["run_id"] for row in rows],
        "source_episode_ids": [row["episode_id"] for row in rows], "source_snapshot_id": None, "source_snapshot_hash": None,
        "materialized_path": relative(destination), "file_list": [{"relative_path": filename, "byte_size": len(aggregate), "materialized_sha256": materialized_hash}],
        "component_lineage": components, "total_bytes": len(aggregate), "aggregate_payload_sha256": materialized_hash,
        "resource_tree_sha256": tree_hash, "construction_rule": "exact UTF-8 serialized RAW_source_episode payload bytes in source task order 7..14, separated by one LF and with no added headers or researcher metadata",
        "construction_version": "formal_receiver_resource_materialization_v1", "immutable": True, "agent_mountable": False,
        "contains_evaluator_feedback": False, "contains_reference_answer": False, "contains_reference_sql": False,
        "contains_development_data": False, "contains_consolidation_output": False, "contains_raw_trajectory": True,
        "source_lineage_verified": True, "contamination_checks": {"development_source_mounted": False, "evaluator_reference_visible": False, "raw_schema_exact": True},
        "receiver_frozen_mount_path": f"/memory/{filename}", "tree_files": tree_files,
    }


def make_report(*, master_hash: str, master_csv_hash: str, resources: dict[str, dict[str, Any]], manifest_hash: str, seal_hash: str, episodes: list[dict[str, Any]], run_metadata: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    def listed(resource: dict[str, Any]) -> str:
        if not resource["file_list"]:
            return "(zero files)"
        return "\n".join(f"- `{item['relative_path']}` — `{item.get('materialized_sha256')}`" for item in resource["file_list"])
    runs = "\n".join(f"- Block {row['block_number']} ({row['runner_version']}): `{row['run_id']}`" for row in run_metadata)
    validations = [
        "32/32 source episodes found; manifest positions are exactly 1–32 with no duplication.",
        "Every task 7–14 contains F0, U0, F1, and U1; IDs 1–6 are excluded.",
        "M_F and M_U each resolve uniquely to their task-14 same-condition final snapshot and match it byte-for-byte.",
        "M_U contains no fabricated `experience_006.md`; its retained filename gap is preserved.",
        "RAW_F and RAW_U each contain exactly eight source RAW payloads in source-task order, with the frozen single-LF serialization rule.",
        "RAW payload schemas contain no consolidation output, evaluator output, reference answer, reference SQL, or researcher logs.",
        "All M/RAW provenance checks report no development mounting and no evaluator/reference visibility.",
        "Resource hashes and the source seal canonical binding were recomputed in-process after writing.",
        "No formal probe task content was opened or executed; only receiver-manifest schema/resource labels were checked.",
        "This materialization invoked 0 provider requests and 0 evaluator calls.",
    ]
    summary_rows = "\n".join(
        f"| {condition} | {row['episode_count']} | {row['native_answer_count']} | {row['correct_count']} | {row['mean_native_score']} (n={row['mean_native_score_denominator']}) | {row['resource_limited_count']} | {row['artifact_count']} | {row['provider_attempts']} | {row['prompt_tokens']}/{row['completion_tokens']}/{row['reasoning_tokens']} | {row['estimated_total_cost']} |"
        for condition, row in summary.items()
    )
    return f"""# Formal Source Freeze and Receiver Materialization V1

## Completion

The formal source phase is sealed with 32 completed source episodes (tasks 7–14 × F0/U0/F1/U1). Receiver execution has not started.

## Completed formal blocks

{runs}

Runner lineage is V1 for Block 1, V2 for Blocks 2–6, and V3 for Blocks 7–8. Every record was cross-checked against the consumed authorization, frozen source-manifest hash, formal-protocol hash, block-definition hash, frozen pending-config hash, and historical runner entry hash.

## Source master record

- `FORMAL_SOURCE_MASTER_V1.json`: `{master_hash}`
- `FORMAL_SOURCE_MASTER_V1.csv`: `{master_csv_hash}`

The master table is sorted by frozen manifest position and retains missing native outcomes as recorded (no missing evaluator result was imputed as zero).

## Descriptive condition summary

Native-score mean denominator is only episodes with an explicitly recorded `native_score`; missing native evaluator outcomes are excluded rather than imputed.

| Condition | Episodes | Native ANSWER | Correct | Mean native score | Resource-limited | Artifacts | Provider attempts | Prompt/completion/reasoning tokens | Estimated cost |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: |
{summary_rows}

## M_F

Source: `{resources['M_F']['source_episode_ids'][0]}` from `{resources['M_F']['source_run_ids'][0]}`, snapshot `{resources['M_F']['source_snapshot_id']}` / `{resources['M_F']['source_snapshot_hash']}`.

{listed(resources['M_F'])}

## M_U

Source: `{resources['M_U']['source_episode_ids'][0]}` from `{resources['M_U']['source_run_ids'][0]}`, snapshot `{resources['M_U']['source_snapshot_id']}` / `{resources['M_U']['source_snapshot_hash']}`.

{listed(resources['M_U'])}

The U1 continuity case at task 12 is preserved: no `experience_006.md` exists in M_U, while `experience_007.md` and `experience_008.md` retain their original names.

## RAW_F and RAW_U

RAW_F is the frozen concatenation of all eight F0 pre-consolidation RAW source payloads (tasks 7→14); RAW_U is the equivalent U0 set. The protocol-specified representation is one aggregate file per resource, with original UTF-8 payload bytes separated by a single LF and no added headers.

- RAW_F payload hash: `{resources['RAW_F']['aggregate_payload_sha256']}`
- RAW_U payload hash: `{resources['RAW_U']['aggregate_payload_sha256']}`

## Exclusions and integrity

No resource contains development IDs 1–6, calibration/viability material, cross-condition artifacts, evaluator feedback, reference answers, reference SQL, or probe data. M resources contain consolidation output only; RAW resources contain pre-consolidation trajectories only.

## Receiver resources and seal

- Receiver resource manifest canonical hash: `{manifest_hash}`
- Source phase seal canonical hash: `{seal_hash}`
- EMPTY is defined as the zero-file, zero-content baseline and has no materialized helper content.
- `receiver_started = false`

## Offline validation

{chr(10).join(f'- PASS — {item}' for item in validations)}

## Unresolved ambiguity

None. The frozen source manifest explicitly specified RAW aggregation and receiver mount names; the construction introduced no scientific-content selection difference.
"""


def main() -> None:
    if FREEZE_ROOT.exists() or RESOURCE_ROOT.exists():
        raise FreezeError("freeze output already exists; refusing to overwrite an immutable materialization")
    source, blocks, receiver, episodes, run_metadata = validate_historical_inputs()
    FREEZE_ROOT.mkdir(parents=True, exist_ok=False)
    RESOURCE_ROOT.mkdir(parents=True, exist_ok=False)
    try:
        master_rows = [master_row(row) for row in episodes]
        master = {
            "format": "FORMAL_SOURCE_MASTER_V1", "immutable": True,
            "construction_version": "formal_receiver_resource_materialization_v1",
            "source_manifest_path": "FORMAL_SOURCE_MANIFEST_V1.json", "source_manifest_sha256": sha256_file(ROOT / "FORMAL_SOURCE_MANIFEST_V1.json"),
            "formal_protocol_path": "FORMAL_EXPERIMENT_PROTOCOL_V1.md", "formal_protocol_sha256": sha256_file(ROOT / "FORMAL_EXPERIMENT_PROTOCOL_V1.md"),
            "source_block_definition_path": "FORMAL_SOURCE_BLOCKS_V1.json", "source_block_definition_sha256": sha256_file(ROOT / "FORMAL_SOURCE_BLOCKS_V1.json"),
            "run_lineage": run_metadata, "episodes": master_rows, "condition_summary": condition_summary(episodes),
            "this_materialization_provider_requests": 0, "this_materialization_evaluator_calls": 0,
            "probe_content_read": False, "receiver_started": False,
        }
        master_path = FREEZE_ROOT / "FORMAL_SOURCE_MASTER_V1.json"
        master_path.write_bytes(json.dumps(master, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        csv_path = FREEZE_ROOT / "FORMAL_SOURCE_MASTER_V1.csv"
        fieldnames = list(master_rows[0])
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for row in master_rows:
                writer.writerow({key: serializable(value) if isinstance(value, (dict, list)) else value for key, value in row.items()})
        master_hash, master_csv_hash = sha256_file(master_path), sha256_file(csv_path)

        by_token = {source_token(str(row["task_id"]), row["condition"]): row for row in episodes}
        resources = {
            "EMPTY": {
                "resource_id": "EMPTY", "resource_kind": "empty_baseline", "source_conditions": [], "source_tasks": [], "source_run_ids": [], "source_episode_ids": [],
                "source_snapshot_id": None, "source_snapshot_hash": None, "materialized_path": None, "file_list": [], "total_bytes": 0,
                "resource_tree_sha256": sha256_bytes(b""), "construction_rule": "fresh empty immutable memory baseline; no helper content", "construction_version": "formal_receiver_resource_materialization_v1",
                "immutable": True, "agent_mountable": False, "contains_evaluator_feedback": False, "contains_reference_answer": False, "contains_reference_sql": False,
                "contains_development_data": False, "contains_consolidation_output": False, "contains_raw_trajectory": False, "source_lineage_verified": True,
            },
            "M_F": materialize_memory("M_F", by_token["t14-F1"], "F1"),
            "M_U": materialize_memory("M_U", by_token["t14-U1"], "U1"),
            "RAW_F": materialize_raw("RAW_F", "F0", episodes),
            "RAW_U": materialize_raw("RAW_U", "U0", episodes),
        }
        if any(item["relative_path"] == "experience_006.md" for item in resources["M_U"]["file_list"]):
            raise FreezeError("M_U incorrectly contains experience_006.md")

        manifest = {
            "format": "FORMAL_RECEIVER_RESOURCES_V1", "immutable": True, "construction_version": "formal_receiver_resource_materialization_v1",
            "source_manifest_sha256": sha256_file(ROOT / "FORMAL_SOURCE_MANIFEST_V1.json"),
            "receiver_manifest_schema_sha256": sha256_file(ROOT / "FORMAL_RECEIVER_MANIFEST_V1.json"),
            "receiver_resource_order": ["EMPTY", "M_F", "M_U", "RAW_F", "RAW_U"], "resources": resources,
            "agent_mountable_for_now": False, "receiver_started": False, "this_materialization_provider_requests": 0, "this_materialization_evaluator_calls": 0,
            "scientific_content_selection_diff": "NONE", "probe_content_read": False,
        }
        manifest["canonical_content_sha256"] = sha256_bytes(canonical_bytes(manifest))
        manifest_path = RESOURCE_ROOT / "FORMAL_RECEIVER_RESOURCES_V1.json"
        manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        manifest_file_hash = sha256_file(manifest_path)

        seal = {
            "format": "FORMAL_SOURCE_PHASE_SEAL_V1", "creation_timestamp": datetime.now(timezone.utc).isoformat(),
            "formal_protocol_hash": sha256_file(ROOT / "FORMAL_EXPERIMENT_PROTOCOL_V1.md"),
            "source_manifest_hash": sha256_file(ROOT / "FORMAL_SOURCE_MANIFEST_V1.json"),
            "source_block_definition_hash": sha256_file(ROOT / "FORMAL_SOURCE_BLOCKS_V1.json"),
            "source_master_table_hash": master_hash, "source_master_csv_hash": master_csv_hash,
            "completed_run_ids": list(RUN_IDS), "source_episode_identities": [row["episode_id"] for row in episodes],
            "runner_hashes": {"V1": run_metadata[0]["runner_entry_hash"], "V2": run_metadata[1]["runner_entry_hash"], "V3": run_metadata[6]["runner_entry_hash"]},
            "resource_tree_hashes": {name: value["resource_tree_sha256"] for name, value in resources.items()},
            "raw_payload_hashes": {name: resources[name].get("aggregate_payload_sha256") for name in ("RAW_F", "RAW_U")},
            "receiver_resource_manifest_canonical_hash": manifest["canonical_content_sha256"], "receiver_resource_manifest_file_hash": manifest_file_hash,
            "source_complete": True, "source_episode_count": 32, "next_source_position": None, "receiver_started": False,
            "this_materialization_provider_requests": 0, "this_materialization_evaluator_calls": 0, "probe_content_read": False,
        }
        seal["canonical_content_sha256"] = sha256_bytes(canonical_bytes(seal))
        if seal["canonical_content_sha256"] != sha256_bytes(canonical_bytes({key: value for key, value in seal.items() if key != "canonical_content_sha256"})):
            raise FreezeError("source seal cannot be reproduced")
        seal_path = FREEZE_ROOT / "FORMAL_SOURCE_PHASE_SEAL_V1.json"
        seal_path.write_bytes(json.dumps(seal, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")

        report = make_report(
            master_hash=master_hash, master_csv_hash=master_csv_hash, resources=resources,
            manifest_hash=manifest["canonical_content_sha256"], seal_hash=seal["canonical_content_sha256"],
            episodes=episodes, run_metadata=run_metadata, summary=master["condition_summary"],
        )
        report_path = FREEZE_ROOT / "FORMAL_SOURCE_FREEZE_AND_RECEIVER_MATERIALIZATION_V1.md"
        report_path.write_text(report, encoding="utf-8")

        # Recompute payload/tree hashes from the materialized files before sealing permissions.
        for name in ("M_F", "M_U", "RAW_F", "RAW_U"):
            root = RESOURCE_ROOT / name
            if hash_tree(root)[0] != resources[name]["resource_tree_sha256"]:
                raise FreezeError(f"non-deterministic resource tree hash after materialization: {name}")
        if sha256_bytes(canonical_bytes({key: value for key, value in seal.items() if key != "canonical_content_sha256"})) != seal["canonical_content_sha256"]:
            raise FreezeError("source seal canonical recheck failed")
        immutable_tree(FREEZE_ROOT)
        immutable_tree(RESOURCE_ROOT)
    except Exception:
        # New output only: leave the evidence for diagnosis rather than risk deleting data.
        raise


if __name__ == "__main__":
    main()
