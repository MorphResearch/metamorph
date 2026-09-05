"""Configuration-driven AppWorld E1/E2 experiment runner."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from .appworld_adapter import AppWorldController, PhaseModel, _hash_directory, official_metrics
from .appworld_budget import BudgetLimits


WorldFactory = Callable[..., Any]


def sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def git_dirty(path: Path) -> bool:
    return bool(subprocess.check_output(["git", "-C", str(path), "status", "--porcelain"], text=True).strip())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def validate_task_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != "appworld.task-manifest.v1":
        raise ValueError("unsupported AppWorld task manifest schema")
    task_ids = manifest.get("task_ids")
    if not isinstance(task_ids, list) or not task_ids:
        raise ValueError("task manifest requires a non-empty task_ids list")
    if len(task_ids) != len(set(task_ids)) or manifest.get("task_count") != len(task_ids):
        raise ValueError("task manifest task IDs/count are inconsistent")
    split_ids = [task_id for values in manifest.get("splits", {}).values() for task_id in values]
    if split_ids != task_ids:
        raise ValueError("task manifest splits do not reproduce task_ids in order")
    unsigned = dict(manifest)
    recorded_hash = unsigned.pop("selection_hash", None)
    canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if recorded_hash != actual_hash:
        raise ValueError("task manifest selection_hash integrity check failed")


def budget_limits(config: dict[str, Any], *, enforce: bool = True) -> BudgetLimits:
    value = config["budget"]
    required = ("max_steps", "max_errors", "max_total_tokens", "max_tool_calls", "max_latency_seconds", "allow_write")
    missing = [name for name in required if name not in value]
    if missing:
        raise ValueError("budget is missing: " + ", ".join(missing))
    return BudgetLimits(
        max_steps=int(value["max_steps"]),
        max_errors=int(value["max_errors"]),
        max_total_tokens=int(value["max_total_tokens"]),
        max_tool_calls=int(value["max_tool_calls"]),
        max_latency_seconds=float(value["max_latency_seconds"]),
        allow_write=bool(value["allow_write"]),
        enforce=enforce,
        emergency_multiplier=float(value.get("emergency_multiplier", 2.0)),
    )


def validate_experiment_config(config: dict[str, Any], *, formal: bool) -> None:
    if config.get("benchmark") != "AppWorld":
        raise ValueError("benchmark must be AppWorld")
    if config.get("experiment") not in {"E1", "E2"}:
        raise ValueError("experiment must be E1 or E2")
    limits = budget_limits(config)
    for name in ("max_steps", "max_errors", "max_total_tokens", "max_tool_calls", "max_latency_seconds"):
        if getattr(limits, name) <= 0:
            raise ValueError(f"budget {name} must be positive")
    if limits.emergency_multiplier < 1:
        raise ValueError("budget emergency_multiplier must be at least 1")
    if config.get("lessons", {}).get("enabled") is not False:
        raise ValueError("AppWorld E1/E2 requires lessons.enabled=false")
    model = config.get("model", {})
    for name in ("temperature", "prompt_version", "tool_schema_version", "max_output_tokens_per_call"):
        if name not in model:
            raise ValueError(f"model config is missing {name}")
    if formal and float(model["temperature"]) != 0.0:
        raise ValueError("formal experiments require temperature=0")
    if int(model["max_output_tokens_per_call"]) < 1:
        raise ValueError("max_output_tokens_per_call must be positive")
    timeout = model.get("request_timeout_seconds")
    if timeout is None or float(timeout) <= 0:
        raise ValueError("model.request_timeout_seconds must be positive")
    if float(timeout) > float(config["budget"]["max_latency_seconds"]):
        raise ValueError("request timeout cannot exceed per-task latency budget")
    if len(set(config.get("seeds", []))) != len(config.get("seeds", [])) or not config.get("seeds"):
        raise ValueError("seeds must be a non-empty unique list")
    if formal and len(config["seeds"]) < 2:
        raise ValueError("formal experiments require multiple seeds")
    serialized = json.dumps(config, ensure_ascii=False)
    if formal and "freeze_before_run" in serialized:
        raise ValueError("formal config still contains freeze_before_run placeholders")
    if config["experiment"] == "E2":
        base_condition = config.get("base_condition")
        component_ids = {item["id"] for item in config.get("component_conditions", [])}
        if not isinstance(base_condition, str) or base_condition not in component_ids:
            raise ValueError("E2 base_condition must name a component condition")
        edge_ids = {tuple(item["masked_edge"]) for item in config.get("edge_conditions", [])}
        supported = {("planner", "executor"), ("executor", "verifier")}
        if not edge_ids <= supported:
            raise ValueError(f"unsupported E2 edge conditions: {sorted(edge_ids - supported)}")
        for item in config.get("edge_conditions", []):
            if item.get("artifact_policy", "typed_null") not in {"typed_null", "passthrough"}:
                raise ValueError(f"unsupported E2 artifact policy: {item.get('artifact_policy')}")
    condition_items = config.get("conditions", []) + config.get("component_conditions", []) + config.get("edge_conditions", [])
    condition_ids = [item["id"] for item in condition_items]
    if len(condition_ids) != len(set(condition_ids)):
        raise ValueError("condition IDs must be unique")


@contextmanager
def appworld_root(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def default_world_factory(
    *, appworld_dir: Path, task_id: str, experiment_name: str, seed: int, limits: BudgetLimits
) -> Any:
    with appworld_root(appworld_dir):
        if str(appworld_dir / "src") not in sys.path:
            sys.path.insert(0, str(appworld_dir / "src"))
        from appworld import AppWorld

        emergency_factor = limits.emergency_multiplier if not limits.enforce else 1.0
        return AppWorld(
            task_id=task_id,
            experiment_name=experiment_name,
            random_seed=seed,
            # AppWorld's code agents use one environment interaction for a
            # complete Python cell, which can safely contain many direct API
            # calls. The controller independently accounts for every endpoint
            # call and sets the requester cap to the remaining global budget.
            max_interactions=max(1, int(limits.max_steps * emergency_factor)),
            max_api_calls_per_interaction=max(1, int(limits.max_tool_calls * emergency_factor)),
            timeout_seconds=max(1, int(limits.max_latency_seconds)),
            load_ground_truth=True,  # evaluator-only; never placed in model messages
            ground_truth_mode="full",
            include_direct_functions=True,
            direct_function_separator="__",
            raise_on_unsafe_syntax=True,
            raise_on_unsafe_execution=True,
        )


class AppWorldExperimentRunner:
    def __init__(
        self,
        *,
        config_path: Path,
        task_manifest_path: Path,
        appworld_dir: Path,
        output_root: Path,
        model: PhaseModel,
        world_factory: WorldFactory = default_world_factory,
        formal: bool = False,
        resume: bool = False,
    ) -> None:
        self.config_path = config_path.resolve()
        self.task_manifest_path = task_manifest_path.resolve()
        self.appworld_dir = appworld_dir.resolve()
        self.output_root = output_root.resolve()
        self.model = model
        self.world_factory = world_factory
        self.formal = formal
        self.resume = resume
        self.config = load_json(self.config_path)
        self.task_manifest = load_json(self.task_manifest_path)
        validate_task_manifest(self.task_manifest)
        self.task_splits = {
            task_id: split
            for split, task_ids in self.task_manifest.get("splits", {}).items()
            for task_id in task_ids
        }
        validate_experiment_config(self.config, formal=formal)
        if self.task_manifest.get("task_set") != self.config.get("task_set"):
            raise ValueError("task manifest task_set does not match experiment config")
        self.output_root.mkdir(parents=True, exist_ok=True)
        expected = self.task_manifest.get("appworld_commit")
        actual = git_commit(self.appworld_dir)
        if expected and expected != actual:
            raise ValueError(f"AppWorld commit mismatch: expected {expected}, found {actual}")
        if formal and (git_dirty(self.config_path.parents[3]) or git_dirty(self.appworld_dir)):
            raise ValueError("formal experiments require clean Metamorph and AppWorld git worktrees")

    def _run_dir(self, condition: str, task_id: str, seed: int) -> Path:
        return self.output_root / "runs" / condition / task_id / str(seed)

    def _world_name(self, condition: str, task_id: str, seed: int) -> str:
        safe_task = re_sub_nonword(task_id)
        return f"{self.config['experiment_id']}-{condition}-{safe_task}-{seed}"

    def write_manifest(self) -> Path:
        embedded_task_manifest = self.output_root / "task_manifest.json"
        manifest = {
            "schema_version": "appworld.experiment-manifest.v1",
            "experiment_id": self.config["experiment_id"],
            "experiment": self.config["experiment"],
            "created_at_unix": time.time(),
            "metamorph_commit": git_commit(self.config_path.parents[3]),
            "appworld_commit": git_commit(self.appworld_dir),
            "config_path": str(self.config_path),
            "config_hash": sha256_file(self.config_path),
            "task_manifest_source_path": str(self.task_manifest_path),
            "task_manifest_path": str(embedded_task_manifest),
            "task_manifest_hash": sha256_file(self.task_manifest_path),
            "task_selection_hash": self.task_manifest.get("selection_hash"),
            "task_ids": self.task_manifest["task_ids"],
            "task_splits": self.task_manifest.get("splits", {}),
            "provider": getattr(self.model, "provider", "custom"),
            "model": self.model.model_name,
            "prompt_version": self.config["model"]["prompt_version"],
            "prompt_source_hash": sha256_file(Path(__file__).with_name("appworld_adapter.py")),
            "contract_source_hash": sha256_file(Path(__file__).with_name("appworld_contracts.py")),
            "code_executor_source_hash": sha256_file(Path(__file__).with_name("appworld_code_executor.py")),
            "provider_adapter_source_hash": sha256_file(Path(__file__).parents[1] / "llm" / "adapters.py"),
            "provider_client_source_hash": sha256_file(Path(__file__).parents[1] / "llm" / "client.py"),
            "tool_schema_version": self.config["model"]["tool_schema_version"],
            "tool_policy": self.config["budget"].get("tool_policy"),
            "evaluator": {
                "name": "AppWorld individual evaluator",
                "version": git_commit(self.appworld_dir),
                "primary_mapping": "strict_success_to_binary_reward",
            },
            "runner_version": "appworld.experiment-manifest.v1",
            "budget": self.config["budget"],
            "seeds": self.config["seeds"],
            "formal": self.formal,
        }
        path = self.output_root / "manifest.json"
        if path.exists():
            previous = load_json(path)
            immutable = (
                "config_hash",
                "task_manifest_hash",
                "provider",
                "model",
                "appworld_commit",
                "formal",
                "prompt_source_hash",
                "contract_source_hash",
                "code_executor_source_hash",
                "provider_adapter_source_hash",
                "provider_client_source_hash",
            )
            changed = [name for name in immutable if previous.get(name) != manifest.get(name)]
            if changed:
                raise ValueError("existing manifest is incompatible: " + ", ".join(changed))
            if not embedded_task_manifest.exists() or sha256_file(embedded_task_manifest) != manifest["task_manifest_hash"]:
                raise ValueError("embedded task_manifest.json is missing or has changed")
            return path
        if embedded_task_manifest.resolve() != self.task_manifest_path:
            if embedded_task_manifest.exists():
                if sha256_file(embedded_task_manifest) != manifest["task_manifest_hash"]:
                    raise ValueError("refusing to replace a different embedded task_manifest.json")
            else:
                shutil.copy2(self.task_manifest_path, embedded_task_manifest)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _new_world(self, condition: str, task_id: str, seed: int, limits: BudgetLimits) -> Any:
        return self.world_factory(
            appworld_dir=self.appworld_dir,
            task_id=task_id,
            experiment_name=self._world_name(condition, task_id, seed),
            seed=seed,
            limits=limits,
        )

    def _close_world(self, world: Any, *, restored_checkpoint: bool = False) -> None:
        """Close a world without letting AppWorld's load-state freezer bug erase an arm.

        AppWorld.load_state() calls AppWorld.close_all(), which stops the
        instance freezer but leaves the instance carrying that stopped freezer.
        A later instance.close() can call freezegun.stop() a second time and
        raise ``IndexError``/``AttributeError``.  The run result and checkpoint
        are already valid at that point, so tolerate only those documented
        cleanup signatures and finally clear AppWorld's class-level globals.
        """

        cleanup_error: Exception | None = None
        try:
            world.close()
        except (AttributeError, IndexError) as exc:
            if not restored_checkpoint:
                raise
            cleanup_error = exc
        if self.world_factory is default_world_factory:
            with appworld_root(self.appworld_dir):
                from appworld import AppWorld

                AppWorld.close_all()
        if cleanup_error is not None:
            # The specific duplicate-freezer cleanup failure is intentionally
            # non-fatal; class-level cleanup above restored the process state.
            return

    def _result_base(self, condition: str, task_id: str, seed: int) -> dict[str, Any]:
        return {
            "schema_version": "appworld.result.v1",
            "benchmark": "AppWorld",
            "experiment_id": self.config["experiment_id"],
            "condition": condition,
            "task_id": task_id,
            "split": self.task_splits.get(task_id),
            "seed": seed,
        }

    def _persist_result(self, run_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "result.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _safe_run(self, condition: str, task_id: str, seed: int, function: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return function()
        except FileExistsError:
            raise
        except Exception as exc:  # every failed arm remains in the paired dataset
            result = {
                **self._result_base(condition, task_id, seed),
                "status": "failed",
                "official_reward": 0.0,
                "strict_success": False,
                "error": str(exc),
                "failure_category": type(exc).__name__,
            }
            return self._persist_result(self._run_dir(condition, task_id, seed), result)

    def run_condition(self, condition: str, task_id: str, seed: int) -> dict[str, Any]:
        if hasattr(self.model, "configure"):
            self.model.configure(
                temperature=float(self.config["model"]["temperature"]),
                seed=seed,
                request_timeout_seconds=float(self.config["model"]["request_timeout_seconds"]),
            )
        run_dir = self._run_dir(condition, task_id, seed)
        existing_result = run_dir / "result.json"
        if existing_result.exists():
            if self.resume:
                return load_json(existing_result)
            raise FileExistsError(f"refusing to overwrite existing result: {existing_result}")
        base = self._result_base(condition, task_id, seed)
        component = next((item for item in self.config.get("component_conditions", []) if item["id"] == condition), {})
        e1_condition = next((item for item in self.config.get("conditions", []) if item["id"] == condition), {})
        workflow = e1_condition.get("workflow", {}) if self.config["experiment"] == "E1" else {}
        if self.config["experiment"] == "E1" and not isinstance(workflow, dict):
            raise ValueError("E1 condition requires a workflow object")
        no_gate = component.get("disable_feature") == "budget_gate"
        limits = budget_limits(self.config, enforce=not no_gate)
        world = self._new_world(condition, task_id, seed, limits)
        controller = AppWorldController(
            world=world,
            model=self.model,
            limits=limits,
            trace_dir=run_dir / "traces",
            json_contract=component.get("disable_feature") != "json_contract",
            enable_verifier=(
                bool(workflow.get("verifier")) if self.config["experiment"] == "E1"
                else component.get("exclude_agent") != "verifier"
            ),
            enable_repair=(
                bool(workflow.get("repair")) if self.config["experiment"] == "E1"
                else component.get("disable_feature") != "repair_loop"
            ),
            max_output_tokens=int(self.config["model"]["max_output_tokens_per_call"]),
            require_token_usage=self.formal,
            request_timeout_seconds=float(self.config["model"]["request_timeout_seconds"]),
        )
        try:
            route_record: dict[str, Any] | None = None
            if self.config["experiment"] == "E1":
                config_condition = next(item for item in self.config["conditions"] if item["id"] == condition)
                route_record = {"workflow": workflow, "source": "fixed_pre_registered"}
                execution = controller.run_fixed_s3(exclude_planner=not bool(workflow.get("planner")))
            else:
                execution = controller.run_fixed_s3(exclude_planner=component.get("exclude_agent") == "planner")
            world.save()
            metrics = official_metrics(world)
            audit = controller.audit_payload()
            result = {
                **base,
                "status": "completed",
                **metrics,
                "routing": route_record,
                "answer": execution.get("answer", ""),
                "artifacts": execution.get("artifacts", {}),
                "artifact_hashes": execution.get("artifact_hashes", {}),
                "budget": audit["budget"],
                "selected_tools": audit["selected_tools"],
                "selected_tool_schema_hash": audit["selected_tool_schema_hash"],
                "checkpoints": audit["checkpoints"],
                "replay": None,
                "failure_category": None,
            }
        except Exception as exc:
            result = {
                **base,
                "status": "failed",
                "official_reward": 0.0,
                "strict_success": False,
                "budget": controller.ledger.snapshot(),
                "error": str(exc),
                "failure_category": type(exc).__name__,
            }
        finally:
            self._close_world(world)
        return self._persist_result(run_dir, result)

    def run_edge_intervention(self, edge_condition: dict[str, Any], task_id: str, seed: int) -> dict[str, Any]:
        if hasattr(self.model, "configure"):
            self.model.configure(
                temperature=float(self.config["model"]["temperature"]),
                seed=seed,
                request_timeout_seconds=float(self.config["model"]["request_timeout_seconds"]),
            )
        condition = edge_condition["id"]
        run_dir = self._run_dir(condition, task_id, seed)
        existing_result = run_dir / "result.json"
        if existing_result.exists():
            if self.resume:
                return load_json(existing_result)
            raise FileExistsError(f"refusing to overwrite existing result: {existing_result}")
        base = self._result_base(condition, task_id, seed)
        baseline_condition = self.config["base_condition"]
        baseline_path = self._run_dir(baseline_condition, task_id, seed) / "result.json"
        if not baseline_path.exists():
            raise ValueError(f"{baseline_condition} baseline required before {condition}: {baseline_path}")
        baseline = load_json(baseline_path)
        edge = tuple(edge_condition["masked_edge"])
        checkpoint_name = "pre_executor" if edge == ("planner", "executor") else "post_executor"
        source_checkpoint = baseline["checkpoints"][checkpoint_name]
        source_path = Path(source_checkpoint["path"])
        source_hash_before = _hash_directory(source_path)
        if source_hash_before != source_checkpoint["state_hash"]:
            raise ValueError("baseline checkpoint hash changed before replay")
        limits = budget_limits(self.config)
        world = self._new_world(condition, task_id, seed, limits)
        imported_id = f"source-{checkpoint_name}"
        destination = Path(world.output_checkpoints_directory) / imported_id
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source_path, destination)
        world.load_state(imported_id)
        controller = AppWorldController(
            world=world,
            model=self.model,
            limits=limits,
            initial_usage=source_checkpoint["budget"],
            trace_dir=run_dir / "traces",
            json_contract=True,
            enable_verifier=True,
            enable_repair=True,
            max_output_tokens=int(self.config["model"]["max_output_tokens_per_call"]),
            require_token_usage=self.formal,
            request_timeout_seconds=float(self.config["model"]["request_timeout_seconds"]),
        )
        try:
            replay = controller.replay_masked_edge(
                edge=edge,
                baseline_artifacts=baseline["artifacts"],
                selected_tools=baseline["selected_tools"],
                artifact_policy=edge_condition.get("artifact_policy", "typed_null"),
            )
            world.save()
            metrics = official_metrics(world)
            source_hash_after = _hash_directory(source_path)
            contamination = source_hash_before != source_hash_after
            replay.update({
                "source_checkpoint": checkpoint_name,
                "source_state_hash": source_hash_before,
                "replay_state_hash": controller.checkpoints["final"]["state_hash"],
                "replayed_agents": sorted(controller.traces),
                "baseline_checkpoint_unchanged": not contamination,
                "replay_contamination": contamination,
            })
            result = {
                **base,
                "status": "completed",
                **metrics,
                "artifacts": replay["artifacts"],
                "artifact_hashes": replay["artifact_hashes"],
                "budget": controller.ledger.snapshot(),
                "selected_tools": baseline["selected_tools"],
                "checkpoints": controller.checkpoints,
                "replay": replay,
                "failure_category": "replay_contamination" if contamination else None,
            }
        except Exception as exc:
            result = {
                **base,
                "status": "failed",
                "official_reward": 0.0,
                "strict_success": False,
                "budget": controller.ledger.snapshot(),
                "error": str(exc),
                "failure_category": type(exc).__name__,
            }
        finally:
            self._close_world(world, restored_checkpoint=True)
        return self._persist_result(run_dir, result)

    def run_task(self, task_id: str, seed: int, condition_ids: set[str] | None = None) -> list[dict[str, Any]]:
        if self.config["experiment"] == "E1":
            items = [item for item in self.config["conditions"] if condition_ids is None or item["id"] in condition_ids]
            return [self._safe_run(item["id"], task_id, seed, lambda item=item: self.run_condition(item["id"], task_id, seed)) for item in items]
        component_items = [item for item in self.config["component_conditions"] if condition_ids is None or item["id"] in condition_ids]
        edge_items = [item for item in self.config["edge_conditions"] if condition_ids is None or item["id"] in condition_ids]
        # A fixed-context edge intervention is undefined without its matching
        # The configured Full checkpoint. When users request an edge alone (common in pilot
        # and recovery runs), materialize that dependency exactly once.
        baseline_condition = self.config["base_condition"]
        baseline_path = self._run_dir(baseline_condition, task_id, seed) / "result.json"
        if edge_items and not baseline_path.exists() and not any(item["id"] == baseline_condition for item in component_items):
            component_items.insert(0, next(item for item in self.config["component_conditions"] if item["id"] == baseline_condition))
        results = [self._safe_run(item["id"], task_id, seed, lambda item=item: self.run_condition(item["id"], task_id, seed)) for item in component_items]
        results.extend(self._safe_run(item["id"], task_id, seed, lambda item=item: self.run_edge_intervention(item, task_id, seed)) for item in edge_items)
        return results


def re_sub_nonword(value: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value)
