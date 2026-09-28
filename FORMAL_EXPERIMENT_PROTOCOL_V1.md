# Formal public Database Exploration protocol v1

Status: **frozen pending protocol; `live_requests_authorized=false`; no formal provider request has been sent.**

The completed calibration and viability stages are closed. Database Exploration IDs 1–6 are permanently `development_contacted=true` and `formal_eligible=false`. Their traces, artifacts, RAW trajectories, frozen snapshots, and all calibration/viability records cannot be mounted into a formal source, probe, receiver resource, or formal analysis input. Historical evidence remains preserved.

## Fixed data split

The upstream fixed commit is `5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26`, pre-migration variant. `questions.json` SHA-256 is `f98e515c14b74f4d30c29401fb79cca9ceeb15fe9ee2432b10265a4a649d1771`; `products.db` SHA-256 is `edf8ee80ff125de0bfd6c37a1d185efa9e3037ce28eb1bd1d32ae0829bd264a6`.

- Formal sources: original-order task IDs 7–14 (8 tasks).
- Formal probes: original-order task IDs 15–20 (6 tasks).

The split was selected mechanically by original order, after verifying IDs and public category/dependency metadata but without recording any formal task text, answer, reference SQL, or evaluator reference material in these protocol files. The complete safe metadata and source execution order are in [FORMAL_SOURCE_MANIFEST_V1.json](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/FORMAL_SOURCE_MANIFEST_V1.json); the probe order is in [FORMAL_RECEIVER_MANIFEST_V1.json](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/FORMAL_RECEIVER_MANIFEST_V1.json).

## Source conditions and order

There are 32 source episodes: each of F0, U0, F1, U1 receives tasks 7→14 in that order. F0/U0 start every task with empty memory and archive their experience without inheritance. F1/U1 start task 7 empty, then clone only prior immutable experience files produced under the same condition. A task can add its allocated `experience_NNN.md` but cannot change an inherited file.

The fixed interleaving is exactly the 32-token `execution_order` in the source manifest: four rotating condition orders for tasks 7–10, repeated for tasks 11–14. No task error or resource-limited result may alter that order or be selectively rerun.

All source conditions share model, task input, read-only SQL, 15-SQL limit, 8-file-operation limit, 24 main decisions, 24,000-token formal cutoff, 8,192 output cap, 120-second request timeout, 1,080-second episode timeout, retry rules, evaluator, consolidation prompt, deterministic commit, permissions, and cost accounting. F/U differs only in the already-frozen execution-organization prompts.

## Experience and RAW

Every source performs one tool-less experience-generation decision before evaluator feedback. Non-empty provider-visible text other than exact `NO_MEMORY` is committed byte-for-byte to the condition-local, episode-unique immutable `/memory/experience_NNN.md`; no text is edited, summarized, or repaired. `NO_MEMORY`, empty content, and an attempted tool call remain recorded outcomes. Provenance records task/condition/response ID, visible-content/file hashes, bytes, snapshot hash, and `evaluator_visible=false`.

Each source also archives a research-only pre-consolidation RAW trajectory. `RAW_F` is the task-order concatenation of all eight F0 agent-visible trajectories; `RAW_U` is the same for U0. The exact aggregation excludes evaluator output, references, researcher logs, and consolidation output. RAW is immutable, not auto-mounted, and only available to the preregistered receiver conditions below.

## Common receiver

There are 30 E* probe episodes: 6 probe tasks × five resources (`EMPTY`, `M_F`, `M_U`, `RAW_F`, `RAW_U`). `M_F` and `M_U` are respectively the final F1/U1 accumulated snapshots. `RAW_F` and `RAW_U` mount exactly one immutable aggregate file. Each probe gets a new session and an independent resource clone; its writes never propagate back to sources or other probes.

The receiver prompt, tools, and shared task budget are frozen in the receiver manifest. It has no consolidation step. The 30-token probe-major order is fixed there and cannot depend on source outcomes.

## Outcomes and stop semantics

Primary: answer correctness/accuracy. Secondary: upstream native `TaskResult.score` and normalized-regret-derived score. Efficiency, experience, receiver-use, and failure fields are exactly enumerated in the pending configuration. Costs include every attempt, not only successes.

Episode resource limits yield recorded `RESOURCE_LIMITED_FAILURE` and continue in frozen order. An infrastructure failure after the one allowed pre-response transport retry, billing uncertainty, hash/authorization mismatch, permission violation, leakage, contamination, hard-cap breach, or confirmed systemic implementation/evaluator error stops its authorized block. Once the first formal provider dispatch occurs, all listed scientific and operational fields are immutable; a systemic error stops the batch rather than being silently fixed and mixed in.

## Counts and authorization state

The formal design is 32 sources + 30 receivers = **62 episodes**. It has no current live authorization. The pending configuration is [public_formal_experiment_v1.pending.json](/Users/luckyjudy/Desktop/CoALA_EPFL_PHD_Prep/04_projects/metamorph/experiments/experience_value/public_formal_experiment_v1.pending.json), SHA-256 `8a6f3664c8668b73f976d290afe101e1e6de17662f0e3e6def04900e776c221c`.
