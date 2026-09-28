# E0 local recovery / backup manifest

This list is a backup checklist, not an archive and not a request to copy
credentials or unrelated user data.

1. Preserve source and configuration: `experiments/experience_value/`,
   `DAY1_REPORT.md`, `REPO_PREFLIGHT.md`, `LIVE_SMOKE_PREPARATION.md`,
   `PUBLIC_ENVIRONMENT_PREFLIGHT.md`, and this manifest.
2. Preserve the Git commit ID `b5ef5216bd8eceefdee5c0485583e6de4850002b`
   plus a patch or content hash for these paths; Git HEAD alone is insufficient
   while E0 files are uncommitted. The current E0 content-set SHA-256 over
   `experiments/experience_value/`, `graphs/loop.py`, and `llm/adapters.py` is
   `6a600de18b740be510d47e801a078113b2a4cb608d958002064921186f72d29d`.
   The verified local dependency tuple is Python 3.10.5, `pydantic 2.13.5`,
   and `openai 3.6.0`.
3. Preserve local evidence under `artifacts/experience_value/`, including
   `research_records/events.jsonl`, `scripted_smoke_summary.json`,
   `plan_only.json`, and any future `ledger_<attempt_id>.json`. This path is
   ignored to prevent accidental commits, not to discard evidence.
4. Exclude `.env`, credentials, authorization headers, user home directories,
   full benchmark datasets, and unrelated worktree changes. Record only
   credential-variable names and presence, never values.
5. For a future public checkout, separately preserve upstream commit, lockfile,
   resource checksums/revisions, image IDs, and evaluator version after those
   resources have actually been acquired.
