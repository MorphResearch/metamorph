# Public viability gate run

Status: **COMPLETED_GO**

`study_kind=development_public_viability_gate`

`included_in_primary_analysis=false`

## Identity

- Model: `deepseek-v4-pro`
- Config: `3ff57258fbac867fe4cd9261c3926c5f7b6de49edc7fb8e18069a37356fde463`
- Task: `63a759c611c4ea7a267d633572d2ba71b4074340c594fa90de4f7911366d1a8c`
- Code: `acbea5c5deb2b5bbe9def3a79bd8f3ce6243c2203f7a337d1e840f0ede13a155`
- Authorization: `105c76426a03be6a463ebf3e24ac7c755022e3f28af01c6250e338f47ad2e872`

## Time and preflight

- Time-window: `{"request_allowed": true, "new_episode_allowed": true, "reason": "within_signed_offpeak_window", "timezone": "Asia/Shanghai", "local_time": "2026-09-27T00:55:35.968364+08:00", "utc_time": "2026-09-26T16:55:35.968364+00:00", "utc_offset": "+0800", "window_end_local": "2026-09-27T08:55:00+08:00", "remaining_seconds": 28764, "official_rate_window": "offpeak"}`
- Credential-free DNS/TLS/HEAD: `{"ok": true, "dns": [{"family": "IPv4", "address": "198.18.0.95"}], "tls": {"version": "TLSv1.3", "cipher": "TLS_AES_256_GCM_SHA384"}, "http": {"status": 401, "reason": "Authorization Required"}, "elapsed_ms": 124.27}`

## Episodes

- `viability-1-f0` (F0, task 1): started=True; ANSWER=True; evaluator=True; score=0.0; decisions=8; attempts/responses=9/9; SQL=14; files=1; stop=model_finished; analysis=EVALUATED_NATIVE; artifacts=['/memory/experience_001.md']; cost=0.017637972; billing_unknown=False
- `viability-2-u0` (U0, task 2): started=True; ANSWER=True; evaluator=True; score=0.0; decisions=9; attempts/responses=10/10; SQL=13; files=2; stop=model_finished; analysis=EVALUATED_NATIVE; artifacts=['/memory/experience_002.md']; cost=0.023806772; billing_unknown=False

## Batch summary

- Provider attempts / completed responses: `19` / `19`
- Paid evaluator requests: `2`
- Native evaluator count: `2`
- Known cost estimate: `0.041444744`; unknown-billing attempts: `0`
- Infrastructure status: `NOT_APPLICABLE`

# GO
