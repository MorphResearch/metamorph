"""Public Database Exploration development-calibration entry.

This is deliberately a thin binding around the existing restricted tool loop.
It does not create a second agent framework, and live mode is rejected until a
separate public-calibration authorization is recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib
import json
import socket
import ssl
import time as monotonic_time
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from llm.adapters import ProviderAdapter

from .clbench_database_exploration import DatabaseExplorationAdapter
from .live import (
    FORMAL_INPUT_CUTOFF_ESTIMATOR_NAME,
    PriceSheet,
    ToolOnlySmokeConfig,
    _exception_chain,
    build_authorized_client,
    run_tool_only_episode,
    tool_only_schemas,
)
from .records import AuthorizationError, BudgetError, CostLedger, LiveAuthorization, RunRecords
from .runner import ExperimentRunner, stable_hash


ALLOWED_TOOLS = {"list_dir", "read_file", "write_file", "query_sql"}
FILE_TOOLS = {"list_dir", "read_file", "write_file"}
EXPECTED_EPISODES = (
    (1, "dev-1-f0", "1", "F0"),
    (2, "dev-1-u0", "1", "U0"),
    (3, "dev-2-u0", "2", "U0"),
    (4, "dev-2-f0", "2", "F0"),
    (5, "dev-3-f0", "3", "F0"),
    (6, "dev-3-u0", "3", "U0"),
)
PENDING_STATUSES = {
    "PENDING_PUBLIC_CALIBRATION_USER_SIGNOFF_NO_LIVE_CALLS",
    "PENDING_PUBLIC_CALIBRATION_OFFPEAK_USER_SIGNOFF",
    "PENDING_PUBLIC_CALIBRATION_REVISION_USER_SIGNOFF_NO_LIVE_CALLS",
    "PENDING_PUBLIC_CALIBRATION_REVISION_V2_USER_SIGNOFF_NO_LIVE_CALLS",
    "PENDING_PUBLIC_CALIBRATION_REVISION_V3_USER_SIGNOFF_NO_LIVE_CALLS",
}


def _offpeak_status(pending: dict[str, Any], *, for_new_episode: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """Evaluate the signed Asia/Shanghai window without using host local time."""
    rule = pending.get("offpeak_window")
    if rule is None:
        return {"request_allowed": True, "new_episode_allowed": True, "reason": "no_offpeak_window_configured"}
    zone = ZoneInfo(rule["timezone"])
    local = (now or datetime.now(timezone.utc)).astimezone(zone)
    start = time.fromisoformat(rule["start_local"])
    end = time.fromisoformat(rule["end_local"])
    clock = local.timetz().replace(tzinfo=None)
    if clock >= start:
        window_end = datetime.combine(local.date() + timedelta(days=1), end, tzinfo=zone)
    elif clock <= end:
        window_end = datetime.combine(local.date(), end, tzinfo=zone)
    else:
        window_end = None
    requested_window = window_end is not None
    # The official documentation lists weekday 09:00-12:00 and 14:00-18:00
    # Beijing time as peak.  Retain this independent check so a changed user
    # window cannot silently claim the off-peak rate.
    official_peak = local.weekday() < 5 and (time(9, 0) <= clock < time(12, 0) or time(14, 0) <= clock < time(18, 0))
    remaining_seconds = max(0, int((window_end - local).total_seconds())) if window_end else 0
    request_allowed = requested_window and not official_peak
    episode_seconds = int(rule["minimum_remaining_seconds_for_new_episode"])
    new_episode_allowed = request_allowed and remaining_seconds >= episode_seconds
    if not requested_window:
        reason = "outside_requested_Asia_Shanghai_window"
    elif official_peak:
        reason = "official_DeepSeek_peak_period"
    elif for_new_episode and not new_episode_allowed:
        reason = "insufficient_remaining_offpeak_time_for_episode"
    else:
        reason = "within_signed_offpeak_window"
    return {
        "request_allowed": request_allowed,
        "new_episode_allowed": new_episode_allowed,
        "reason": reason,
        "timezone": rule["timezone"],
        "local_time": local.isoformat(),
        "utc_time": local.astimezone(timezone.utc).isoformat(),
        "utc_offset": local.strftime("%z"),
        "window_end_local": window_end.isoformat() if window_end else None,
        "remaining_seconds": remaining_seconds,
        "official_rate_window": "peak" if official_peak else "offpeak",
    }


def _provider_connectivity_preflight() -> dict[str, Any]:
    """Run DNS, verified TLS, and unauthenticated HEAD without a model call."""
    host = "api.deepseek.com"
    started = monotonic_time.monotonic()
    try:
        resolved = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = [
            {"family": "IPv6" if item[0] == socket.AF_INET6 else "IPv4", "address": item[4][0]}
            for item in resolved
        ]
        family, _, _, _, sockaddr = resolved[0]
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(10)
        raw.connect(sockaddr)
        tls = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        tls_info = {"version": tls.version(), "cipher": tls.cipher()[0]}
        tls.close()
        connection = http.client.HTTPSConnection(host, 443, timeout=10, context=ssl.create_default_context())
        connection.request("HEAD", "/", headers={"User-Agent": "metamorph-public-calibration/1.0"})
        response = connection.getresponse()
        http_info = {"status": response.status, "reason": response.reason}
        connection.close()
        return {
            "ok": True,
            "dns": addresses,
            "tls": tls_info,
            "http": http_info,
            "elapsed_ms": round((monotonic_time.monotonic() - started) * 1000, 2),
        }
    except Exception as exc:  # credential-free preflight; no provider client or completion exists yet
        return {
            "ok": False,
            "exception_chain": _exception_chain(exc),
            "elapsed_ms": round((monotonic_time.monotonic() - started) * 1000, 2),
        }


def _provider_infra_failure(events: list[dict[str, Any]]) -> tuple[bool, list[dict[str, str]] | None]:
    """Classify only transport failures that occurred before any provider response."""
    failures = [event for event in events if event.get("type") == "provider.request_failed"]
    if not failures:
        return False, None
    chain = failures[-1].get("exception_chain")
    classes = {entry.get("class") for entry in chain or []}
    transport_classes = {
        "APIConnectionError", "APITimeoutError", "ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutException",
        "SSLError", "SSLCertVerificationError", "gaierror", "RemoteProtocolError", "ProtocolError",
        "NetworkError", "SocketError",
    }
    return bool(classes & transport_classes), chain


def _write_run_markdown(*, status: str, spec: CalibrationSpec | None, detail: dict[str, Any], report_path: Path) -> Path:
    """Write the one user-facing report for a completed or waiting batch."""
    lines = ["# Public Database Exploration calibration run", "", f"Status: **{status}**", "", "`study_kind=development_public_calibration`", "", "`included_in_primary_analysis=false`", ""]
    if spec is not None:
        lines += [
            f"- Configuration SHA-256: `{spec.pending_hash}`",
            f"- Task manifest SHA-256: `{spec.tasks_hash}`",
            f"- Authorization SHA-256: `{spec.authorization_hash}`",
            f"- Model: `{spec.config.exact_model_id}`",
        ]
    window = detail.get("time_window")
    if window:
        lines += ["", "## Time-window check", "", f"- Local time: `{window.get('local_time')}` (`UTC{window.get('utc_offset')}`)", f"- Decision: `{window.get('reason')}`", f"- Official rate window: `{window.get('official_rate_window')}`"]
    if detail.get("preflight") is not None:
        lines += ["", "## Credential-free provider preflight", "", f"- Result: `{json.dumps(detail['preflight'], ensure_ascii=False)}`"]
    if status == "WAITING_OFFPEAK":
        lines += ["", "No provider client was constructed and no provider request, evaluator request, or authorization budget was consumed. Re-run the same `--live` entry during the signed window; this process does not wait or schedule itself."]
    else:
        lines += ["", "## Batch summary", "", f"- Provider requests attempted: `{detail.get('provider_requests_attempted', detail.get('provider_requests_sent'))}`", f"- Provider responses completed: `{detail.get('provider_requests_completed', detail.get('provider_requests_sent'))}`", f"- Paid evaluator requests: `{detail.get('paid_evaluator_requests_sent')}`", f"- Infrastructure status: `{detail.get('infra_status', 'NOT_APPLICABLE')}`", f"- Ledger: `{json.dumps(detail.get('ledger', {}), ensure_ascii=False)}`", "", "## Episodes", ""]
        for episode in detail.get("episodes", []):
            lines.append(f"- `{episode.get('episode_id')}`: score={episode.get('native_score')}; correct={episode.get('native_accuracy')}; SQL={episode.get('sql_queries')}; files={episode.get('file_operations')}; requests={episode.get('model_requests_attempted', episode.get('model_requests'))} attempted / {episode.get('model_requests_completed', episode.get('model_requests'))} completed; tokens={episode.get('token_usage')}; stop={episode.get('runner_stop_reason')}; infra={episode.get('infra_status', 'NOT_APPLICABLE')}; offpeak-estimate={episode.get('offpeak_cost_estimate')}; peak-reference-estimate={episode.get('fixed_reference_peak_cost_estimate')}; artifacts={episode.get('snapshot_files')}")
            if episode.get("exception_chain"):
                lines.append(f"  - Desensitized exception chain: `{json.dumps(episode['exception_chain'], ensure_ascii=False)}`")
        lines += ["", "Provider charges are estimates from returned usage, not a provider billing statement. No cross-condition learning or significance conclusion is made from these six development episodes."]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    paths = {
        "entry": Path(__file__),
        "public_adapter": root / "experiments/experience_value/clbench_database_exploration.py",
        "live_bridge": root / "experiments/experience_value/live.py",
        "runner": root / "experiments/experience_value/runner.py",
        "workspace": root / "experiments/experience_value/workspace.py",
        "records": root / "experiments/experience_value/records.py",
        "loop": root / "graphs/loop.py",
        "provider_adapter": root / "llm/adapters.py",
        "provider_client": root / "llm/client.py",
    }
    return {name: _sha256(path) for name, path in paths.items()}


@dataclass(frozen=True)
class CalibrationSpec:
    pending: dict[str, Any]
    tasks: str
    authorization: dict[str, Any]
    pending_hash: str
    tasks_hash: str
    authorization_hash: str
    config: ToolOnlySmokeConfig
    prices: PriceSheet
    live_authorization: LiveAuthorization


def _tool_schema_hash() -> str:
    return hashlib.sha256(json.dumps(tool_only_schemas(ALLOWED_TOOLS), sort_keys=True).encode("utf-8")).hexdigest()


def _config(raw: dict[str, Any]) -> ToolOnlySmokeConfig:
    request = raw["request"]
    file_budget = raw["file_budget"]
    if request.get("automatic_retries") != 0 or request.get("sdk_implicit_retries") != 0:
        raise AuthorizationError("public calibration requires application and SDK retries to be zero")
    return ToolOnlySmokeConfig(
        provider=raw["provider"], exact_model_id=raw["exact_model_id"], base_url=raw["base_url"],
        api_key_env=raw["api_key_env_name_only"], max_input_characters=request.get("diagnostic_max_input_characters", request.get("max_input_characters", 0)),
        max_input_tokens_per_request=request["max_input_tokens_per_request"],
        max_output_tokens_per_request=request["max_output_tokens_per_request"],
        max_requests_per_episode=request["max_provider_requests_per_episode"],
        max_tool_calls_per_episode=request["max_total_tool_calls_per_episode"], timeout_seconds=request["request_timeout_seconds"],
        retries=request["automatic_retries"], max_transport_retries=request.get("max_transport_retries", 0), temperature=request["temperature"],
        thinking_enabled=request["thinking_enabled"], reasoning_effort=request["reasoning_effort"],
        episode_timeout_seconds=request["episode_timeout_seconds"], max_file_return_bytes=file_budget["max_file_return_bytes"],
        enforce_utf8_input_reservation=request.get("enforce_input_token_budget", request.get("enforce_utf8_input_reservation", False)),
        formal_input_cutoff_estimator=request.get("formal_input_cutoff", {}).get("name", request.get("input_token_estimator", {}).get("name", "calibrated_utf8_half_bytes_plus_chat_tool_overhead_v1")),
    )


def load_spec(pending_path: Path, tasks_path: Path, authorization_path: Path) -> CalibrationSpec:
    pending, tasks, authorization = _load_json(pending_path), tasks_path.read_text(encoding="utf-8"), _load_json(authorization_path)
    pending_hash, tasks_hash, authorization_hash = _sha256(pending_path), _sha256(tasks_path), _sha256(authorization_path)
    if pending.get("status") not in PENDING_STATUSES:
        raise AuthorizationError("public calibration pending configuration has an invalid status")
    if pending.get("study_kind") != "development_public_calibration" or pending.get("included_in_primary_analysis") is not False:
        raise AuthorizationError("public calibration analysis scope is invalid")
    if pending.get("interface", {}).get("allowed_tools") != sorted(ALLOWED_TOOLS):
        raise AuthorizationError("public calibration tool allowlist differs")
    if pending["interface"].get("tool_schema_hash") != _tool_schema_hash():
        raise AuthorizationError("public calibration tool schema hash differs from the actual loop schema")
    forbidden = {"python", "bash", "shell", "eval", "import", "arbitrary_code", "web"}
    if not forbidden <= set(pending["interface"].get("forbidden_capabilities", [])):
        raise AuthorizationError("public calibration forbidden capability list is incomplete")
    actual_episodes = tuple((item.get("order"), item.get("id"), item.get("task_id"), item.get("condition")) for item in pending.get("episodes", []))
    if actual_episodes != EXPECTED_EPISODES:
        raise AuthorizationError("public calibration must contain exactly the frozen six development episodes")
    if any(item.get("task_index") != int(item["task_id"]) - 1 for item in pending["episodes"]):
        raise AuthorizationError("public calibration task index does not match its actual public task ID")
    if pending["native_task"].get("variant") != "pre_migration" or pending["native_task"].get("max_sql_queries") != 15:
        raise AuthorizationError("public calibration must use the pre-migration native 15-query task")
    if pending["file_budget"].get("max_operations") != 8:
        raise AuthorizationError("public calibration must preserve the independent 8-operation file budget")
    request = pending["request"]
    if request.get("max_total_tool_calls_per_episode") != 23 or request.get("max_provider_requests_per_episode") != 24:
        raise AuthorizationError("public calibration request/tool envelope differs from the fixed 15+8+answer plan")
    expected_output_cap = 8192 if pending.get("status") in {
        "PENDING_PUBLIC_CALIBRATION_REVISION_V2_USER_SIGNOFF_NO_LIVE_CALLS",
        "PENDING_PUBLIC_CALIBRATION_REVISION_V3_USER_SIGNOFF_NO_LIVE_CALLS",
    } else 2048
    if request.get("max_output_tokens_per_request") != expected_output_cap:
        raise AuthorizationError(f"public calibration output cap is not the frozen {expected_output_cap}-token candidate")
    if request.get("enforce_input_token_budget", request.get("enforce_utf8_input_reservation")) is not True:
        raise AuthorizationError("public calibration must enforce its configured input-token reservation")
    if request.get("max_input_tokens_per_request") != 24000:
        raise AuthorizationError("public calibration must preserve the 24,000-token input budget")
    if pending.get("status") == "PENDING_PUBLIC_CALIBRATION_REVISION_V3_USER_SIGNOFF_NO_LIVE_CALLS":
        if request.get("request_timeout_seconds") != 120 or request.get("max_transport_retries") != 1:
            raise AuthorizationError("revision-v3 must use the frozen 120-second transport deadline and one retry")
        if request.get("transport_retry_policy", {}).get("only_pre_response_transport_failures") is not True:
            raise AuthorizationError("revision-v3 transport retry policy is incomplete")
    if request.get("input_token_estimator", {}).get("name") not in {None, "calibrated_utf8_half_bytes_plus_chat_tool_overhead_v1"}:
        raise AuthorizationError("public calibration input-token estimator differs from the reviewed implementation")
    formal_cutoff = request.get("formal_input_cutoff", {})
    if formal_cutoff and formal_cutoff.get("name") != FORMAL_INPUT_CUTOFF_ESTIMATOR_NAME:
        raise AuthorizationError("public calibration formal input cutoff differs from the reviewed implementation")
    if "F0" not in tasks or "U0" not in tasks or "1-F0" not in tasks or "3-U0" not in tasks:
        raise AuthorizationError("public calibration task manifest is incomplete")
    frozen = authorization.get("frozen_pending_config", {})
    frozen_tasks = authorization.get("frozen_task_manifest", {})
    if frozen.get("sha256") != pending_hash or frozen_tasks.get("sha256") != tasks_hash:
        raise AuthorizationError("public calibration authorization does not match its frozen config/task hashes")
    entry = authorization.get("entry_code", {})
    if entry.get("path") != "experiments/experience_value/public_calibration_run.py" or entry.get("sha256") != _sha256(Path(__file__)):
        raise AuthorizationError("public calibration authorization does not match the actual entry code")
    frozen_dependencies = authorization.get("code_dependencies", {})
    actual_dependencies = _code_hashes()
    if not frozen_dependencies or any(actual_dependencies.get(name) != digest for name, digest in frozen_dependencies.items()):
        raise AuthorizationError("public calibration authorization does not match the bound execution dependencies")
    if pending.get("offpeak_window") is not None:
        signed_window = authorization.get("offpeak_window", {})
        for key in ("timezone", "start_local", "end_local"):
            if signed_window.get(key) != pending["offpeak_window"].get(key):
                raise AuthorizationError("public calibration authorization does not match the signed off-peak window")
    authorization_keys = ["study_kind", "included_in_primary_analysis", "provider", "exact_model_id", "max_episodes", "max_provider_requests", "hard_cap_usd"]
    if pending.get("status") == "PENDING_PUBLIC_CALIBRATION_REVISION_V3_USER_SIGNOFF_NO_LIVE_CALLS":
        authorization_keys.append("max_provider_attempts")
    for key in authorization_keys:
        expected = pending["budget_proposal"].get("proposed_hard_cap_usd") if key == "hard_cap_usd" else pending.get(key)
        if key == "max_episodes":
            expected = len(EXPECTED_EPISODES)
        elif key == "max_provider_requests":
            expected = pending["budget_proposal"]["max_provider_requests"]
        elif key == "max_provider_attempts":
            expected = pending["budget_proposal"].get("max_provider_attempts", pending["budget_proposal"]["max_provider_requests"])
        if authorization.get(key) != expected:
            raise AuthorizationError(f"public calibration authorization differs at {key}")
    config = _config(pending)
    config.validate()
    price = pending["budget_proposal"]
    prices = PriceSheet(
        Decimal(price["input_cache_miss_usd_per_million"]), Decimal(price["output_usd_per_million"]),
        price["price_source"], price["price_checked_on"],
        Decimal(price["input_cache_hit_usd_per_million"]) if price.get("input_cache_hit_usd_per_million") is not None else None,
        Decimal(price["fixed_reference_input_cache_miss_usd_per_million"]) if price.get("fixed_reference_input_cache_miss_usd_per_million") is not None else None,
        Decimal(price["fixed_reference_output_usd_per_million"]) if price.get("fixed_reference_output_usd_per_million") is not None else None,
    )
    per_request = config.worst_case_request_cost(prices)
    if str(per_request) != price["worst_case_per_request_usd"]:
        raise AuthorizationError("public calibration per-request reservation does not match frozen limits")
    max_provider_attempts = price.get("max_provider_attempts", price["max_provider_requests"])
    if per_request * Decimal(max_provider_attempts) != Decimal(price["worst_case_total_usd"]):
        raise AuthorizationError("public calibration batch reservation does not match frozen limits")
    hard_cap = Decimal(price["proposed_hard_cap_usd"])
    if per_request * Decimal(max_provider_attempts) > hard_cap:
        raise AuthorizationError("public calibration reservation exceeds its proposed hard cap")
    live = LiveAuthorization(True, pending["provider"], pending["exact_model_id"], price["currency"], hard_cap, max_provider_attempts, price["price_source"], max_episodes=len(EXPECTED_EPISODES), episode_cap=len(EXPECTED_EPISODES))
    live.validate()
    return CalibrationSpec(pending, tasks, authorization, pending_hash, tasks_hash, authorization_hash, config, prices, live)


class NativeQueryTool:
    """Expose the public task's real QUERY action to the existing tool service."""

    def __init__(self, task: DatabaseExplorationAdapter) -> None:
        self.task = task
        self.successful_queries = 0
        self.failed_queries = 0

    def query(self, sql: str) -> str:
        feedback = self.task.query_sql(sql)
        self.successful_queries += 1
        if "ERROR:" in feedback:
            self.failed_queries += 1
        return feedback


