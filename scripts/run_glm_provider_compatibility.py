#!/usr/bin/env python3
"""Run the isolated GLM provider-protocol compatibility gate.

This intentionally exercises no AppWorld task. It checks only the frozen
tool/artifact protocol before any provider-specific benchmark validation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters.appworld_contracts import ExecutorArtifact, SCHEMA_VERSION, VerifierArtifact, validate_artifact
from llm.client import build_client


def contract_instruction(contract: type[Any]) -> str:
    return (
        "Return exactly one JSON object, with no markdown or surrounding prose. "
        "It must validate against this JSON Schema:\n"
        + json.dumps(contract.model_json_schema(), ensure_ascii=False, sort_keys=True)
    )


def classify(content: str, contract: type[Any]) -> dict[str, Any]:
    """Classify exact-JSON and local-schema outcomes without forgiving output."""

    text = str(content or "")
    result: dict[str, Any] = {
        "content_chars": len(text), "empty": not bool(text.strip()), "valid_json": False,
        "schema_valid": False, "malformed": False, "truncated": False, "extra_text": False,
    }
    if result["empty"]:
        return result
    stripped = text.strip()
    try:
        decoder = json.JSONDecoder()
        _, end = decoder.raw_decode(stripped)
        result["extra_text"] = bool(stripped[end:].strip())
        result["valid_json"] = not result["extra_text"]
    except json.JSONDecodeError as exc:
        result["malformed"] = True
        lowered = str(exc).lower()
        result["truncated"] = "unterminated" in lowered or exc.pos >= max(0, len(stripped) - 2)
    artifact, errors = validate_artifact(text, contract)
    result["schema_valid"] = artifact is not None
    result["validation_errors"] = errors
    if artifact is not None:
        result["artifact_status"] = getattr(artifact, "status", None)
    return result


def usage(response: Any) -> dict[str, int]:
    value = dict(getattr(response, "usage", {}) or {})
    return {key: int(value.get(key, 0) or 0) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}


def summarize(records: list[dict[str, Any]]) -> dict[str, int]:
    fields = ("valid_json", "schema_valid", "empty", "malformed", "truncated", "extra_text")
    return {field: sum(bool(record.get(field)) for record in records) for field in fields}


def call(adapter: Any, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
    options: dict[str, Any] = {"temperature": 0.0, "max_tokens": 1024, "timeout": 90.0}
    if not tools:
        options["response_format"] = {"type": "json_object"}
    return adapter.complete_configured(
        model_name=model, messages=messages, tools=tools, generation_options=options,
    )


def artifact_trials(adapter: Any, model: str, contract: type[Any], prompt: str, repeats: int) -> list[dict[str, Any]]:
    rows = []
    for index in range(repeats):
        response = call(adapter, model, [{"role": "user", "content": prompt + "\n\n" + contract_instruction(contract)}], [])
        row = {"trial": index + 1, **classify(response.content, contract), "usage": usage(response)}
        rows.append(row)
    return rows


def continuation_trials(adapter: Any, model: str, repeats: int) -> list[dict[str, Any]]:
    tool = {
        "type": "function",
        "function": {
            "name": "lookup", "description": "Returns a deterministic test record.",
            "parameters": {
                "type": "object", "properties": {"key": {"type": "string"}},
                "required": ["key"], "additionalProperties": False,
            },
        },
    }
    rows = []
    for index in range(repeats):
        initial = [{
            "role": "user",
            "content": "Call lookup exactly once with key='alpha'. Do not answer before the tool result.",
        }]
        first = call(adapter, model, initial, [tool])
        calls = list(first.tool_calls or [])
        structured = len(calls) == 1 and bool(calls[0].get("id")) and calls[0].get("name") == "lookup"
        arguments_valid = False
        if structured:
            try:
                arguments_valid = isinstance(json.loads(str(calls[0].get("arguments", ""))), dict)
            except json.JSONDecodeError:
                pass
        pairing_valid = False
        final: Any | None = None
        if structured and arguments_valid:
            call_id = str(calls[0]["id"])
            assistant = {
                "role": "assistant", "content": first.content or None,
                "tool_calls": [{
                    "id": call_id, "type": "function",
                    "function": {"name": "lookup", "arguments": str(calls[0]["arguments"])},
                }],
            }
            tool_result = {"role": "tool", "tool_call_id": call_id, "content": '{"value":"alpha-record"}'}
            pairing_valid = assistant["tool_calls"][0]["id"] == tool_result["tool_call_id"]
            final_messages = [
                *initial, assistant, tool_result,
                {"role": "user", "content": "Tool interaction is complete. " + contract_instruction(ExecutorArtifact)},
            ]
            final = call(adapter, model, final_messages, [])
            outcome = classify(final.content, ExecutorArtifact)
        else:
            outcome = classify("", ExecutorArtifact)
        rows.append({
            "trial": index + 1, "structured_tool_calls": structured, "arguments_json": arguments_valid,
            "tool_call_id_pairing": pairing_valid, "first_usage": usage(first),
            "final_usage": usage(final) if final is not None else {}, **outcome,
        })
    return rows


def write_failure_audit(output_dir: Path, model: str, stage: str, exc: Exception) -> None:
    """Persist provider failures instead of leaving an ambiguous empty root."""

    payload = {
        "schema_version": "glm-provider-compatibility.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": "Z.AI", "model": model, "phase_1_pass": False,
        "failure_stage": stage, "failure_type": type(exc).__name__, "failure": str(exc),
    }
    (output_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "GLM47_PROVIDER_COMPATIBILITY_AUDIT.md").write_text(
        "# GLM-5.3 Provider Compatibility Audit\n\n"
        "- Phase 1 pass: **False**\n"
        f"- Failure stage: `{stage}`\n"
        f"- Failure type: `{type(exc).__name__}`\n"
        f"- Failure: `{exc}`\n\n"
        "No AppWorld task was called.\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="glm-5.3")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    if args.repeats != 10:
        raise ValueError("provider compatibility gate is frozen at exactly 10 repeats per microtest")
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to overwrite provider validation output: {args.output_dir}")
    args.output_dir.mkdir(parents=True)

    try:
        bundle = build_client("glm", args.model, "https://api.z.ai/api/paas/v4/", "ZAI_API_KEY")
        adapter = bundle.adapter
        assert adapter is not None
        verifier_rows = artifact_trials(
            adapter, args.model, VerifierArtifact,
            "Evidence: the requested state was observed and matches the criterion. Return VERIFIED with one passing check.",
            args.repeats,
        )
        executor_rows = artifact_trials(
            adapter, args.model, ExecutorArtifact,
            "Evidence: fake lookup returned alpha-record. Return COMPLETED with one successful lookup action.",
            args.repeats,
        )
        continuation_rows = continuation_trials(adapter, args.model, args.repeats)
        not_verified_rows = artifact_trials(
            adapter, args.model, VerifierArtifact,
            "Evidence is insufficient to prove task success. Return NOT_VERIFIED with concrete non-empty repair_instructions.",
            args.repeats,
        )
    except Exception as exc:  # A provider error is an explicit compatibility failure.
        write_failure_audit(args.output_dir, args.model, "phase_1_provider_call", exc)
        print(json.dumps({"phase_1_pass": False, "output_dir": str(args.output_dir), "error": type(exc).__name__}, indent=2))
        return
    for row in not_verified_rows:
        row["not_verified_valid"] = row.get("artifact_status") == "NOT_VERIFIED" and row.get("schema_valid")

    payload = {
        "schema_version": "glm-provider-compatibility.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": "Z.AI", "model": args.model, "base_url": "https://api.z.ai/api/paas/v4/",
        "api_key_environment_variable": "ZAI_API_KEY", "repeats": args.repeats,
        "artifact_finalization": {"verifier": verifier_rows, "executor": executor_rows},
        "function_calling_continuation": continuation_rows,
        "not_verified": not_verified_rows,
    }
    payload["summaries"] = {
        "verifier": summarize(verifier_rows), "executor": summarize(executor_rows),
        "continuation_final": summarize(continuation_rows), "not_verified": summarize(not_verified_rows),
        "continuation_structured_tool_calls": sum(row["structured_tool_calls"] for row in continuation_rows),
        "continuation_arguments_json": sum(row["arguments_json"] for row in continuation_rows),
        "continuation_pairing": sum(row["tool_call_id_pairing"] for row in continuation_rows),
        "not_verified_correct": sum(row["not_verified_valid"] for row in not_verified_rows),
    }
    requirements = {
        "verifier_schema_valid": args.repeats,
        "executor_schema_valid": args.repeats,
        "continuation_final_schema_valid": args.repeats,
        "continuation_structured_tool_calls": args.repeats,
        "continuation_arguments_json": args.repeats,
        "continuation_pairing": args.repeats,
        "not_verified_correct": args.repeats,
    }
    observed = {
        "verifier_schema_valid": payload["summaries"]["verifier"]["schema_valid"],
        "executor_schema_valid": payload["summaries"]["executor"]["schema_valid"],
        "continuation_final_schema_valid": payload["summaries"]["continuation_final"]["schema_valid"],
        "continuation_structured_tool_calls": payload["summaries"]["continuation_structured_tool_calls"],
        "continuation_arguments_json": payload["summaries"]["continuation_arguments_json"],
        "continuation_pairing": payload["summaries"]["continuation_pairing"],
        "not_verified_correct": payload["summaries"]["not_verified_correct"],
    }
    payload["phase_1_pass"] = observed == requirements
    (args.output_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# GLM-5.3 Provider Compatibility Audit", "",
        f"- Provider: Z.AI", f"- Model: `{args.model}`", f"- Phase 1 pass: **{payload['phase_1_pass']}**", "",
        "| check | observed | required |", "| --- | ---: | ---: |",
        *[f"| {name} | {observed[name]} | {required} |" for name, required in requirements.items()],
        "", "The full per-trial record is in `results.json`. No AppWorld task was called.",
    ]
    (args.output_dir / "GLM47_PROVIDER_COMPATIBILITY_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"phase_1_pass": payload["phase_1_pass"], "output_dir": str(args.output_dir)}, indent=2))


if __name__ == "__main__":
    main()
