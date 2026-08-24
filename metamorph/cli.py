from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api import serve
from .config import Settings
from .events import EventLogger
from .model import PROVIDER_DEFAULTS, build_model
from .runtime import AgentRuntime
from .store import RunStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metamorph")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run one task synchronously")
    run.add_argument("task")
    run.add_argument("--workspace", type=Path, default=Path("."))
    run.add_argument("--data-dir", type=Path, default=Path(".metamorph"))
    run.add_argument("--provider", choices=["mock", "openai", "deepseek", "minimax", "claude", "glm", "sensenova"], default=None)
    run.add_argument("--model-mode", choices=["mock", "openai"], default=None, help="backwards-compatible alias for --provider")
    run.add_argument("--model", default=None)
    run.add_argument("--base-url", default=None)
    run.add_argument("--api-key-env", default=None)
    run.add_argument("--allow-write", action="store_true")

    server = subparsers.add_parser("serve", help="start the local HTTP API")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)
    server.add_argument("--data-dir", type=Path, default=Path(".metamorph"))
    server.add_argument("--provider", choices=["mock", "openai", "deepseek", "minimax", "claude", "glm", "sensenova"], default=None)
    server.add_argument("--model-mode", choices=["mock", "openai"], default=None, help="backwards-compatible alias for --provider")
    server.add_argument("--model", default=None)
    server.add_argument("--base-url", default=None)
    server.add_argument("--api-key-env", default=None)
    server.add_argument("--allow-write", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_environment(data_dir=args.data_dir)
    selected_provider = getattr(args, "provider", None) or getattr(args, "model_mode", None)
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
    if getattr(args, "allow_write", False):
        settings = Settings(**{**settings.__dict__, "allow_write": True})

    if args.command == "serve":
        serve(settings, host=args.host, port=args.port)
        return

    model = build_model(settings.provider, settings.model_name, settings.base_url, settings.api_key_env)
    store = RunStore(settings.data_dir)
    run_id = store.create(args.task, args.workspace.expanduser().resolve())
    store.update(run_id, "running")
    logger = EventLogger(settings.data_dir / "runs" / run_id)
    try:
        result = AgentRuntime(
            model=model,
            max_steps=settings.max_steps,
            max_read_bytes=settings.max_read_bytes,
            allow_write=settings.allow_write,
        ).run(args.task, args.workspace, logger, run_id)
        store.update(run_id, result["status"], result)
    except Exception as exc:
        result = {"run_id": run_id, "status": "failed", "error": str(exc)}
        store.update(run_id, "failed", result)
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
