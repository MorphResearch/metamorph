# Public Database Exploration integration report

Status: development environment integrated and no-model end-to-end acceptance
passed. This is not a model evaluation or a continual-learning result.

`study_kind=engineering_public_environment_integration`

`included_in_primary_analysis=false`

## Atomic close-out

The completed Atomic file-I/O run is unchanged at
`artifacts/experience_value/e0-e98ad111fe8849c4bca6dff4655c6c74` and was
copied, together with its transcript, artifacts, configuration, authorization,
and SHA-256 manifest, to
`artifacts/experience_value/backups/e0-e98ad111fe8849c4bca6dff4655c6c74`.

It remains engineering evidence that, under restricted file tools, a real
model wrote an artifact and a new session discovered and read it. The historical
`returned_exact_marker=false` field is retained: it tested whole-response
equality. The separate evidence report records exact-marker containment as
passing. Neither the source artifact nor its marker is mounted, copied, or used
by this public-environment development work. This does not establish autonomous
learning, generalization, or a causal effect.

## Fixed public source and isolated installation

The checkout is a sparse clone of the requested official origin
`https://github.com/pgasawa/continual-learning-bench.git`, detached at
`5f8c50eb1e84b2eda2ef4faff757dfc812a0ea26` (not `main`). The commit subject is
`fix(leaderboard): normalize cohort_studies reward to the current signed metric (#9)`.

Upstream requires Python `>=3.13`. The existing Metamorph `.venv` and system
Python were not changed. A repository-local CPython 3.13.15 runtime and a
separate `benchmarks/continual-learning-bench/.venv-database-exploration`
environment were created. Installed task-only runtime packages include
`pydantic 2.12.5`, `huggingface-hub 1.32.0`, `httpx 0.28.1`, `fsspec 2026.9.0`,
and `tqdm 4.70.1`. No Docker, raw Amazon review corpus, `setup --all`, or full
benchmark run was used.

The upstream interface imports a general billing module that eagerly imports
LiteLLM, although Database Exploration and its evaluator do not invoke it. To
avoid adding the provider client stack in this zero-model task, the adapter has
a narrow import-only shim when LiteLLM is absent. It supplies only the unused
`model_cost` attribute needed for type-module import. It cannot send a request;
the shim is documented in code and is prohibited for a later live provider run.
The upstream task, SQLite executor, and evaluator files are unmodified.

Only upstream `DatabaseExploration.setup()` was initialized. It fetched the
two official public database snapshots through the normal Hugging Face HTTP
path after the Xet path remained at zero bytes. Their local evidence is:

| Resource | SHA-256 | Size |
| --- | --- | ---: |
| `questions.json` | `f98e515c14b74f4d30c29401fb79cca9ceeb15fe9ee2432b10265a4a649d1771` | 30,820 B |
| `questions_post_drift.json` | `c05aa6a33def3878e6b655a1cba6454e55e1a9c16ded8c1fe53b7811986a45de` | 21,144 B |
| `products.db` | `edf8ee80ff125de0bfd6c37a1d185efa9e3037ce28eb1bd1d32ae0829bd264a6` | 397,910,016 B |
| `products_drifted.db` | `a53d523f70604be0e4328f3722417895250ac35e1127cc504b609576aee70fad` | 432,148,480 B |

## Thin adapter and safety boundary

Implemented files:

- `experiments/experience_value/clbench_database_exploration.py` — SHA-256
  `3df0b9fa4f8050f2a4dc0cd18a187d5dad8bee5489165315a1ec7fb392131eef`
- `experiments/experience_value/verify_clbench_database_exploration.py` — SHA-256
  `21edc6853deff7fd4cc458a6d29fa80969064b338eade51ad52a62ce643a50dc`

`DatabaseExplorationAdapter` constructs the actual upstream
`DatabaseExploration`, calls `build_canonical_run_state()`, exposes only the
public prompt/task ID/query budget, and maps `query_sql` to the native `QUERY`
action and terminal text to the native `ANSWER` action. SQL feedback comes from
the upstream SQLite executor; its read-only SQL policy, 10-second query timeout,
row limit, and native 15-query default remain in force. `evaluate_native()`
calls upstream `evaluate()` and saves only aggregate scoring evidence.

The runner-side database path, question JSON, reference SQL, answers,
evaluator history, and research event directory are never fields of the
agent-visible `PublicTaskView`. Terminal native feedback is deliberately
replaced with a completion notice because upstream feedback includes reference
answers/SQL after an `ANSWER`; SQL feedback and SQL error feedback are preserved.
This keeps reference material out of a possible subsequent model turn and the
generic event log. Agent code execution remains unavailable: no shell, Python,
eval, import, web, or direct database-file tool was added.

The adapter emits into the existing append-only `RunRecords` mechanism. It is
ready to be supplied to the existing restricted tool loop; this acceptance did
not create an Agent workspace or snapshot because no Agent/provider session was
started. The existing workspace/snapshot isolation and transcript/ledger loop
therefore remain the required path for any later authorized provider binding.

## Actual no-model end-to-end acceptance

Final command (exit code `0`):

```bash
HF_HUB_DISABLE_XET=1 benchmarks/continual-learning-bench/.venv-database-exploration/bin/python \
  -m experiments.experience_value.verify_clbench_database_exploration \
  benchmarks/continual-learning-bench \
  artifacts/experience_value/public_environment_development/clbench-db-20260921T213900Z
```