def _live_dependency_versions() -> dict[str, str]:
    litellm = DatabaseExplorationAdapter.assert_real_litellm_available()
    try:
        importlib.import_module("openai")
        from importlib.metadata import version
        return {"litellm": litellm, "openai": version("openai")}
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("live public calibration requires the installed OpenAI-compatible provider dependency") from exc


def _tool_counts(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts = {name: {"proposed": 0, "dispatched": 0, "succeeded": 0, "failed": 0, "rejected": 0} for name in sorted(ALLOWED_TOOLS)}
    for event in events:
        name = event.get("tool")
        if name not in counts:
            continue
        if event["type"] == "tool.proposed":
            counts[name]["proposed"] += 1
        elif event["type"] == "tool.completed":
            counts[name]["dispatched"] += 1
            counts[name]["succeeded" if event.get("result", {}).get("ok") else "failed"] += 1
        elif event["type"] == "tool.rejected":
            counts[name]["rejected"] += 1
    return counts


def _events(records: RunRecords, attempt_id: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in records.path.read_text(encoding="utf-8").splitlines() if line and json.loads(line).get("attempt_id") == attempt_id]


def _require_live_authorization(spec: CalibrationSpec) -> None:
    expected_status = (
        "AUTHORIZED_FOR_EXACT_SIX_PUBLIC_CALIBRATION_OFFPEAK_EPISODES"
        if spec.pending.get("offpeak_window") is not None
        else "AUTHORIZED_FOR_EXACT_SIX_PUBLIC_CALIBRATION_EPISODES"
    )
    if spec.authorization.get("status") != expected_status:
        raise AuthorizationError("public calibration live execution requires a new separately signed authorization")
    if spec.authorization.get("live_requests_authorized") is not True:
        raise AuthorizationError("public calibration live execution is not authorized")
    if spec.authorization.get("real_model_requests_sent_under_this_authorization") != 0:
        raise AuthorizationError("public calibration authorization is already consumed")


def _event_usage(events: list[dict[str, Any]]) -> tuple[int, int, dict[str, int], Decimal, Decimal]:
    """Aggregate only completed responses; attempted requests are separate evidence."""
    started = len([event for event in events if event.get("type") == "provider.request_started"])
    finished = [event for event in events if event.get("type") == "provider.request_finished"]
    usage = {
        key: sum(int((event.get("usage") or {}).get(key, 0)) for event in finished)
        for key in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
    }
    offpeak = sum((Decimal(event["billed_cost_estimate"]) for event in finished if event.get("billed_cost_estimate") is not None), Decimal("0"))
    peak_reference = sum((Decimal(event["fixed_reference_peak_cost_estimate"]) for event in finished if event.get("fixed_reference_peak_cost_estimate") is not None), Decimal("0"))
    return started, len(finished), usage, offpeak, peak_reference


def _resource_stop_reason(exc: Exception | None, metrics: dict[str, Any] | None, answer: str | None, events: list[dict[str, Any]]) -> str | None:
    """Separate a local episode-resource stop from a batch safety failure."""
    if isinstance(exc, BudgetError) and str(exc) in {
        "input token estimate budget reached before provider request",
        "formal input token cutoff reached before provider request",
    }:
        return "input_token_budget_reached"
    if metrics is not None:
        reason = str(metrics.get("runner_stop_reason") or "")
        if reason in {
            "max_turns_reached", "latency budget exhausted", "input_token_budget_reached",
            "terminal_answer_unavailable_model_decision_budget_reached", "terminal_only_empty_answer",
            "terminal_only_tool_call_rejected",
        } or reason.endswith("_budget_reached"):
            return reason
    if not answer and any(event.get("stop_reason") == "length" for event in events if event.get("type") == "provider.request_finished"):
        return "output_token_limit_reached"
    return None


def _analysis_outcome(
    *, native_score: Any = None, evaluator_ran: bool = False, resource_stop_reason: str | None = None,
    infrastructure_failure: bool = False, system_failure: bool = False,
) -> dict[str, Any]:
    """Derive analysis-only status without overwriting native evaluation evidence."""
    if evaluator_ran:
        return {"analysis_score": native_score, "analysis_status": "EVALUATED_NATIVE"}
    if system_failure:
        return {"analysis_score": None, "analysis_status": "INVALID_SYSTEM"}
    if infrastructure_failure:
        return {"analysis_score": None, "analysis_status": "INVALID_INFRA"}
    if resource_stop_reason is not None:
        return {"analysis_score": 0, "analysis_status": "RESOURCE_LIMITED_FAILURE"}
    return {"analysis_score": None, "analysis_status": "NOT_EVALUATED"}


def _transport_retry_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    retry_events = [event for event in events if event.get("type", "").startswith("provider.transport_retry")]
    recovered = any(event.get("type") == "provider.transport_retry_recovered" for event in retry_events)
    return {
        "transport_retry_attempted": any(event.get("type") == "provider.transport_retry_started" for event in retry_events),
        "infra_recovered": recovered,
        "first_failure_chain": next((event.get("first_failure_chain") for event in retry_events if event.get("first_failure_chain")), None),
    }


def execute(*, pending_path: Path, tasks_path: Path, authorization_path: Path, output_root: Path, mode: str, adapter: ProviderAdapter | None = None) -> Path:
    """Run exactly six public development episodes through the existing loop."""
    if mode not in {"plan-only", "fake", "live"}:
        raise ValueError("mode must be plan-only, fake, or live")
    spec = load_spec(pending_path, tasks_path, authorization_path)
    if mode == "fake" and adapter is None:
        raise ValueError("fake mode requires an injected transport")
    if mode == "live":
        if adapter is not None:
            raise ValueError("live mode constructs only the configured real provider adapter")
        _require_live_authorization(spec)
        start_window = _offpeak_status(spec.pending, for_new_episode=True)
        if start_window.get("new_episode_allowed") is not True:
            return _write_run_markdown(
                status="WAITING_OFFPEAK", spec=spec, detail={"time_window": start_window},
                report_path=Path(__file__).resolve().parents[2] / "PUBLIC_CALIBRATION_RUN_REPORT.md",
            )
        preflight = _provider_connectivity_preflight()
        if not preflight["ok"]:
            records = RunRecords(output_root / f"preflight-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
            detail = {
                "provider_requests_attempted": 0, "provider_requests_completed": 0,
                "paid_evaluator_requests_sent": 0, "infra_status": "INFRA_FAILURE",
                "preflight": preflight, "time_window": start_window,
                "ledger": {"entries": [], "reserved_usd": "0", "settled_usd": "0", "billing_unknown": False},
                "episodes": [],
            }
            records.write_json("public_calibration_preflight.json", detail)
            return _write_run_markdown(status="INFRA_FAILURE", spec=spec, detail=detail, report_path=Path(__file__).resolve().parents[2] / "PUBLIC_CALIBRATION_RUN_REPORT.md")
        _live_dependency_versions()  # rejects the no-model shim before client construction
        client = build_authorized_client(spec.live_authorization, spec.config)
        if not isinstance(client.adapter, ProviderAdapter):
            raise RuntimeError("configured provider client lacks a normalized adapter")
        adapter = client.adapter
    runner = ExperimentRunner(output_root, receiver_config={
        "provider": spec.config.provider, "model": spec.config.exact_model_id,
        "base_url": spec.config.base_url, "thinking_enabled": spec.config.thinking_enabled,
        "reasoning_effort": spec.config.reasoning_effort, "temperature": spec.config.temperature,
        "max_input_tokens": spec.config.max_input_tokens_per_request,
        "max_output_tokens": spec.config.max_output_tokens_per_request,
        "request_timeout_seconds": spec.config.timeout_seconds,
        "episode_timeout_seconds": spec.config.episode_timeout_seconds,
        "retries": 0, "max_transport_retries": spec.config.max_transport_retries,
        "max_sql_queries": 15, "max_file_operations": 8,
        "max_requests": spec.config.max_requests_per_episode,
    })
    code_hashes = _code_hashes()
    manifest = {
        "study_kind": "development_public_calibration", "included_in_primary_analysis": False,
        "mode": mode, "run_id": runner.run_id, "generated_at": datetime.now(timezone.utc).isoformat(),
        "pending_sha256": spec.pending_hash, "tasks_sha256": spec.tasks_hash,
        "authorization_sha256": spec.authorization_hash, "code_hashes": code_hashes,
        "combined_code_hash": stable_hash(code_hashes), "episodes": spec.pending["episodes"],
        "provider_requests_sent": 0 if mode != "live" else None,
        "max_provider_attempts": spec.live_authorization.max_requests,
        "max_transport_retries": spec.config.max_transport_retries,
        "no_model_import_shim": False, "allowed_tools": sorted(ALLOWED_TOOLS),
    }
    runner.records.write_json("public_calibration_manifest.json", manifest)
    if mode == "plan-only":
        return runner.records.write_json("public_calibration_plan.json", {"requests_sent": 0, "episodes": spec.pending["episodes"], "manifest": manifest})
    assert adapter is not None
    upstream = Path(spec.pending["native_task"]["upstream_root"])
    data = upstream / "data/database_exploration"
    ledger = CostLedger(spec.live_authorization)
    report: dict[str, Any] = {"status": "RUNNING", "study_kind": "development_public_calibration", "included_in_primary_analysis": False, "mode": mode, "run_id": runner.run_id, "episodes": [], "provider_requests_sent": 0, "provider_requests_attempted": 0, "provider_requests_completed": 0, "paid_evaluator_requests_sent": 0, "no_model_import_shim": False, "infra_status": "NOT_APPLICABLE"}
    if mode == "live":
        report["preflight"] = preflight
    for episode in spec.pending["episodes"]:
        if mode == "live":
            episode_window = _offpeak_status(spec.pending, for_new_episode=True)
            if episode_window.get("new_episode_allowed") is not True:
                report["status"] = "STOPPED_OFFPEAK"
                report["stop_reason"] = episode_window["reason"]
                report["time_window"] = episode_window
                break
        public_task = DatabaseExplorationAdapter(
            upstream_root=upstream, db_path=data / "products.db", questions_path=data / "questions.json",
            records=runner.records, seed=spec.pending["native_task"]["seed"], max_queries_per_question=15,
            task_index=episode["task_index"], allow_no_model_import_shim=False,
        )
        view = public_task.reset()
        if view.task_id != episode["task_id"]:
            raise RuntimeError("upstream task ID differs from frozen calibration manifest")
        prepared = runner.prepare_task(episode["condition"], "development-calibration", episode["id"], task_text=view.prompt)
        database = NativeQueryTool(public_task)

        def _submit_before_consolidation(answer: str, _metrics: dict[str, Any]) -> None:
            if answer and not public_task.completed:
                # The upstream task is terminal, but its sanitized terminal
                # observation and evaluator material never return to the model.
                public_task.submit_answer(answer)

        try:
            answer, snapshot, metrics = run_tool_only_episode(
                prepared=prepared, manager=runner.manager, records=runner.records, database=database,
                adapter=adapter, ledger=ledger, config=spec.config, prices=spec.prices,
                transport_kind="fake_transport" if mode == "fake" else "live_provider",
                allowed_tool_names=ALLOWED_TOOLS,
                tool_call_limits={"query_sql": 15},
                tool_call_group_limits={"file_operations": (FILE_TOOLS, 8)},
                pre_request_check=(lambda: _offpeak_status(spec.pending)) if mode == "live" else None,
                stop_on_tool_limit_reached=True,
                terminal_only_after_tool_limit_names=(
                    {"query_sql"}
                    if spec.pending.get("terminal_answer_interface", {}).get("enabled", False)
                    else None
                ),
                enable_optional_consolidation=bool(spec.pending.get("optional_consolidation", {}).get("enabled", False)),
                before_consolidation=(
                    _submit_before_consolidation
                    if spec.pending.get("optional_consolidation", {}).get("enabled", False)
                    else None
                ),
            )
        except Exception as exc:  # preserve a stopped batch rather than auto-retrying it
            attempt_events = _events(runner.records, prepared.session.attempt_id)
            attempts, completed, token_usage, offpeak_cost, peak_reference_cost = _event_usage(attempt_events)
            infrastructure_failure, exception_chain = _provider_infra_failure(attempt_events)
            resource_reason = _resource_stop_reason(exc, None, None, attempt_events)
            retry_summary = _transport_retry_summary(attempt_events)
            report["provider_requests_attempted"] += attempts
            report["provider_requests_completed"] += completed
            report["provider_requests_sent"] += completed
            if resource_reason is not None:
                report["episodes"].append({
                    "episode_id": episode["id"], "task_id": view.task_id, "condition": episode["condition"],
                    "attempt_id": prepared.session.attempt_id, "conversation_id": prepared.session.conversation_id,
                    "model_requests": completed, "model_requests_attempted": attempts, "model_requests_completed": completed,
                    "runner_stop_reason": "PER_EPISODE_RESOURCE_STOP", "resource_stop_reason": resource_reason,
                    "infra_status": "NOT_INFRASTRUCTURE", "native_score": None, "native_accuracy": None,
                    "sql_queries": database.successful_queries, "file_operations": 0, "snapshot_files": [],
                    "token_usage": token_usage, "offpeak_cost_estimate": str(offpeak_cost),
                    "fixed_reference_peak_cost_estimate": str(peak_reference_cost),
                    "tool_counts": _tool_counts(attempt_events), "transport_retry": retry_summary,
                    **_analysis_outcome(resource_stop_reason=resource_reason),
                })
                report.setdefault("per_episode_resource_stops", 0)
                report["per_episode_resource_stops"] += 1
                continue
            report["status"] = "INFRA_FAILURE" if infrastructure_failure else "STOPPED"
            report["stop_reason"] = type(exc).__name__
            report["stop_detail"] = str(exc)
            report["time_window"] = _offpeak_status(spec.pending)
            report["infra_status"] = "INFRA_FAILURE" if infrastructure_failure else "NOT_INFRASTRUCTURE"
            report["episodes"].append({
                "episode_id": episode["id"], "task_id": view.task_id, "condition": episode["condition"],
                "attempt_id": prepared.session.attempt_id, "conversation_id": prepared.session.conversation_id,
                "model_requests": completed, "model_requests_attempted": attempts, "model_requests_completed": completed,
                "runner_stop_reason": type(exc).__name__, "infra_status": "INFRA_FAILURE" if infrastructure_failure else "NOT_INFRASTRUCTURE",
                "exception_chain": exception_chain, "native_score": None,
                "native_accuracy": None, "sql_queries": database.successful_queries, "file_operations": 0,
                "snapshot_files": [], "token_usage": token_usage, "offpeak_cost_estimate": str(offpeak_cost),
                "fixed_reference_peak_cost_estimate": str(peak_reference_cost),
                "transport_retry": retry_summary,
                **_analysis_outcome(infrastructure_failure=infrastructure_failure, system_failure=not infrastructure_failure),
            })
            break
        attempt_events = _events(runner.records, prepared.session.attempt_id)
        provider_attempts, provider_count, token_usage, offpeak_cost, peak_reference_cost = _event_usage(attempt_events)
        retry_summary = _transport_retry_summary(attempt_events)
        report["provider_requests_sent"] += provider_count
        report["provider_requests_attempted"] += provider_attempts
        report["provider_requests_completed"] += provider_count
        resource_reason = _resource_stop_reason(None, metrics, answer, attempt_events)
        if resource_reason is not None:
            report["episodes"].append({
                "episode_id": episode["id"], "task_id": view.task_id, "condition": episode["condition"],
                "attempt_id": prepared.session.attempt_id, "conversation_id": prepared.session.conversation_id,
                "prompt_hash": stable_hash(prepared.prompt), "request_config_hash": prepared.request_config_hash,
                "model_requests": provider_count, "model_requests_attempted": provider_attempts,
                "model_requests_completed": provider_count, "infra_status": "NOT_INFRASTRUCTURE",
                "runner_stop_reason": "PER_EPISODE_RESOURCE_STOP", "resource_stop_reason": resource_reason,
                "tool_counts": _tool_counts(attempt_events), "sql_queries": database.successful_queries,
                "sql_feedback_errors": database.failed_queries,
                "file_operations": sum(metrics["tool_calls_by_name"].get(name, 0) for name in FILE_TOOLS),
                "metrics": metrics, "native_score": None, "native_accuracy": None,
                "native_terminal_feedback_forwarded_to_model": False,
                "snapshot_hash": snapshot.content_hash, "snapshot_files": list(snapshot.files),
                "token_usage": token_usage, "offpeak_cost_estimate": str(offpeak_cost),
                "fixed_reference_peak_cost_estimate": str(peak_reference_cost),
                "request_time_windows": [event.get("received_time_window") for event in attempt_events if event.get("type") == "provider.request_finished"],
                "transport_retry": retry_summary,
                **_analysis_outcome(resource_stop_reason=resource_reason),
            })
            report.setdefault("per_episode_resource_stops", 0)
            report["per_episode_resource_stops"] += 1
            continue
        if not public_task.completed:
            public_task.submit_answer(answer)
        native = public_task.evaluate_native()
        report["episodes"].append({
            "episode_id": episode["id"], "task_id": view.task_id, "condition": episode["condition"],
            "attempt_id": prepared.session.attempt_id, "conversation_id": prepared.session.conversation_id,
            "prompt_hash": stable_hash(prepared.prompt), "request_config_hash": prepared.request_config_hash,
            "model_requests": provider_count, "model_requests_attempted": provider_attempts,
            "model_requests_completed": provider_count, "infra_status": "NOT_INFRASTRUCTURE", "tool_counts": _tool_counts(attempt_events),
            "sql_queries": database.successful_queries, "sql_feedback_errors": database.failed_queries,
            "file_operations": sum(metrics["tool_calls_by_name"].get(name, 0) for name in FILE_TOOLS),
            "runner_stop_reason": metrics.get("runner_stop_reason"), "metrics": metrics,
            "native_score": native.score, "native_accuracy": native.metrics.get("accuracy"),
            "native_terminal_feedback_forwarded_to_model": False,
            "snapshot_hash": snapshot.content_hash, "snapshot_files": list(snapshot.files),
            "token_usage": token_usage, "offpeak_cost_estimate": str(offpeak_cost),
            "fixed_reference_peak_cost_estimate": str(peak_reference_cost),
            "request_time_windows": [event.get("received_time_window") for event in attempt_events if event.get("type") == "provider.request_finished"],
            "transport_retry": retry_summary,
            **_analysis_outcome(native_score=native.score, evaluator_ran=True),
        })
    if report["status"] == "RUNNING":
        report["status"] = "COMPLETED"
    report["ledger"] = {"entries": ledger.entries, "reserved_usd": str(ledger.reserved), "settled_usd": str(ledger.settled), "billing_unknown": ledger.billing_unknown}
    json_report = runner.records.write_json("public_calibration_run.json", report)
    if mode == "live":
        _write_run_markdown(status=report["status"], spec=spec, detail=report, report_path=Path(__file__).resolve().parents[2] / "PUBLIC_CALIBRATION_RUN_REPORT.md")
    return json_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Public Database Exploration development-calibration entry")
    parser.add_argument("--pending", type=Path, default=Path("experiments/experience_value/public_calibration.offpeak.pending.json"))
    parser.add_argument("--tasks", type=Path, default=Path("experiments/experience_value/public_calibration.tasks.md"))
    parser.add_argument("--authorization", type=Path, default=Path("experiments/experience_value/public_calibration.offpeak.authorization.authorized_20260922.json"))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experience_value/public_calibration"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan-only", action="store_true")
    group.add_argument("--live", action="store_true")
    args = parser.parse_args()
    mode = "plan-only" if args.plan_only else "live"
    print(execute(pending_path=args.pending, tasks_path=args.tasks, authorization_path=args.authorization, output_root=args.output_root, mode=mode))


if __name__ == "__main__":
    main()
