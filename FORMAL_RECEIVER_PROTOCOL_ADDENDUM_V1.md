# Formal Receiver Protocol Addendum V1

## Status

`receiver_protocol_status = COMPLETED_PRE_EXECUTION_BY_ADDENDUM`

This addendum completes previously omitted receiver execution semantics before any formal receiver episode or probe outcome was observed. It does not alter the completed source experiment. It is not performance tuning.

## Immutable bindings

- Formal protocol: `ef157008c669b93bdfcffc1579cea4275349916079a6ab2945c10fd3c82b3450`
- Original receiver manifest: `6a6ed3b22aebc5b0bace7bd06c73c54892f3d6e951005115d40ca047ea0d11a2`
- Analysis plan: `eb5628ead51537fe6fc3f12ec6a132f3c4c86f284f14065d2ed6a139ca955f74`
- Source phase seal: `f6a1ca4f44a5f0d6720ace90b8634b11d5e03b9025e715ca364fcb52fa100d46`
- Receiver resource manifest: `6ea6e4b1054f387a394ab2c3c2e71a0ca93a2b7f1235444b1a6a72589a6d96bf`
- Addendum canonical hash: `96b033729af9768b6a5ebe6fe2c2a1436f13270161b8f2370dc2b3a7960c95e7`

## Completed execution semantics

- Tool allowlist: `list_dir, read_file, write_file, query_sql`; canonical schema SHA-256: `cb9348286035ae1db212e0d5f737b3ced1ede25d7691c709f1cb0d2a914da4ce`.
- File paths are restricted to `/memory` and `/work`; path escape, symlinks, and non-regular files are rejected. Existing cloned memory files remain immutable, while legal episode-local writes may create new clone/work files and never propagate.
- The terminal path permits one tool-free ordinary-text decision only after the fifteenth legal SQL feedback and only when fewer than 24 main decisions have been used. It is counted within the 24-decision limit; there is no finalization retry or sixteenth SQL query.
- Formal input cutoff is `ceil(diagnostic_estimated_tokens * 0.50) + 256`; it blocks pre-dispatch at `>= 24000`. Its 46-observation calibration excludes scores, answers, SQL, and condition outcomes.
- Native evaluation occurs once only after an accepted native answer; evaluator/reference output never enters agent-visible messages, files, resources, or a follow-up model call. Receiver consolidation is disabled.
- Frozen per-attempt reservation is USD `0.03206016`. A five-episode probe-major block has USD `7.69443840` worst-case reservation and an independent mechanical USD `8.00` cap. Thirty episodes have USD `46.16663040` worst-case reservation with no transferable shared cap.

## Operational receiver blocks

- formal_receiver_block_01: probe 15, positions 1–5, tokens `t15-EMPTY, t15-M_F, t15-M_U, t15-RAW_F, t15-RAW_U`.
- formal_receiver_block_02: probe 16, positions 6–10, tokens `t16-M_F, t16-M_U, t16-RAW_F, t16-RAW_U, t16-EMPTY`.
- formal_receiver_block_03: probe 17, positions 11–15, tokens `t17-M_U, t17-RAW_F, t17-RAW_U, t17-EMPTY, t17-M_F`.
- formal_receiver_block_04: probe 18, positions 16–20, tokens `t18-RAW_F, t18-RAW_U, t18-EMPTY, t18-M_F, t18-M_U`.
- formal_receiver_block_05: probe 19, positions 21–25, tokens `t19-RAW_U, t19-EMPTY, t19-M_F, t19-M_U, t19-RAW_F`.
- formal_receiver_block_06: probe 20, positions 26–30, tokens `t20-EMPTY, t20-M_F, t20-M_U, t20-RAW_F, t20-RAW_U`.

## Static validation

- PASS — original protocol/manifest/analysis hashes and both frozen resource bindings matched before addendum creation.
- PASS — the source V3 authorization hashes matched the current common source execution implementation and source pricing records.
- PASS — all five formerly omitted fields have one explicit, machine-readable binding.
- PASS — the six block slices preserve the original 30-token probe-major order with five resources each.
- PASS — all five resources share every bound receiver setting; only their frozen starting content differs.
- PASS — source seal/resources/original frozen documents were rehashed unchanged after addendum creation.
- PASS — provider requests = 0; evaluator calls = 0; probe content read = false; receiver_started = false.
