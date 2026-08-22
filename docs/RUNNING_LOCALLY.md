# Running Metamorph locally

## Short answer

You do not need to rent a server for v0.1. Your Mac can run the control plane, API, SQLite database, logs, benchmark runner, and a sandboxed task worker. The language model can be called through an API, so the Mac does not need to hold model weights or have a discrete GPU.

The Mac is also suitable for a local-first prototype with a small quantized model, but the quality and speed will usually be lower than a hosted model for long-horizon coding and evolution tasks.

## Detected machine

The machine inspected on 2026-08-22 reports:

| Item | Detected value | Consequence |
|---|---|---|
| Model | MacBook Pro, `MacBookPro18,3` | Apple Silicon |
| Chip | Apple M1 Pro, 8 cores | Fine for Python services and bounded workers |
| RAM | 16 GB | Do not run several large local models or many workers simultaneously |
| Storage | 512 GB-class disk; 69 GiB currently free on `/` | Keep at least 50 GB free for environments, logs, and datasets |

The phrase “512 memory” normally means 512 GB SSD storage. macOS reports the installed RAM as 16 GB, not 512 GB.

## Recommended v0.1 resources

### Required

- Python 3.11 or newer;
- a virtual environment manager such as `uv` or `venv`;
- Git;
- SQLite;
- an API key for the chosen model provider;
- 10–20 GB free disk space for the project, environments, and test artifacts.

### Optional

- Docker or another OS-level sandbox;
- a local model runtime such as Ollama or MLX;
- a vector index, only after retrieval evaluation justifies it;
- a small web frontend.

## Base-model recommendation

For this project I recommend starting with a hosted model and keeping the model adapter provider-neutral.

| Role | Default | Why |
|---|---|---|
| Normal execution | `gpt-5.6-terra` | Good quality/cost balance for tool use and multi-step work |
| Difficult diagnosis/evolution | `gpt-5.6-sol` | Use selectively for hard failure analysis and candidate design |
| Routing, classification, memory gate | `gpt-5.6-luna` | Lower-cost, high-volume decisions |

These names and the balance between them follow the current official OpenAI model guidance. Use the Responses API for reasoning, tool calling, and multi-turn workflows, and pin a specific model version once experiments begin so benchmark results remain comparable. Availability, limits, and pricing depend on the account and can change; check the [official Models documentation](https://developers.openai.com/api/docs/models) and [model guidance](https://developers.openai.com/api/docs/guides/latest-model) before deployment.

The important design decision is not to hard-code the provider. Keep an interface like:

```python
class ModelAdapter(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...
```

Then a model comparison is an experiment, not a rewrite of the runtime.

## Do you need a server?

| Situation | Local Mac | Server |
|---|---:|---:|
| Personal development and research | Recommended | Not required |
| API model with one or a few concurrent runs | Enough | Not required |
| Always-on service while Mac is asleep/offline | Not enough | Useful |
| Several users or many concurrent workers | Not ideal | Recommended |
| Training or serving a large model locally | Not practical on 16 GB | GPU server required |
| Local small quantized model experiments | Possible | Not required |

Rent a server later when you need uptime, concurrency, a GPU, or remote access. Do not rent one merely to run the Python control loop.

## Minimum safety setup

Before enabling write or shell tools:

1. Restrict every path to a dedicated workspace.
2. Keep secrets outside the workspace and redact them from logs.
3. Use a command allowlist and resource limits.
4. Run candidate tools in an isolated environment.
5. Require confirmation for deletes, network access, dependency installation, and writes outside the task workspace.
6. Keep the evaluator, safety policy, and rollback mechanism outside the automatically mutable area.

Never expose the model-provider API key to a browser frontend. The browser should call the local/backend API, and only the backend should call the model provider.
