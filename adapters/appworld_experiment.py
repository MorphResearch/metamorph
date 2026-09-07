"""Configuration-driven AppWorld E1/E2 experiment runner."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from .appworld_adapter import AppWorldController, PhaseModel, _hash_directory, official_metrics
from .appworld_budget import BudgetLimits
from .appworld_dag import Intervention, registered_dags


WorldFactory = Callable[..., Any]


class ArmTimeout(RuntimeError):
    """Raised in the parent process when one arm exceeds its wall-clock limit."""


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _pid_is_alive(pid: Any) -> bool:
    try:
        value = int(pid)
        if value <= 0:
            return False
        os.kill(value, 0)
    except (TypeError, ValueError, OSError):
        return False
    return True


@contextmanager
def arm_timeout(seconds: float) -> Iterator[None]:
    """Bound an arm without replacing the provider's per-request timeout."""

    if seconds <= 0 or not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        # Signal timers cannot safely be installed from a worker thread;
        # provider timeouts remain active in that case.
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expire(_signum: int, _frame: Any) -> None:
        raise ArmTimeout(f"arm_timeout after {seconds:g} seconds")

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


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


def budget_cost_usd(config: dict[str, Any], budget: dict[str, Any]) -> float | None:
    """Price observed tokens only when a frozen per-token price is supplied."""

    pricing = config.get("pricing")
    if not isinstance(pricing, dict):
        return None
    try:
        input_rate = float(pricing["input_usd_per_million_tokens"])
        output_rate = float(pricing["output_usd_per_million_tokens"])
    except (KeyError, TypeError, ValueError):
        return None
    return round(
        (float(budget.get("input_tokens", 0) or 0) * input_rate + float(budget.get("output_tokens", 0) or 0) * output_rate)
        / 1_000_000,
        8,
    )


