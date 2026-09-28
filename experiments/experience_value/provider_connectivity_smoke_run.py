"""One independently authorized, no-tools DeepSeek connectivity smoke."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.metadata
import json
import platform
import socket
import ssl
import time
from datetime import datetime, time as clock_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from llm.adapters import ProviderAdapter

from .live import MeteredConfiguredAdapter, PriceSheet, ToolOnlySmokeConfig, _exception_chain, build_authorized_client
from .records import AuthorizationError, CostLedger, LiveAuthorization, RunRecords


ROOT = Path(__file__).resolve().parents[2]
HOST = "api.deepseek.com"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _window(raw: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    rule = raw["offpeak_window"]
    zone = ZoneInfo(rule["timezone"])
    local = (now or datetime.now(timezone.utc)).astimezone(zone)
    start, end = clock_time.fromisoformat(rule["start_local"]), clock_time.fromisoformat(rule["end_local"])
    current = local.timetz().replace(tzinfo=None)
    in_signed = current >= start or current <= end
    peak = local.weekday() < 5 and (clock_time(9) <= current < clock_time(12) or clock_time(14) <= current < clock_time(18))
    return {
        "allowed": in_signed and not peak, "local_time": local.isoformat(), "utc_time": local.astimezone(timezone.utc).isoformat(),
        "utc_offset": local.strftime("%z"), "official_rate_window": "peak" if peak else "offpeak",
        "reason": "within_signed_offpeak_window" if in_signed and not peak else "outside_signed_window" if not in_signed else "official_peak_period",
    }


def _network_preflight() -> dict[str, Any]:
    """DNS, verified TLS, and unauthenticated HEAD only; never a completion."""
    started = time.monotonic()
    try:
        resolved = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
        addresses = [{"family": "IPv6" if item[0] == socket.AF_INET6 else "IPv4", "address": item[4][0]} for item in resolved]
        family, _, _, _, sockaddr = resolved[0]
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(10)
        raw.connect(sockaddr)
        tls = ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
        tls_info = {"version": tls.version(), "cipher": tls.cipher()[0]}
        tls.close()
        connection = http.client.HTTPSConnection(HOST, 443, timeout=10, context=ssl.create_default_context())
        connection.request("HEAD", "/", headers={"User-Agent": "metamorph-provider-connectivity-smoke/1.0"})
        response = connection.getresponse()
        http_info = {"status": response.status, "reason": response.reason}
        connection.close()
        return {"ok": True, "dns": addresses, "tls": tls_info, "http": http_info, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}
    except Exception as exc:  # no model request has been constructed here
        return {"ok": False, "exception_chain": _exception_chain(exc), "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}


def _environment() -> dict[str, Any]:
    versions = {}
    for package in ("openai", "httpx", "litellm", "certifi"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {"python": platform.python_version(), "openssl": ssl.OPENSSL_VERSION, "versions": versions}


def _write_report(payload: dict[str, Any]) -> Path:
    path = ROOT / "PUBLIC_PROVIDER_CONNECTIVITY_SMOKE_REPORT.md"
    lines = ["# Provider connectivity smoke", "", f"Status: **{payload['status']}**", "", "`study_kind=engineering_provider_connectivity_smoke`", "", "`included_in_primary_analysis=false`", "", f"- Preflight: `{json.dumps(payload['preflight'], ensure_ascii=False)}`", f"- Time window: `{json.dumps(payload['time_window'], ensure_ascii=False)}`", f"- Environment: `{json.dumps(payload['environment'], ensure_ascii=False)}`", f"- Provider request attempts: `{payload['provider_request_attempts']}`", f"- Result: `{json.dumps(payload.get('result'), ensure_ascii=False)}`", f"- Ledger: `{json.dumps(payload['ledger'], ensure_ascii=False)}`"]
    if payload["status"] == "SUCCESS":
        lines += ["", "READY_TO_REAUTHORIZE_PUBLIC_CALIBRATION"]
    elif payload["status"] == "BLOCKED_PROVIDER_PATH":
        lines += ["", "BLOCKED_PROVIDER_PATH"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def execute(pending_path: Path, authorization_path: Path, output_root: Path) -> Path:
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    if pending["status"] != "PENDING_PROVIDER_CONNECTIVITY_SMOKE_USER_SIGNOFF":
        raise AuthorizationError("invalid smoke pending status")
    if authorization.get("status") != "AUTHORIZED_FOR_ONE_PROVIDER_CONNECTIVITY_SMOKE" or authorization.get("requests_sent") != 0:
        raise AuthorizationError("smoke authorization is absent or consumed")
    if authorization.get("pending_sha256") != _sha256(pending_path) or authorization.get("entry_sha256") != _sha256(Path(__file__)):
        raise AuthorizationError("smoke authorization hash mismatch")
    request, budget = pending["request"], pending["budget"]
    config = ToolOnlySmokeConfig(pending["provider"], pending["model"], pending["base_url"], pending["api_key_env"], request["max_input_characters"], request["max_input_tokens"], request["max_output_tokens"], 1, 0, request["timeout_seconds"], 0, None, True, "low", enforce_utf8_input_reservation=True)
    prices = PriceSheet(Decimal(budget["input_cache_miss_usd_per_million"]), Decimal(budget["output_usd_per_million"]), budget["price_source"], budget["price_checked_at"], Decimal(budget["input_cache_hit_usd_per_million"]))
    if str(config.worst_case_request_cost(prices)) != budget["worst_case_request_usd"] or config.worst_case_request_cost(prices) > Decimal(budget["hard_cap_usd"]):
        raise AuthorizationError("smoke cost reservation differs from its frozen cap")
    window, preflight, environment = _window(pending), _network_preflight(), _environment()
    records = RunRecords(output_root / f"smoke-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    base = {"study_kind": pending["study_kind"], "included_in_primary_analysis": False, "pending_sha256": _sha256(pending_path), "authorization_sha256": _sha256(authorization_path), "time_window": window, "preflight": preflight, "environment": environment, "provider_request_attempts": 0, "ledger": {"entries": [], "billing_unknown": False}, "result": None}
    if not window["allowed"] or not preflight["ok"]:
        base["status"] = "BLOCKED_PROVIDER_PATH" if not preflight["ok"] else "WAITING_OFFPEAK"
        records.write_json("provider_connectivity_smoke.json", base)
        return _write_report(base)
    live = LiveAuthorization(True, pending["provider"], pending["model"], "USD", Decimal(budget["hard_cap_usd"]), 1, budget["price_source"], max_episodes=1, episode_cap=1)
    client = build_authorized_client(live, config)
    if not isinstance(client.adapter, ProviderAdapter):
        raise RuntimeError("configured client has no provider adapter")
    ledger = CostLedger(live)
    guarded = MeteredConfiguredAdapter(client.adapter, config, prices, ledger, records, "provider-connectivity-smoke", pre_request_check=lambda: {"request_allowed": _window(pending)["allowed"], **_window(pending)})
    try:
        response = guarded.complete(model_name=config.exact_model_id, messages=[{"role": "user", "content": "Reply with exactly OK."}], tools=[])
        result = {"response_present": True, "actual_model_id": response.request_metadata.get("response_model"), "finish_reason": response.stop_reason, "usage": response.usage, "content": response.content, "latency_note": "see provider request event timestamps"}
        status = "SUCCESS"
    except Exception as exc:
        failures = [json.loads(line) for line in records.path.read_text(encoding="utf-8").splitlines() if json.loads(line).get("type") == "provider.request_failed"]
        result = {"response_present": False, "exception_chain": failures[-1].get("exception_chain") if failures else _exception_chain(exc), "deepest_layer": "unknown_without_transport_cause", "usage": None}
        status = "BLOCKED_PROVIDER_PATH"
    base.update({"status": status, "provider_request_attempts": len(ledger.entries), "ledger": {"entries": ledger.entries, "reserved_usd": str(ledger.reserved), "settled_usd": str(ledger.settled), "billing_unknown": ledger.billing_unknown}, "result": result})
    records.write_json("provider_connectivity_smoke.json", base)
    return _write_report(base)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pending", type=Path, default=Path("experiments/experience_value/provider_connectivity_smoke.pending.json"))
    parser.add_argument("--authorization", type=Path, default=Path("experiments/experience_value/provider_connectivity_smoke.authorization.authorized_20260922.json"))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experience_value/provider_connectivity_smoke"))
    args = parser.parse_args()
    print(execute(args.pending, args.authorization, args.output_root))


if __name__ == "__main__":
    main()
