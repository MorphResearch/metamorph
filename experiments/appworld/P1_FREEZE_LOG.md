# P1 Freeze Log

- Frozen at source commit `c88d6af` on 2026-09-06, before any P1 model call.
- Manifest: `manifests/p1_dag_dev_v1.json`; 12 previously unrun public-instruction tasks, with four labels per family.
- Config: `configs/dag_p1_dev_v1.json`; DAGs G0--G3, seed 300, fixed budgets, DeepSeek-V4-Pro, peak cache-miss USD pricing, and lambda values 0.25/1.0/4.0.
- P1 is development-only. On completion, create exactly one `family_to_dag_profile.json`, commit it, and use that exact commit for P2/P3/E3. Do not regenerate it after any P3 result.
- Gate-1 results and infrastructure-invalid predecessors are tracked in `formal_run_registry.csv`; no old root may enter primary analysis.
