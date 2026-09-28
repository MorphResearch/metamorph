"""No-model development acceptance for the official Database Exploration task.

The correct answer is read only in this researcher-side verifier and never
provided to ``DatabaseExplorationAdapter.reset()`` or its agent-visible view.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from experiments.experience_value.clbench_database_exploration import DatabaseExplorationAdapter
from experiments.experience_value.records import RunRecords


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_clbench_database_exploration.py <upstream-root> <output-root>")
    upstream, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    data = upstream / "data" / "database_exploration"
    records = RunRecords(output / "research_records")
    DatabaseExplorationAdapter.setup_database_exploration(upstream, records)
    questions = json.loads((data / "questions.json").read_text(encoding="utf-8"))
    development_question = questions[0]  # recorded development instance; never an unseen confirmation task

    def adapter() -> DatabaseExplorationAdapter:
        return DatabaseExplorationAdapter(
            upstream_root=upstream, db_path=data / "products.db", questions_path=data / "questions.json",
            records=records, seed=42,
        )

    wrong = adapter()
    wrong_view = wrong.reset()
    query_feedback = wrong.query_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    wrong.submit_answer("__development_wrong_answer__")
    wrong_result = wrong.evaluate_native()

    correct = adapter()
    correct_view = correct.reset()
    correct_feedback = correct.query_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    correct.submit_answer(str(development_question["answer"]))
    correct_result = correct.evaluate_native()

    payload = {
        "study_kind": "engineering_public_environment_development_acceptance",
        "included_in_primary_analysis": False,
        "provider_requests_sent": 0,
        "development_instance_id": wrong_view.task_id,
        "task_prompt_was_loaded": bool(wrong_view.prompt),
        "agent_view_excludes_db_path": "products.db" not in wrong_view.prompt,
        "legal_query": "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        "query_feedback_received": bool(query_feedback) and query_feedback == correct_feedback,
        "native_wrong_success": wrong_result.metrics["question_history"][0]["correct"],
        "native_correct_success": correct_result.metrics["question_history"][0]["correct"],
        "native_wrong_score": wrong_result.score,
        "native_correct_score": correct_result.score,
        "contact_scope": "researcher-side verifier read questions.json fields for development instance 1, including answer, to exercise native correct/incorrect scoring; no reference value entered an adapter prompt or agent-visible workspace.",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "development_acceptance.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if payload["native_wrong_success"] is not False or payload["native_correct_success"] is not True:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
