"""Command-line interface: `run` (one task) and `serve` (HTTP API)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graphs.agent import run_agent
from api.router import serve
from config import Settings
from state.events import EventLogger
from llm.client import PROVIDER_DEFAULTS, build_client
from state.store import RunStore
from multiagent.orchestrator import MultiAgentOrchestrator
from multiagent.models import BudgetPolicy


_PROVIDER_CHOICES = sorted(PROVIDER_DEFAULTS.keys())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metamorph")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run one task synchronously via the agent")
    run.add_argument("task")
    run.add_argument("--workspace", type=Path, default=Path("."))
    run.add_argument("--data-dir", type=Path, default=Path(".metamorph"))
    run.add_argument("--provider", choices=_PROVIDER_CHOICES, default=None)
    run.add_argument("--mode", choices=("single", "multiagent"), default=None)
    run.add_argument("--model", default=None)
    run.add_argument("--base-url", default=None)
    run.add_argument("--api-key-env", default=None)

    server = subparsers.add_parser("serve", help="start the local HTTP API")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)
    server.add_argument("--data-dir", type=Path, default=Path(".metamorph"))
    server.add_argument("--provider", choices=_PROVIDER_CHOICES, default=None)
    server.add_argument("--mode", choices=("single", "multiagent"), default=None)
    server.add_argument("--model", default=None)
    server.add_argument("--base-url", default=None)
    server.add_argument("--api-key-env", default=None)
    return parser


def _apply_provider_overrides(args: argparse.Namespace, settings: Settings) -> Settings:
    selected_provider = getattr(args, "provider", None)
    if selected_provider:
        provider_defaults = PROVIDER_DEFAULTS.get(selected_provider, {})
        settings = Settings(**{
            **settings.__dict__,
            "provider": selected_provider,
            "model_name": args.model or provider_defaults.get("model", settings.model_name),
            "base_url": args.base_url or provider_defaults.get("base_url", settings.base_url),
            "api_key_env": args.api_key_env or provider_defaults.get("api_key_env", settings.api_key_env),
        })
    if getattr(args, "model", None):
        settings = Settings(**{**settings.__dict__, "model_name": args.model})
    if getattr(args, "base_url", None):
        settings = Settings(**{**settings.__dict__, "base_url": args.base_url})
    if getattr(args, "api_key_env", None):
        settings = Settings(**{**settings.__dict__, "api_key_env": args.api_key_env})
    if getattr(args, "mode", None):
        settings = Settings(**{**settings.__dict__, "mode": args.mode})
    return settings


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_environment(data_dir=args.data_dir)
    settings = _apply_provider_overrides(args, settings)

    if args.command == "serve":
        serve(settings, host=args.host, port=args.port)
        return

    # `run` command: execute one task directly with the agent (no HTTP server).
    client = build_client(
        settings.provider,
        model_name=settings.model_name,
        base_url=settings.base_url,
        api_key_env=settings.api_key_env,
    )
    store = RunStore(settings.data_dir)
    run_id, conversation_id = store.create(args.task, args.workspace.expanduser().resolve())
    store.update(run_id, "running")
    run_dir = settings.data_dir / "runs" / run_id
    logger = EventLogger(run_dir)
    try:
        workspace = args.workspace.expanduser().resolve()
        if settings.mode == "multiagent":
            def run_role(prompt: str, agent_id: str) -> dict[str, object]:
                role_metrics: dict[str, object] = {}
                answer = run_agent(
                    client=client.client,
                    model_name=client.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    logger=EventLogger(run_dir / "agents" / agent_id),
                    data_dir=settings.data_dir,
                    workspace_root=workspace,
                    max_turns=settings.max_steps,
                    adapter=client.adapter,
                    metrics=role_metrics,
                    max_read_bytes=settings.max_read_bytes,
                    max_tool_calls=settings.max_tool_calls,
                    allow_write=settings.allow_write,
                )
                return {"answer": answer, "metrics": role_metrics}

            multi_result = MultiAgentOrchestrator(
                runner=run_role,
                data_dir=settings.data_dir,
                logger=logger,
                max_parallelism=settings.max_parallel_agents,
                budget_policy=BudgetPolicy(
                    max_total_tokens=settings.max_total_tokens,
                    max_latency_seconds=settings.max_latency_seconds,
                    max_tool_calls=settings.max_tool_calls,
                    max_causal_audits=settings.max_causal_audits,
                    allow_write=settings.allow_write,
                ),
            ).run(args.task, source_run=run_id)
            answer = multi_result["answer"]
        else:
            multi_result = None
            run_metrics: dict[str, object] = {}
            answer = run_agent(
                client=client.client,
                model_name=client.model_name,
                messages=[{"role": "user", "content": args.task}],
                logger=logger,
                data_dir=settings.data_dir,
                workspace_root=workspace,
                max_turns=settings.max_steps,
                adapter=client.adapter,
                metrics=run_metrics,
                max_read_bytes=settings.max_read_bytes,
                max_tool_calls=settings.max_tool_calls,
                max_total_tokens=settings.max_total_tokens,
                max_latency_seconds=settings.max_latency_seconds,
                allow_write=settings.allow_write,
            )
        result = {
            "run_id": run_id,
            "conversation_id": conversation_id,
            "status": "completed",
            "answer": answer,
            "provider": client.provider,
            "model": client.model_name,
            "mode": settings.mode,
        }
        if multi_result is None:
            result["metrics"] = run_metrics
        if multi_result is not None:
            result.update({k: v for k, v in multi_result.items() if k != "answer"})
        store.append_message(conversation_id, "user", args.task)
        store.append_message(conversation_id, "assistant", answer)
        logger.write_json("result.json", result)
        store.update(run_id, "completed", result)
    except Exception as exc:
        result = {"run_id": run_id, "status": "failed", "error": str(exc)}
        store.update(run_id, "failed", result)
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
