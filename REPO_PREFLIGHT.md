# E0 repository preflight — 2026-09-21

Status: **PARTIAL**. The repository and relevant reusable capabilities were
verified; the public benchmark and a suitable untrusted-code sandbox were not.

- Git root: `/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph`.
  HEAD at inspection: `31e568a1f9f04582ea1db67806c2cc739187ce3f`.
- No applicable `AGENTS.md` was found outside the intentionally excluded
  vendored/upload trees. Repository instructions used: root `README.md`,
  `pyproject.toml`, and the supplied Day-1 package under
  `Metamorph_Day1_Codex_Guide_20260921/`.
- Pre-existing dirty files were preserved: `README.md`,
  `docs/zh-CN/NEXT_CHAT_EXECUTION_CHECKLIST.md`,
  `experiments/appworld/README.md`, and
  `experiments/appworld/formal_run_registry.csv`, plus existing untracked
  research material. This E0 work is isolated in `experiments/experience_value/`
  with two new root reports and a narrow `.gitignore` rule for local evidence.
- Reusable code found: `graphs.agent.run_agent` / `graphs.loop.run_loop` for a
  single-agent tool loop; `llm.client.build_client` and `llm.providers` for
  provider selection; `tools.base` plus `tools.fileops` / `tools.document` for
  scoped workspace tools; `state.events.EventLogger` and `state.store.RunStore`
  for append-only events and runs; agent-loop token/tool/latency limits.
- E0 does **not** invoke or refactor those global paths. It reuses their
  separation-of-concerns approach in a local runner because the existing
  workspace is one directory rather than distinct `/memory` and `/work`, and
  the app conversation store intentionally supports continuity.
- Interpreters: system `python` is 3.11 but lacks `pydantic`; `.venv/bin/python`
  is Python 3.10.5 with `pydantic 2.13.5` and was used for verified tests.
  `pytest` is absent from that virtual environment; standard-library
  `unittest` is sufficient and was used.
- Candidate credential variable *presence only*: `DEEPSEEK_API_KEY` and
  `ZAI_API_KEY` were configured. No values were read, copied, or logged. Their
  presence is not authorization for a paid E0 run.
- No local CL-Bench / Continual Learning Bench Database Exploration source or
  installed integration was found in the scoped search. Public integration is
  therefore blocked; only the synthetic `local_fixture` is used.
- There is no verified OS/container sandbox for arbitrary agent-authored code.
  `code_execution_isolation=BLOCKED`; E0 does not execute agent code on the
  host.