def validate_experiment_config(config: dict[str, Any], *, formal: bool) -> None:
    if config.get("benchmark") != "AppWorld":
        raise ValueError("benchmark must be AppWorld")
    if config.get("experiment") not in {"E1", "E2", "DAG_E1", "DAG_E2"}:
        raise ValueError("experiment must be E1, E2, DAG_E1, or DAG_E2")
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
    pricing = config.get("pricing")
    if pricing is not None:
        for name in ("input_usd_per_million_tokens", "output_usd_per_million_tokens"):
            if name not in pricing or float(pricing[name]) < 0:
                raise ValueError(f"pricing.{name} must be a non-negative number")
    timeout = model.get("request_timeout_seconds")
    if timeout is None or float(timeout) <= 0:
        raise ValueError("model.request_timeout_seconds must be positive")
    if float(timeout) > float(config["budget"]["max_latency_seconds"]):
        raise ValueError("request timeout cannot exceed per-task latency budget")
    projection = config.get("context_projection", {})
    if projection and not isinstance(projection, dict):
        raise ValueError("context_projection must be an object")
    for name in (
        "max_model_visible_tool_chars",
        "max_model_visible_evidence_chars",
        "max_model_visible_node_transcript_chars",
        "max_model_visible_list_items",
    ):
        if name in projection and int(projection[name]) <= 0:
            raise ValueError(f"context_projection.{name} must be positive")
    reservations = config["budget"].get("downstream_reservations", {})
    if reservations and not isinstance(reservations, dict):
        raise ValueError("budget.downstream_reservations must be an object")
    if isinstance(reservations, dict) and any(int(value) < 0 for value in reservations.values()):
        raise ValueError("budget.downstream_reservations values must be non-negative")
    arm_timeout_seconds = config.get("run_control", {}).get("arm_timeout_seconds", 900)
    if float(arm_timeout_seconds) <= 0:
        raise ValueError("run_control.arm_timeout_seconds must be positive")
    if len(set(config.get("seeds", []))) != len(config.get("seeds", [])) or not config.get("seeds"):
        raise ValueError("seeds must be a non-empty unique list")
    if formal and len(config["seeds"]) == 1 and not bool(
        config.get("statistical_limitations", {}).get("single_seed")
    ):
        raise ValueError("single-seed formal experiments require statistical_limitations.single_seed=true")
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
    if config["experiment"] in {"DAG_E1", "DAG_E2"}:
        allowed_dags = set(registered_dags())
        for item in config.get("conditions", []):
            if item.get("dag_id") not in allowed_dags:
                raise ValueError(f"DAG_E1 condition requires dag_id in {sorted(allowed_dags)}")
        if config["experiment"] == "DAG_E2":
            base_condition = config.get("base_condition")
            base_ids = {item["id"] for item in config.get("conditions", [])}
            if not isinstance(base_condition, str) or base_condition not in base_ids:
                raise ValueError("DAG_E2 base_condition must name a DAG condition")
            for item in config.get("replay_conditions", []):
                if item.get("dag_id") not in allowed_dags:
                    raise ValueError(f"DAG_E2 replay requires dag_id in {sorted(allowed_dags)}")
                if not isinstance(item.get("source_checkpoint"), str):
                    raise ValueError("DAG_E2 replay requires source_checkpoint")
                if not isinstance(item.get("initial_artifact_nodes", []), list):
                    raise ValueError("DAG_E2 initial_artifact_nodes must be a list")
    condition_items = (
        config.get("conditions", [])
        + config.get("component_conditions", [])
        + config.get("edge_conditions", [])
        + config.get("replay_conditions", [])
    )
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
            # Minimal mode supports official evaluation but does not load the
            # solution or required-API metadata into the model-serving process.
            ground_truth_mode="minimal",
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
        self.arm_timeout_seconds = float(self.config.get("run_control", {}).get("arm_timeout_seconds", 900))
        self._active_run_dir: Path | None = None
        self._state_lock = threading.Lock()
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
            "experiment_runner_source_hash": sha256_file(Path(__file__)),
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
            "statistical_limitations": self.config.get("statistical_limitations", {}),
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
                "experiment_runner_source_hash",
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

    def _close_world(self, world: Any, *, restored_checkpoint: bool = False) -> str | None:
        """Close a world without letting AppWorld's load-state freezer bug erase an arm.

        AppWorld.load_state() calls AppWorld.close_all(), which stops the
        instance freezer but leaves the instance carrying that stopped freezer.
        A later instance.close() can call freezegun.stop() a second time and
        raise ``IndexError``/``AttributeError``.  The run result and checkpoint
        are already valid at that point, so tolerate only those documented
        cleanup signatures and finally clear AppWorld's class-level globals.
        """

        del restored_checkpoint  # both paths are vulnerable to duplicate freezer teardown
        cleanup_error: Exception | None = None
        try:
            world.close()
        except (AttributeError, IndexError) as exc:
            cleanup_error = exc
        if self.world_factory is default_world_factory:
            try:
                with appworld_root(self.appworld_dir):
                    from appworld import AppWorld

                    AppWorld.close_all()
            except (AttributeError, IndexError):
                cleanup_error = cleanup_error or RuntimeError("AppWorld class-level freezer cleanup failed")
        if cleanup_error is not None:
            # The specific duplicate-freezer cleanup failure is intentionally
            # non-fatal; class-level cleanup above restored the process state.
            return f"{type(cleanup_error).__name__}: {cleanup_error}"
        return None

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
        budget = result.get("budget") if isinstance(result.get("budget"), dict) else {}
        for name in ("missing_token_usage_calls", "total_tokens", "latency_seconds", "budget_exhausted", "tool_calls"):
            result.setdefault(name, budget.get(name))
        result.setdefault("failure_reason", result.get("error"))
        result.setdefault("exception_type", result.get("failure_category"))
        result.setdefault("exception_message", result.get("error"))
        result.setdefault("trace_paths", [str(path) for path in sorted((run_dir / "traces").glob("*.json"))])
        result.setdefault("checkpoint_paths", {
            name: value.get("path") for name, value in (result.get("checkpoints") or {}).items()
            if isinstance(value, dict)
        })
        path = run_dir / "result.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _write_run_state(self, run_dir: Path, state: dict[str, Any]) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        state["last_heartbeat_at"] = _utc_now()
        path = run_dir / "run_state.json"
        # G2 emits events from two genuine parallel read-only branches.  A
        # per-thread temporary avoids one atomic replace deleting another
        # writer's staging file before it can replace the state file.
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _append_arm_log(self, run_dir: Path, event: str, details: dict[str, Any]) -> None:
        payload = {"time": _utc_now(), "event": event, **details}
        with (run_dir / "arm.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"[{payload['time']}] {event} {json.dumps(details, ensure_ascii=False, sort_keys=True)}", flush=True)

    def _arm_event(self, event: str, details: dict[str, Any]) -> None:
        if self._active_run_dir is None:
            return
        with self._state_lock:
            path = self._active_run_dir / "run_state.json"
            state = load_json(path) if path.exists() else {"status": "running"}
            if event == "STAGE_START":
                state["current_stage"] = details.get("phase", "unknown")
            self._write_run_state(self._active_run_dir, state)
            self._append_arm_log(self._active_run_dir, event, details)

    def _begin_arm(self, condition: str, task_id: str, seed: int) -> dict[str, Any] | None:
        run_dir = self._run_dir(condition, task_id, seed)
        result_path = run_dir / "result.json"
        if result_path.exists():
            print(f"ARM_ALREADY_FINISHED {condition} {task_id} {seed}", flush=True)
            return load_json(result_path)
        state_path = run_dir / "run_state.json"
        if state_path.exists():
            state = load_json(state_path)
            if state.get("status") == "running" and _pid_is_alive(state.get("pid")):
                raise RuntimeError(f"ARM_ALREADY_RUNNING {condition} {task_id} {seed} pid={state.get('pid')}")
            if state.get("status") == "running":
                state.update({"status": "stale", "failure_reason": "runner_process_not_alive"})
                self._write_run_state(run_dir, state)
                self._append_arm_log(run_dir, "ARM_STALE", {"previous_pid": state.get("pid")})
        state = {
            "status": "running", "pid": os.getpid(), "condition": condition,
            "task_id": task_id, "seed": seed, "started_at": _utc_now(),
            "last_heartbeat_at": _utc_now(), "current_stage": "initializing",
        }
        self._write_run_state(run_dir, state)
        self._append_arm_log(run_dir, "ARM_START", {"condition": condition, "task_id": task_id, "seed": seed, "pid": os.getpid()})
        return None

    def _finish_arm(self, result: dict[str, Any]) -> None:
        if self._active_run_dir is None:
            return
        terminal = "finished" if result.get("status") == "completed" else result.get("status", "failed")
        state = load_json(self._active_run_dir / "run_state.json")
        state.update({
            "status": terminal,
            "current_stage": "finished",
            "finished_at": _utc_now(),
            "failure_reason": result.get("failure_reason"),
            "result_path": str(self._active_run_dir / "result.json"),
        })
        self._write_run_state(self._active_run_dir, state)
        self._append_arm_log(self._active_run_dir, "ARM_SUCCESS" if terminal == "finished" else "ARM_FAILURE", {"status": terminal, "failure_reason": result.get("failure_reason")})

    def _safe_run(self, condition: str, task_id: str, seed: int, function: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        existing = self._begin_arm(condition, task_id, seed)
        if existing is not None:
            return existing
        run_dir = self._run_dir(condition, task_id, seed)
        self._active_run_dir = run_dir
        try:
            with arm_timeout(self.arm_timeout_seconds):
                result = function()
        except ArmTimeout as exc:
            result = {
                **self._result_base(condition, task_id, seed), "status": "timeout", "official_reward": 0.0,
                "strict_success": False, "protocol_valid": False,
                "protocol_invalid_reasons": ["infrastructure_failure: arm_timeout"],
                "failure_reason": "arm_timeout", "exception_type": type(exc).__name__, "exception_message": str(exc),
            }
            result = self._persist_result(run_dir, result)
        except Exception as exc:  # every failed arm remains in the paired dataset
            result = {
                **self._result_base(condition, task_id, seed),
                "status": "failed",
                "official_reward": 0.0,
                "strict_success": False,
                "protocol_valid": False,
                "protocol_invalid_reasons": [f"infrastructure_failure: {type(exc).__name__}"],
                "error": str(exc),
                "failure_category": type(exc).__name__,
                "failure_reason": "runner_exception",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
            result = self._persist_result(run_dir, result)
        finally:
            self._finish_arm(result)
            self._active_run_dir = None
        return result

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
            max_model_visible_tool_chars=int(
                self.config.get("context_projection", {}).get("max_model_visible_tool_chars", 6_000)
            ),
            max_model_visible_evidence_chars=int(
                self.config.get("context_projection", {}).get("max_model_visible_evidence_chars", 12_000)
            ),
            max_model_visible_node_transcript_chars=int(
                self.config.get("context_projection", {}).get("max_model_visible_node_transcript_chars", 12_000)
            ),
            max_model_visible_list_items=int(
                self.config.get("context_projection", {}).get("max_model_visible_list_items", 8)
            ),
            downstream_reservations=dict(self.config["budget"].get("downstream_reservations", {})),
            require_token_usage=self.formal,
            request_timeout_seconds=float(self.config["model"]["request_timeout_seconds"]),
            event_callback=self._arm_event,
        )
        try:
            route_record: dict[str, Any] | None = None
            if self.config["experiment"] in {"DAG_E1", "DAG_E2"}:
                config_condition = next(item for item in self.config["conditions"] if item["id"] == condition)
                dag_id = config_condition["dag_id"]
                route_record = {"dag_id": dag_id, "source": "fixed_pre_registered"}
                execution = controller.run_dag(registered_dags()[dag_id])
            elif self.config["experiment"] == "E1":
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
                "dag_execution": execution.get("dag_execution"),
                # Environment success is the official AppWorld outcome.  This
                # independent flag says whether all required execution traces
                # and artifacts satisfied the audit protocol.
                "protocol_valid": bool(execution.get("protocol_valid", True)),
                "protocol_invalid_reasons": list(execution.get("protocol_invalid_reasons", [])),
                "phase_statuses": execution.get("phase_statuses", {
                    name: trace.get("status") for name, trace in audit["phases"].items()
                }),
                "budget": audit["budget"],
                "cost_usd": budget_cost_usd(self.config, audit["budget"]),
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
                "protocol_valid": False,
                "protocol_invalid_reasons": [f"run exception: {type(exc).__name__}"],
                "budget": controller.ledger.snapshot(),
                "cost_usd": budget_cost_usd(self.config, controller.ledger.snapshot()),
                "error": str(exc),
                "failure_category": type(exc).__name__,
            }
        finally:
            cleanup_warning = self._close_world(world)
            if cleanup_warning is not None:
                result["cleanup_warning"] = cleanup_warning
        return self._persist_result(run_dir, result)

    def run_dag_replay_intervention(self, replay_condition: dict[str, Any], task_id: str, seed: int) -> dict[str, Any]:
        """Restore a real DAG checkpoint and execute only its legal downstream subgraph."""

        if hasattr(self.model, "configure"):
            self.model.configure(
                temperature=float(self.config["model"]["temperature"]),
                seed=seed,
                request_timeout_seconds=float(self.config["model"]["request_timeout_seconds"]),
            )
        condition = replay_condition["id"]
        run_dir = self._run_dir(condition, task_id, seed)
        existing_result = run_dir / "result.json"
        if existing_result.exists():
            if self.resume:
                return load_json(existing_result)
            raise FileExistsError(f"refusing to overwrite existing result: {existing_result}")
        base = self._result_base(condition, task_id, seed)
        baseline_path = self._run_dir(self.config["base_condition"], task_id, seed) / "result.json"
        if not baseline_path.exists():
            raise ValueError(f"DAG baseline required before {condition}: {baseline_path}")
        baseline = load_json(baseline_path)
        if baseline.get("status") != "completed" or not baseline.get("protocol_valid", False):
            raise ValueError("DAG replay requires a completed, protocol-valid baseline")
        baseline_execution = baseline.get("dag_execution") or {}
        source_checkpoint_name = replay_condition["source_checkpoint"]
        source_checkpoint = baseline["checkpoints"].get(source_checkpoint_name)
        if not isinstance(source_checkpoint, dict):
            raise ValueError(f"baseline checkpoint is missing: {source_checkpoint_name}")
        source_path = Path(source_checkpoint["path"])
        source_hash_before = _hash_directory(source_path)
        if source_hash_before != source_checkpoint["state_hash"]:
            raise ValueError("baseline checkpoint hash changed before DAG replay")
        source_artifacts = baseline_execution.get("artifacts", {})
        artifact_nodes = replay_condition.get("initial_artifact_nodes", [])
        initial_artifacts = {name: source_artifacts[name] for name in artifact_nodes if name in source_artifacts}
        if set(artifact_nodes) != set(initial_artifacts):
            missing = sorted(set(artifact_nodes) - set(initial_artifacts))
            raise ValueError(f"baseline DAG artifacts missing for replay: {missing}")
        spec = registered_dags()[replay_condition["dag_id"]]
        intervention_config = replay_condition.get("intervention", {})
        intervention = Intervention(
            skipped_nodes=frozenset(intervention_config.get("skipped_nodes", [])),
            masked_edges=frozenset(tuple(item) for item in intervention_config.get("masked_edges", [])),
            passthrough_edges=frozenset(tuple(item) for item in intervention_config.get("passthrough_edges", [])),
            serialize_read_only=bool(intervention_config.get("serialize_read_only", False)),
        )
        limits = budget_limits(self.config)
        world = self._new_world(condition, task_id, seed, limits)
        imported_id = f"source-{source_checkpoint_name}"
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
            max_model_visible_tool_chars=int(self.config.get("context_projection", {}).get("max_model_visible_tool_chars", 6_000)),
            max_model_visible_evidence_chars=int(self.config.get("context_projection", {}).get("max_model_visible_evidence_chars", 12_000)),
            max_model_visible_node_transcript_chars=int(
                self.config.get("context_projection", {}).get("max_model_visible_node_transcript_chars", 12_000)
            ),
            max_model_visible_list_items=int(self.config.get("context_projection", {}).get("max_model_visible_list_items", 8)),
            downstream_reservations=dict(self.config["budget"].get("downstream_reservations", {})),
            require_token_usage=self.formal,
            request_timeout_seconds=float(self.config["model"]["request_timeout_seconds"]),
            event_callback=self._arm_event,
        )
        try:
            execution = controller.run_dag(
                spec,
                intervention=intervention,
                initial_artifacts=initial_artifacts,
                selected_tools=baseline["selected_tools"],
            )
            world.save()
            metrics = official_metrics(world)
            audit = controller.audit_payload()
            source_hash_after = _hash_directory(source_path)
            contamination = source_hash_before != source_hash_after
            replay = {
                "source_checkpoint": source_checkpoint_name,
                "source_state_hash": source_hash_before,
                "replay_state_hash": controller.checkpoints["final"]["state_hash"],
                "initial_artifact_nodes": artifact_nodes,
                "replayed_nodes": sorted(name for name, item in execution["nodes"].items() if item["status"] == "completed"),
                "baseline_checkpoint_unchanged": not contamination,
                "replay_contamination": contamination,
            }
            result = {
                **base,
                "status": "completed",
                **metrics,
                "routing": {"dag_id": spec.id, "source": "checkpoint_replay"},
                "answer": execution.get("answer", ""),
                "artifacts": execution.get("artifacts", {}),
                "artifact_hashes": execution.get("artifact_hashes", {}),
                "dag_execution": execution.get("dag_execution"),
                "protocol_valid": bool(execution.get("protocol_valid", True)) and not contamination,
                "protocol_invalid_reasons": [
                    *execution.get("protocol_invalid_reasons", []),
                    *( ["baseline checkpoint contamination"] if contamination else [] ),
                ],
                "phase_statuses": execution.get("phase_statuses", {
                    name: trace.get("status") for name, trace in audit["phases"].items()
                }),
                "budget": audit["budget"],
                "cost_usd": budget_cost_usd(self.config, audit["budget"]),
                "selected_tools": baseline["selected_tools"],
                "selected_tool_schema_hash": baseline.get("selected_tool_schema_hash"),
                "checkpoints": audit["checkpoints"],
                "replay": replay,
                "failure_category": "replay_contamination" if contamination else None,
            }
        except Exception as exc:
            result = {
                **base,
                "status": "failed",
                "official_reward": 0.0,
                "strict_success": False,
                "protocol_valid": False,
                "protocol_invalid_reasons": [f"replay exception: {type(exc).__name__}"],
                "budget": controller.ledger.snapshot(),
                "cost_usd": budget_cost_usd(self.config, controller.ledger.snapshot()),
                "error": str(exc),
                "failure_category": type(exc).__name__,
            }
        finally:
            cleanup_warning = self._close_world(world, restored_checkpoint=True)
            if cleanup_warning is not None:
                result["cleanup_warning"] = cleanup_warning
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
            max_model_visible_tool_chars=int(self.config.get("context_projection", {}).get("max_model_visible_tool_chars", 6_000)),
            max_model_visible_evidence_chars=int(self.config.get("context_projection", {}).get("max_model_visible_evidence_chars", 12_000)),
            max_model_visible_node_transcript_chars=int(
                self.config.get("context_projection", {}).get("max_model_visible_node_transcript_chars", 12_000)
            ),
            max_model_visible_list_items=int(self.config.get("context_projection", {}).get("max_model_visible_list_items", 8)),
            downstream_reservations=dict(self.config["budget"].get("downstream_reservations", {})),
            require_token_usage=self.formal,
            request_timeout_seconds=float(self.config["model"]["request_timeout_seconds"]),
            event_callback=self._arm_event,
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
            cleanup_warning = self._close_world(world, restored_checkpoint=True)
            if cleanup_warning is not None:
                result["cleanup_warning"] = cleanup_warning
        return self._persist_result(run_dir, result)

    def run_task(self, task_id: str, seed: int, condition_ids: set[str] | None = None) -> list[dict[str, Any]]:
        if self.config["experiment"] in {"E1", "DAG_E1"}:
            items = [item for item in self.config["conditions"] if condition_ids is None or item["id"] in condition_ids]
            return [self._safe_run(item["id"], task_id, seed, lambda item=item: self.run_condition(item["id"], task_id, seed)) for item in items]
        if self.config["experiment"] == "DAG_E2":
            base_items = [item for item in self.config["conditions"] if condition_ids is None or item["id"] in condition_ids]
            replay_items = [item for item in self.config.get("replay_conditions", []) if condition_ids is None or item["id"] in condition_ids]
            baseline_condition = self.config["base_condition"]
            baseline_path = self._run_dir(baseline_condition, task_id, seed) / "result.json"
            if replay_items and not baseline_path.exists() and not any(item["id"] == baseline_condition for item in base_items):
                base_items.insert(0, next(item for item in self.config["conditions"] if item["id"] == baseline_condition))
            results = [self._safe_run(item["id"], task_id, seed, lambda item=item: self.run_condition(item["id"], task_id, seed)) for item in base_items]
            results.extend(self._safe_run(item["id"], task_id, seed, lambda item=item: self.run_dag_replay_intervention(item, task_id, seed)) for item in replay_items)
            return results
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