This executed the real path: upstream setup (local files already present) →
task reset/load → legal native SQL `SELECT name FROM sqlite_master WHERE
type='table' ORDER BY name` → actual SQLite feedback → native `ANSWER` →
upstream `evaluate()` → saved result/event evidence. It used public task ID
`1`, query budget `15`, two fresh task instances, and zero provider requests.

`development_acceptance.json` (SHA-256
`22be5f4e047a5bed72d5f4574127dcef85983713262c8dbe05d7caa05571f3a5`)
records:

- prompt loaded and agent view excludes the database path: `true`;
- query feedback received: `true`;
- deliberately wrong researcher-side answer: native success `false`, score `0.0`;
- researcher-side correct development answer: native success `true`, score `0.9333`;
- provider requests and paid evaluator calls: `0`.

The event stream is
`artifacts/experience_value/public_environment_development/clbench-db-20260921T213900Z/research_records/events.jsonl`
(SHA-256 `9fa832f616b6be217d153688cdedcae0c624fc16708559b30d833831b97fc372`).
It has two `task_loaded`, two real `QUERY`, two `ANSWER`, and two native-evaluator
events, with only aggregate metrics for evaluation. The correct answer was read
only by the researcher-side verifier to test the upstream evaluator and was not
put into a prompt, workspace, transcript, or source artifact.

The first Xet download attempt was terminated after remaining at 0 bytes; the
standard HTTP retry downloaded the same two official files. A first local
driver invocation then exited `1` due to a repeated import-shim check; that
specific adapter defect was fixed before the final exit-0 command above. Neither
attempt made a provider request.

Relevant offline regression commands also passed in the isolated Python 3.13
environment:

```text
python -m unittest discover -s experiments/experience_value/tests -p test_e0_acceptance.py -v  # 21 passed, exit 0
python -m unittest experiments.experience_value.tests.test_file_positive_control_run -v          # 7 passed, exit 0
```

The project `.venv` lacks `pytest`; no dependency was added merely to run it.

## Development-only task sequence and data contact

The following IDs are from the checked-in pre-migration `questions.json`, in
that file's original order. All are permanently development-contacted, not
unseen confirmation instances. The selection is based on sequential coverage
of actual knowledge-dependency categories, never on an F/U outcome.

| Role | IDs | Categories / dependency coverage |
| --- | --- | --- |
| Practice | `1`, `2`, `3` | `g1_bad_timestamps`, `g1_join_price_review`, `g1_timestamp`; covers schema map, timestamp/price formats, group identity, joins, and data quality. |
| Probe | `4`, `5`, `6` | `g1_rating_discrepancy`, `g2_median_price`, `g1_cross_table_gap`; distinct IDs; covers joins/data-quality and adds a group-2 price-format check. |

There is no ID overlap. In the direct pre-migration list, items 1–6 share
`products.db` and have no state change. The official `default` schedule instead
uses the `schema_drift` variant: it shuffles a 20-question pre-migration stage,
then changes to `products_drifted.db` and uses 20 post-migration questions.
Thus this six-item development slice does not validate drift handling and must
not be described as preserving default-schedule order.

Researcher contact was limited to reading the two checked-in question JSON
files for IDs/categories/dependencies and parsing `questions.json` to use ID 1's
answer once in the local correct/incorrect evaluator check. The database query
was the schema-table listing above. No answer, reference SQL, full task JSON,
or Atomic marker entered an agent prompt or experience workspace.

## Later calibration: entry and budget proposal (not authorized)

The actual, currently runnable public-task entry is the no-model command above.
There is intentionally no provider `--live` command or authorization record
yet: this turn explicitly permits zero real model requests, and selecting a
model/pricing configuration or silently reusing Atomic limits would violate
that boundary. A later live calibration must first bind this adapter to the
existing `run_tool_only_episode` / workspace / snapshot / transcript / ledger
path under a new public-environment authorization; it must not use the Atomic
authorization or artifact.

Proposed common development envelope, subject to a separately authorized
calibration:

- Preserve the upstream native maximum of 15 exploratory SQL queries per
  question; do not replace it with the Atomic 6-tool limit.
- For a query-only instance, reserve at most 16 model decisions (15 query
  decisions plus one terminal `ANSWER`) with application and SDK retries fixed
  at zero. If optional file operations are retained for F/U, their limit must
  be configured separately so they do not silently reduce the upstream SQL
  budget; its value remains uncalibrated.
- Input context length, output-token cap, timeout, pricing table, provider,
  and batch dollar cap remain uncalibrated. They require an actual serialized
  public prompt/tool-feedback measurement and a fresh authorization; Atomic's
  512-output-token and USD 0.20 values are not reused here.
- All four F/U groups must share the chosen model, original task prompt,
  native query interface, query budget, provider retry policy, and accounting.
  F/U may choose whether to save an experience artifact; no group inherits the
  Atomic forced-write instruction or its SQL-disabled receiver restriction.

Concrete remaining prerequisites are: (1) a separately signed public-task
provider/model/price configuration; (2) a thin authorized provider binding
that keeps SQL queries on `DatabaseExplorationAdapter` rather than local
fixtures and freezes only agent `/memory`; (3) a deliberate file-operation
policy that does not alter the native 15-query allowance; and (4) resolution
of the currently unavailable Agent code sandbox if a later study needs
executable skills. These are not generic blockers: task setup, public data,
native query feedback, native scoring, isolation boundary, and zero-model
development acceptance are complete.

No 78-episode batch, real model request, paid LLM evaluator, provider client
call, public-environment code sandbox, commit, push, or background task was
started in this integration.
