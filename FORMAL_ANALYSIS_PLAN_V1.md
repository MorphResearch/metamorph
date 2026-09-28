# Formal analysis plan v1

Status: frozen before any formal request. This plan contains no formal answers, reference SQL, or evaluator references.

## Included population and fields

The formal population is all 32 source and all 30 receiver episodes listed in the two formal manifests. IDs 1–6 and every development-derived object are excluded. Every executed episode remains in the accounting; `RESOURCE_LIMITED_FAILURE` is a scored failure (`analysis_score=0` when no scorable answer), while `INVALID_INFRA` and `INVALID_SYSTEM` have `analysis_score=null` and are reported rather than silently dropped.

Primary source outcome is answer correctness/accuracy. Secondary source outcome is native `TaskResult.score` (including its normalized-regret interpretation). Record SQL count, model decisions, provider attempts, prompt/completion/reasoning tokens, latency, current off-peak usage estimate, fixed-reference estimate, consolidation length, artifact bytes/count, `NO_MEMORY`, generation failure, and snapshot size for every episode.

## RQ1: within-workflow experience retention

For each source task in original order, report paired/descriptive contrasts:

`G_F(metric) = metric(F1) - metric(F0)`  
`G_U(metric) = metric(U1) - metric(U0)`

The primary metric is correctness/accuracy; the native score is secondary. Do not infer a direction in advance or condition the analysis on artifact quality, score, task success, or cost.

## RQ2: common receiver value

For each probe task, the common E* receiver comparison uses:

`V_accuracy(M_F) = accuracy(M_F) - accuracy(EMPTY)`  
`V_accuracy(M_U) = accuracy(M_U) - accuracy(EMPTY)`  
`DeltaV = V(M_U) - V(M_F)`

Report the equivalent native-score contrasts. `RAW_F` and `RAW_U` are descriptive preregistered baselines that distinguish deterministically committed consolidation text from agent-visible pre-consolidation trajectories; they are not selected after observing outcomes.

## Receiver-use and integrity reporting

For each receiver task/resource, report whether the object existed, mount path, listing/read proposal and dispatch, whether its content entered model context, and paths actually read. Absence of a read is not evidence of transfer. Artifact existence, listing, reading, and use remain separate fields.

The analysis must report all known and unknown-billing attempts, all stop reasons, and all invalid episodes. It must not call the development viability GO result a formal treatment effect, learning result, or causal result.
