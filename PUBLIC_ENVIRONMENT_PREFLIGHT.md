# Continual Learning Bench public-environment preflight

Status: **NOT CONNECTED / BLOCKED FOR LOCAL EXECUTION**. This is independent
of the local tool-only smoke preparation.

## Remote source inspected, not installed

- Upstream: `https://github.com/pgasawa/continual-learning-bench`
- `main` resolved read-only on 2026-09-21 to commit
  `5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26`.
- Relevant Database Exploration source entries at that commit: task README
  blob `2d328f0d0c71ae8fa2e17bff07e5b2d6e2c334ee`, task implementation blob
  `09358652e3d97a6aacb00b9f2310eaff20fff38f`, and SQLite access helper blob
  `d9d054775f4f6affa61153c59b50496e2bc972ca`.
- Upstream requires Python >=3.13, `uv`, and local Docker. Its optional
  `database_exploration` dependency set uses `huggingface-hub`; the task setup
  downloads two SQLite files from its configured Hugging Face repository.
  Database Exploration has a normal `QUERY`/`ANSWER` interface, explicit
  query-regret reward, variants/schedules, and a task inspector.

Local facts: Metamorph's verified interpreter is Python 3.10.5; `uv` exists,
but `python3.13` and the `docker` command were not found. No upstream checkout,
dataset resource, data version, evaluation artifact, or `clbench` CLI exists
under this repository. No setup, image pull, model run, or benchmark command
was attempted.

## Minimal authorized next operation

Create a separate checkout outside the Metamorph `.venv`, pinned to the commit
above. Provision Python 3.13 and Docker first. Then, after approval, use the
upstream project's own isolated environment and only the Database Exploration
extra/setup—not `setup --all` and not a model benchmark:

```text
git clone https://github.com/pgasawa/continual-learning-bench <separate-path>
git -C <separate-path> checkout 5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26
cd <separate-path>
uv sync --extra database_exploration
clbench setup database_exploration
clbench inspect task database_exploration
```

Before any controlled query or evaluator call, record the downloaded resource
revision/checksums, Docker image IDs, task variant/schedule, evaluator entry
point, and the `clbench` version. The setup step itself downloads data and may
require a Hugging Face token or an approved mirror; it therefore awaits
authorization. No public-environment status is inferred from the local SQLite
fixture.

Sources inspected: [upstream README](https://github.com/pgasawa/continual-learning-bench/blob/5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26/README.md), [upstream pyproject](https://github.com/pgasawa/continual-learning-bench/blob/5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26/pyproject.toml), and [Database Exploration README](https://github.com/pgasawa/continual-learning-bench/blob/5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26/src/tasks/database_exploration/README.md).

