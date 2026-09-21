"""Write durable, explicitly ScriptedAgent-only E0 plumbing evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from .fixture import create_local_fixture
from .runner import ExperimentRunner
from .workspace import WorkspaceAccessError


def main() -> None:
    parser = argparse.ArgumentParser(description="offline ScriptedAgent memory-path smoke")
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/experience_value"))
    args = parser.parse_args()
    runner = ExperimentRunner(args.output_root, {"provider": "fixture", "model": "receiver-v0", "max_requests": 1})
    fixture = create_local_fixture(runner.root / "tool_service", max_queries=4)
    practice = runner.prepare_task("U1", "scripted-replicate-0", "local_fixture_practice_region_cluster")

    def practice_agent(runtime):
        rows = fixture.query("SELECT region, cluster FROM regions ORDER BY region")
        text = "observed rows via metered SQLite: " + repr(rows)
        runtime.write("/memory/observed_regions.txt", text.encode("utf-8"))
        return "saved a visible tool observation"

    _, source = runner.run_scripted(practice, practice_agent)
    runner.register_source("M_U", source)
    consumed: list[str] = []

    def memory_receiver(runtime):
        consumed.append(runtime.read("/memory/observed_regions.txt").decode("utf-8"))
        runtime.write("/work/probe_note.txt", b"probe-local output")
        return "read source artifact in a new session"

    _, memory_probe, prepared_memory = runner.run_probe("M_U", "local_fixture_probe_region_aggregate", memory_receiver)

    def empty_receiver(runtime):
        try:
            runtime.read("/memory/observed_regions.txt")
        except WorkspaceAccessError:
            return "empty memory could not retrieve source artifact"
        raise AssertionError("EMPTY probe unexpectedly read a source artifact")

    _, empty_probe, prepared_empty = runner.run_probe("EMPTY", "local_fixture_probe_region_aggregate", empty_receiver)
    summary = {
        "evidence_kind": "ScriptedAgent plumbing only; not a real-model learning result",
        "run_id": runner.run_id,
        "source_snapshot_hash": source.content_hash,
        "source_attempt_id": practice.session.attempt_id,
        "memory_probe_attempt_id": prepared_memory.session.attempt_id,
        "empty_probe_attempt_id": prepared_empty.session.attempt_id,
        "memory_was_read_in_new_session": bool(consumed),
        "source_hash_after_probes": source.content_hash,
        "memory_probe_snapshot_hash": memory_probe.content_hash,
        "empty_probe_snapshot_hash": empty_probe.content_hash,
        "metered_sql": {"success": fixture.successful_queries, "failed": fixture.failed_queries, "blocked": fixture.blocked_queries},
        "model_requests_sent": 0,
        "spend": "NOT_RUN",
    }
    runner.records.write_json("scripted_smoke_summary.json", summary)
    print(runner.root / "research_records" / "scripted_smoke_summary.json")


if __name__ == "__main__":
    main()
