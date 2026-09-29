"""Formal-source runner V3: strict resolver for no-new-artifact lineage.

V3 delegates the verified provider loop to V2.  Its only semantic extension is
a pre-provider resolver for a valid immediate predecessor which produced no
new experience file but retained inherited agent-visible /memory unchanged.
V1 and V2 remain untouched, preserving their historical formal bindings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llm.adapters import ProviderAdapter

from . import formal_source_run_v2 as v2
from .public_viability_gate_run import _code_hashes
from .records import AuthorizationError
from .workspace import Snapshot, hash_tree

ROOT = Path(__file__).resolve().parents[2]
V3_PENDING_STATUS = "PENDING_FORMAL_SOURCE_BLOCK_V3_USER_SIGNOFF_NO_LIVE_CALLS"
V3_ENTRY_PATH = "experiments/experience_value/formal_source_run_v3.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorizationError(f"unreadable formal provenance: {path}") from exc
    if not isinstance(value, dict):
        raise AuthorizationError("formal provenance must be a JSON object")
    return value


def _run_root(run_id: object) -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(r"e0-[0-9a-f]{32}", run_id):
        raise AuthorizationError("invalid formal predecessor run identity")
    return v2._within(v2.FORMAL_RUNS_ROOT / run_id, v2.FORMAL_RUNS_ROOT)


def _root_relative(path_value: object, root: Path) -> Path:
    if not isinstance(path_value, str):
        raise AuthorizationError("formal provenance path is missing")
    return v2._within(ROOT / path_value, root)


def _snapshot_root(storage_run_id: object, snapshot_id: object) -> Path:
    if not isinstance(snapshot_id, str) or not re.fullmatch(r"snapshot-[0-9a-f]{32}", snapshot_id):
        raise AuthorizationError("invalid formal snapshot identity")
    run_root = _run_root(storage_run_id)
    path = v2._within(run_root / "frozen_snapshots" / snapshot_id, run_root / "frozen_snapshots")
    if not path.is_dir():
        raise AuthorizationError("required frozen snapshot is missing")
    return path


def _episode(record: dict[str, Any], episode_id: str) -> dict[str, Any]:
    value = next((row for row in record.get("episodes", []) if row.get("episode_id") == episode_id), None)
    if not isinstance(value, dict):
        raise AuthorizationError("required formal episode record is missing")
    return value


def _verify_formal_record_and_authorization(*, run_id: str, record_path: Path, authorization_path: Path, pending: dict[str, Any]) -> dict[str, Any]:
    record, authorization = _json(record_path), _json(authorization_path)
    if record.get("study_kind") != "formal_source_v1" or record.get("included_in_primary_analysis") is not True:
        raise AuthorizationError("predecessor record is not a formal primary-analysis source")
    if authorization.get("study_kind") != "formal_source_v1" or authorization.get("included_in_primary_analysis") is not True:
        raise AuthorizationError("predecessor authorization is not formal primary-analysis scope")
    if authorization.get("consumption_run_id") != run_id:
        raise AuthorizationError("predecessor authorization is not bound to its formal run")
    if authorization.get("formal_protocol", {}).get("sha256") != pending["formal_protocol"]["sha256"]:
        raise AuthorizationError("predecessor formal protocol lineage differs")
    if authorization.get("source_manifest", {}).get("sha256") != pending["source_manifest"]["sha256"]:
        raise AuthorizationError("predecessor source manifest lineage differs")
    return record


def _verify_common_case_b_lineage(reference: dict[str, Any], item: dict[str, Any], pending: dict[str, Any]) -> dict[str, Any]:
    source = _json(ROOT / pending["source_manifest"]["path"])
    required = v2._required_predecessor(item, source)
    if required is None:
        raise AuthorizationError("empty-memory formal condition supplied a predecessor")
    expected_token, expected_episode = required
    if reference.get("predecessor_token") != expected_token or reference.get("episode_id") != expected_episode:
        raise AuthorizationError("CASE B predecessor is not immediate and same-condition")
    if reference.get("condition") != item["condition"] or int(reference.get("task_id", -1)) != int(item["task_id"]) - 1:
        raise AuthorizationError("CASE B predecessor task or condition differs")
    if reference.get("study_kind") != "formal_source_v1" or reference.get("included_in_primary_analysis") is not True:
        raise AuthorizationError("CASE B predecessor is not a formal source")
    if reference.get("formal_protocol_sha256") != pending["formal_protocol"]["sha256"] or reference.get("source_manifest_sha256") != pending["source_manifest"]["sha256"]:
        raise AuthorizationError("CASE B formal lineage differs")
    run_id = str(reference.get("run_id", ""))
    run_root = _run_root(run_id)
    record_path = _root_relative(reference.get("record_path"), run_root)
    auth_path = _root_relative(reference.get("authorization_path"), ROOT / "experiments/experience_value")
    if not record_path.is_file() or not auth_path.is_file():
        raise AuthorizationError("CASE B run record or authorization is missing")
    record = _verify_formal_record_and_authorization(run_id=run_id, record_path=record_path, authorization_path=auth_path, pending=pending)
    episode = _episode(record, expected_episode)
    if episode.get("condition") != item["condition"] or str(episode.get("task_id")) != str(int(item["task_id"]) - 1):
        raise AuthorizationError("CASE B episode record task/condition differs")
    checks, leakage = episode.get("contamination_checks", {}), episode.get("leakage_checks", {})
    if checks.get("development_source_mounted") is not False or checks.get("evaluator_reference_visible") is not False:
        raise AuthorizationError("CASE B contamination check failed")
    if leakage and leakage.get("reference_or_evaluator_feedback_visible_to_agent") is not False:
        raise AuthorizationError("CASE B evaluator/reference feedback was visible")
    if episode.get("artifact_provenance") or episode.get("artifact_paths"):
        raise AuthorizationError("CASE B must not contain new artifact provenance")
    return episode


def _verify_snapshot_identity(*, root: Path, expected_hash: object, expected_files: object | None = None) -> tuple[str, tuple[str, ...]]:
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise AuthorizationError("snapshot hash is invalid")
    actual_hash, files = hash_tree(root)
    if actual_hash != expected_hash:
        raise AuthorizationError("frozen snapshot hash differs")
    if expected_files is not None and tuple(expected_files) != files:
        raise AuthorizationError("frozen snapshot file set differs from record")
    return actual_hash, files


def _assert_memory_continuity(input_root: Path, output_root: Path) -> tuple[str, ...]:
    """Require an immutable, byte-identical /memory tree for CASE B."""
    _input_hash, input_files = hash_tree(input_root)
    _output_hash, output_files = hash_tree(output_root)
    if input_files != output_files:
        raise AuthorizationError("CASE B changed the inherited /memory path set")
    for relative in input_files:
        before, after = input_root / relative, output_root / relative
        if before.stat().st_size != after.stat().st_size or sha(before) != sha(after):
            raise AuthorizationError("CASE B changed inherited /memory bytes")
        if before.stat().st_mode & stat.S_IWUSR or after.stat().st_mode & stat.S_IWUSR:
            raise AuthorizationError("CASE B inherited snapshot is not immutable")
    return input_files


def _case_b(reference: dict[str, Any], item: dict[str, Any], pending: dict[str, Any]) -> Snapshot:
    """Resolve CASE B only if inherited agent-visible memory is unchanged.

    Resource termination can retain the physical snapshot from the episode's
    parent.  The predecessor *record* run and snapshot *storage* run are thus
    separate, explicit runner-only identities.
    """
    episode = _verify_common_case_b_lineage(reference, item, pending)
    input_id, input_hash = reference.get("input_snapshot_id"), reference.get("input_snapshot_hash")
    output_id, output_hash = reference.get("snapshot_id"), reference.get("snapshot_hash")
    if episode.get("input_snapshot_hash") != input_id or episode.get("snapshot_hash") != output_hash:
        raise AuthorizationError("CASE B input/output identity differs from formal episode record")
    if tuple(episode.get("snapshot_files", [])) != tuple(reference.get("snapshot_files", [])):
        raise AuthorizationError("CASE B output file set differs from signed reference")
    input_root = _snapshot_root(reference.get("input_snapshot_storage_run_id"), input_id)
    output_root = _snapshot_root(reference.get("snapshot_storage_run_id"), output_id)
    _input_tree, input_files = _verify_snapshot_identity(root=input_root, expected_hash=input_hash)
    output_tree, output_files = _verify_snapshot_identity(root=output_root, expected_hash=output_hash, expected_files=reference.get("snapshot_files"))
    _assert_memory_continuity(input_root, output_root)

    origin_run_id = str(reference.get("input_snapshot_storage_run_id", ""))
    origin_root = _run_root(origin_run_id)
    origin_record_path = _root_relative(reference.get("input_snapshot_record_path"), origin_root)
    origin_auth_path = _root_relative(reference.get("input_snapshot_authorization_path"), ROOT / "experiments/experience_value")
    origin_record = _verify_formal_record_and_authorization(run_id=origin_run_id, record_path=origin_record_path, authorization_path=origin_auth_path, pending=pending)
    origin_episode_id = reference.get("input_snapshot_source_episode")
    if not isinstance(origin_episode_id, str):
        raise AuthorizationError("CASE B input snapshot source episode is missing")
    origin_episode = _episode(origin_record, origin_episode_id)
    if origin_episode.get("condition") != item["condition"] or origin_episode.get("snapshot_hash") != input_hash:
        raise AuthorizationError("CASE B input snapshot origin differs")
    if tuple(origin_episode.get("snapshot_files", [])) != input_files:
        raise AuthorizationError("CASE B input snapshot origin file set differs")
    return Snapshot(str(output_id), output_root, output_tree, None, episode.get("attempt_id"), output_files)


_ORIGINAL_PREDECESSOR = v2._load_predecessor


def _v3_predecessor(*, reference: dict[str, Any], item: dict[str, Any], pending: dict[str, Any]) -> Snapshot:
    case = reference.get("operational_case", "A")
    if case == "B":
        return _case_b(reference, item, pending)
    if case != "A":
        raise AuthorizationError("unknown formal predecessor operational case")
    return _ORIGINAL_PREDECESSOR(reference=reference, item=item, pending=pending)


def _consume_v3_after_dispatch(path: Path, events: list[dict[str, Any]], run_id: str, block_id: str) -> None:
    if not any(event.get("type") == "provider.request_started" for event in events):
        return
    payload = _json(path)
    if payload.get("real_model_requests_sent_under_this_authorization", 0):
        return
    payload.update(status=f"CONSUMED_{block_id.upper()}", real_model_requests_sent_under_this_authorization=1, consumption_run_id=run_id, consumed_at=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@contextmanager
def _v2_bridge(authorization_path: Path):
    """Inject V3 resolver and mirror first-dispatch consumption to V3 auth."""
    original_predecessor, original_consume = v2._load_predecessor, v2._consume_after_dispatch
    def mirrored_consume(temp_path: Path, events: list[dict[str, Any]], run_id: str, block_id: str) -> None:
        original_consume(temp_path, events, run_id, block_id)
        _consume_v3_after_dispatch(authorization_path, events, run_id, block_id)
    v2._load_predecessor, v2._consume_after_dispatch = _v3_predecessor, mirrored_consume
    try:
        yield
    finally:
        v2._load_predecessor, v2._consume_after_dispatch = original_predecessor, original_consume


def _validate_v3_authorization(pending_path: Path, authorization_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    pending, authorization = _json(pending_path), _json(authorization_path)
    if pending.get("status") != V3_PENDING_STATUS or pending.get("block_id") not in {"formal_source_block_07", "formal_source_block_08"}:
        raise AuthorizationError("V3 pending scope is invalid")
    if pending.get("study_kind") != "formal_source_v1" or pending.get("included_in_primary_analysis") is not True:
        raise AuthorizationError("V3 pending scientific scope is invalid")
    if authorization.get("entry_code") != {"path": V3_ENTRY_PATH, "sha256": sha(Path(__file__))}:
        raise AuthorizationError("V3 authorization does not bind this entry")
    if authorization.get("code_dependencies") != (_code_hashes() | {"entry": sha(Path(__file__))}):
        raise AuthorizationError("V3 authorization dependency binding differs")
    try:
        pending_relative = str(pending_path.resolve().relative_to(ROOT))
    except ValueError as exc:
        raise AuthorizationError("V3 pending must remain beneath the project root") from exc
    frozen = authorization.get("frozen_pending_config", {})
    if frozen.get("path") != pending_relative or frozen.get("sha256") != sha(pending_path):
        raise AuthorizationError("V3 authorization does not bind this pending configuration")
    if authorization.get("required_predecessors") != pending.get("predecessor_references", {}):
        raise AuthorizationError("V3 authorization predecessor binding differs")
    return pending, authorization


def _v2_compatible_documents(pending: dict[str, Any], authorization: dict[str, Any], compat_pending_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    cp, ca = json.loads(json.dumps(pending)), json.loads(json.dumps(authorization))
    cp["status"] = "PENDING_FORMAL_SOURCE_BLOCK_V2_USER_SIGNOFF_NO_LIVE_CALLS"
    ca["entry_code"] = {"path": "experiments/experience_value/formal_source_run_v2.py", "sha256": sha(ROOT / "experiments/experience_value/formal_source_run_v2.py")}
    ca["code_dependencies"] = _code_hashes() | {"entry": ca["entry_code"]["sha256"]}
    ca["frozen_pending_config"] = {"path": str(compat_pending_path.relative_to(ROOT)), "sha256": ""}
    return cp, ca


def execute(*, pending_path: Path, authorization_path: Path, output_root: Path, mode: str, adapter: ProviderAdapter | None = None, report_path: Path | None = None) -> Path:
    """Run V3 validation and the unchanged V2 provider/tool execution loop."""
    if mode not in {"plan-only", "fake", "live"}:
        raise ValueError("mode")
    pending, authorization = _validate_v3_authorization(pending_path, authorization_path)
    if mode == "live" and not (authorization.get("status") == f"AUTHORIZED_{pending['block_id'].upper()}" and authorization.get("live_requests_authorized") is True and authorization.get("real_model_requests_sent_under_this_authorization") == 0):
        raise AuthorizationError("formal V3 live run requires an independent unused authorization")
    with tempfile.TemporaryDirectory(prefix="formal-source-v3-", dir=ROOT / "artifacts/experience_value") as raw_temp:
        temp = Path(raw_temp)
        compat_pending_path, compat_authorization_path = temp / "pending.json", temp / "authorization.json"
        compat_pending, compat_authorization = _v2_compatible_documents(pending, authorization, compat_pending_path)
        compat_pending_path.write_text(json.dumps(compat_pending, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        compat_authorization["frozen_pending_config"]["sha256"] = sha(compat_pending_path)
        compat_authorization_path.write_text(json.dumps(compat_authorization, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with _v2_bridge(authorization_path):
            return v2.execute(pending_path=compat_pending_path, authorization_path=compat_authorization_path, output_root=output_root, mode=mode, adapter=adapter, report_path=report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manifest-driven formal source runner V3")
    parser.add_argument("--pending", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experience_value/formal_source"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--fake", action="store_true")
    mode.add_argument("--live", action="store_true")
    args = parser.parse_args()
    selected = "plan-only" if args.plan_only else "fake" if args.fake else "live"
    print(execute(pending_path=args.pending, authorization_path=args.authorization, output_root=args.output_root, mode=selected))


if __name__ == "__main__":
    main()
