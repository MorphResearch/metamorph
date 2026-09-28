#!/usr/bin/env bash
# Manual operator wrapper for the already-authorized experience_commit_v3 gate.
# Default mode sends zero provider requests. --run-live is deliberately explicit.

set -euo pipefail

case "${1:-}" in
  ""|--preflight)
    run_live=false
    ;;
  --run-live)
    run_live=true
    ;;
  *)
    echo "Usage: bash scripts/run_public_viability_gate_v3.sh [--preflight|--run-live]" >&2
    exit 64
    ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$repo_root/benchmarks/continual-learning-bench/.venv-database-exploration/bin/python"
pending="experiments/experience_value/public_viability_gate.experience_commit_v3.pending.json"
authorization="experiments/experience_value/public_viability_gate.experience_commit_v3.authorization.authorized_20260927T003029+0800.json"

if [[ ! -x "$python_bin" ]]; then
  echo "ERROR: required Python 3.13 interpreter is unavailable: $python_bin" >&2
  exit 1
fi

cd "$repo_root"

# This uses the exact frozen entry's helpers: hash binding, Asia/Shanghai
# window, credential-free DNS/TLS/HEAD, and real-LiteLLM/no-shim checks.
"$python_bin" - "$pending" "$authorization" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

from experiments.experience_value.clbench_database_exploration import DatabaseExplorationAdapter
from experiments.experience_value.public_calibration_run import _offpeak_status, _provider_connectivity_preflight
from experiments.experience_value.public_viability_gate_run import _load_spec

pending_path, authorization_path = map(Path, sys.argv[1:])
try:
    pending, authorization, _config, _prices = _load_spec(pending_path, authorization_path)
    authorization_ok = (
        authorization.get("status") == "AUTHORIZED_PUBLIC_VIABILITY_GATE_EXPERIENCE_COMMIT_V3"
        and authorization.get("live_requests_authorized") is True
        and authorization.get("real_model_requests_sent_under_this_authorization") == 0
    )
    window = _offpeak_status(pending, for_new_episode=True)
    preflight = _provider_connectivity_preflight()
    shim_ok = False
    shim_error = None
    if authorization_ok and window.get("new_episode_allowed") and preflight.get("ok"):
        try:
            DatabaseExplorationAdapter.assert_real_litellm_available()
            shim_ok = True
        except Exception as exc:  # report, never fall back to a shim
            shim_error = {"class": type(exc).__name__, "message": str(exc)}
    result = {
        "authorization_ok": authorization_ok,
        "time_window": window,
        "credential_free_preflight": preflight,
        "real_litellm_no_shim_ok": shim_ok,
        "no_shim_error": shim_error,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not (authorization_ok and window.get("new_episode_allowed") and preflight.get("ok") and shim_ok):
        raise SystemExit(2)
except Exception as exc:
    print(json.dumps({"operator_preflight_error": {"class": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(2)
PY

if [[ "$run_live" != true ]]; then
  echo "PRECHECK_OK: zero provider requests sent. Re-run with --run-live to execute the two frozen episodes."
  exit 0
fi

echo "PRECHECK_OK: launching the single already-authorized frozen viability gate."
exec "$python_bin" -m experiments.experience_value.public_viability_gate_run \
  --pending "$pending" \
  --authorization "$authorization" \
  --live
