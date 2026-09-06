from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from adapters.appworld_dag import DAGCompiler, DAGEdge, DAGExecutor, DAGNode, DAGSpec, Intervention, registered_dags


class DagRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.world = {"writes": 0}
        self.checkpoint_counter = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _checkpoint(self, name: str) -> dict[str, str]:
        self.checkpoint_counter += 1
        path = self.root / f"{self.checkpoint_counter}-{name}"
        path.mkdir()
        (path / "world.json").write_text(json.dumps(self.world, sort_keys=True), encoding="utf-8")
        return {"name": name, "path": str(path), "state_hash": (path / "world.json").read_text(encoding="utf-8")}

    def _runner(self, node: DAGNode, inputs: dict) -> dict:
        if node.operator in {"act", "repair"}:
            self.world["writes"] += 1
            return {"status": "COMPLETED", "node": node.id, "inputs": inputs}
        if node.operator == "check":
            return {"status": "VERIFIED", "node": node.id, "inputs": inputs}
        return {"status": "READY", "node": node.id, "inputs": inputs}

    def test_all_registered_graphs_compile_and_checkpoint_each_executed_node(self) -> None:
        for spec in registered_dags().values():
            result = DAGExecutor(runner=self._runner, checkpoint=self._checkpoint).execute(spec)
            self.assertEqual(spec.id, result["dag_id"])
            completed = {node_id for node_id, record in result["nodes"].items() if record["status"] == "completed"}
            self.assertEqual(completed, set(result["checkpoints"]))
            for record in result["nodes"].values():
                if record["status"] == "completed":
                    self.assertIn("artifact_hash", record)

    def test_compiler_rejects_cycle_and_invalid_parallel_write(self) -> None:
        cyclic = DAGSpec(
            "bad-cycle",
            (DAGNode("a", "inspect", output_type="PlanArtifact"), DAGNode("b", "join", {"x": "PlanArtifact"}, "PlanArtifact")),
            (DAGEdge("b", "a", "x", "PlanArtifact"),),
            (("a",), ("b",)),
        )
        with self.assertRaises(ValueError):
            DAGCompiler().compile(cyclic)
        write_parallel = DAGSpec(
            "bad-parallel",
            (DAGNode("a", "act", output_type="ExecutionArtifact", read_only=False), DAGNode("b", "inspect", output_type="PlanArtifact")),
            (),
            (("a", "b"),),
        )
        with self.assertRaises(ValueError):
            DAGCompiler().compile(write_parallel)

    def test_node_and_edge_interventions_do_not_mutate_baseline_checkpoint(self) -> None:
        spec = registered_dags()["G2"]
        baseline = DAGExecutor(runner=self._runner, checkpoint=self._checkpoint).execute(spec)
        source = Path(baseline["checkpoints"]["inspect_b"]["path"]) / "world.json"
        baseline_bytes = source.read_bytes()
        masked = DAGExecutor(runner=self._runner, checkpoint=self._checkpoint).execute(
            spec, Intervention(masked_edges=frozenset({("inspect_b", "join")}))
        )
        skipped = DAGExecutor(runner=self._runner, checkpoint=self._checkpoint).execute(
            spec, Intervention(skipped_nodes=frozenset({"inspect_b"}))
        )
        self.assertEqual(baseline_bytes, source.read_bytes())
        self.assertFalse(masked["nodes"]["join"]["inputs"]["b"]["valid"])
        self.assertEqual("skipped_intervention", skipped["nodes"]["inspect_b"]["status"])

    def test_topology_intervention_serializes_only_read_only_fork(self) -> None:
        result = DAGExecutor(runner=self._runner, checkpoint=self._checkpoint).execute(
            registered_dags()["G2"], Intervention(serialize_read_only=True)
        )
        self.assertEqual([["inspect_a"], ["inspect_b"], ["join"], ["act"], ["check"]], result["schedule"])
        with self.assertRaises(ValueError):
            DAGExecutor(runner=self._runner, checkpoint=self._checkpoint).execute(
                registered_dags()["G1"], Intervention(serialize_read_only=True)
            )

    def test_passthrough_control_is_recorded_without_masking(self) -> None:
        baseline = DAGExecutor(runner=self._runner, checkpoint=self._checkpoint).execute(registered_dags()["G2"])
        result = DAGExecutor(runner=self._runner, checkpoint=self._checkpoint).execute(
            registered_dags()["G2"], Intervention(passthrough_edges=frozenset({("inspect_b", "join")}))
        )
        self.assertEqual([['inspect_b', 'join']], result["intervention"]["passthrough_edges"])
        self.assertEqual("READY", result["nodes"]["join"]["inputs"]["b"]["status"])
        self.assertEqual(baseline["artifact_hashes"], result["artifact_hashes"])

    def test_g3_runs_repair_path_only_after_not_verified_check(self) -> None:
        checks = 0

        def repair_runner(node: DAGNode, inputs: dict) -> dict:
            nonlocal checks
            if node.operator in {"act", "repair"}:
                return {"status": "COMPLETED", "node": node.id}
            if node.operator == "check":
                checks += 1
                return {"status": "NOT_VERIFIED" if checks == 1 else "VERIFIED", "node": node.id}
            return {"status": "READY", "node": node.id}

        result = DAGExecutor(runner=repair_runner, checkpoint=self._checkpoint).execute(registered_dags()["G3"])
        self.assertEqual("completed", result["nodes"]["repair"]["status"])
        self.assertEqual("completed", result["nodes"]["final_check"]["status"])


if __name__ == "__main__":
    unittest.main()
