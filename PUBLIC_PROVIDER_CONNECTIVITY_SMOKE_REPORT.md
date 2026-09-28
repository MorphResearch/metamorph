# Provider connectivity smoke

Status: **SUCCESS**

`study_kind=engineering_provider_connectivity_smoke`

`included_in_primary_analysis=false`

- Preflight: `{"ok": true, "dns": [{"family": "IPv4", "address": "198.18.0.68"}], "tls": {"version": "TLSv1.3", "cipher": "TLS_AES_256_GCM_SHA384"}, "http": {"status": 401, "reason": "Authorization Required"}, "elapsed_ms": 138.26}`
- Time window: `{"allowed": true, "local_time": "2026-09-22T22:19:04.900256+08:00", "utc_time": "2026-09-22T14:19:04.900256+00:00", "utc_offset": "+0800", "official_rate_window": "offpeak", "reason": "within_signed_offpeak_window"}`
- Environment: `{"python": "3.13.15", "openssl": "OpenSSL 3.5.8 25 Aug 2026", "versions": {"openai": "2.16.0", "httpx": "0.28.1", "litellm": "1.81.6", "certifi": "2026.7.22"}}`
- Provider request attempts: `1`
- Result: `{"response_present": true, "actual_model_id": "deepseek-v4-pro", "finish_reason": "stop", "usage": {"prompt_tokens": 9, "completion_tokens": 11, "total_tokens": 20, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 9, "reasoning_tokens": 9, "cached_tokens": 0}, "content": "OK", "latency_note": "see provider request event timestamps"}`
- Ledger: `{"entries": [{"id": "44fcb38c2c9a401fb9bee066396b736f", "status": "settled", "reserved": "0.01596672", "usage": {"prompt_tokens": 9, "completion_tokens": 11, "total_tokens": 20, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 9, "reasoning_tokens": 9, "cached_tokens": 0}, "actual": "0.00002772"}], "reserved_usd": "0.01596672", "settled_usd": "0.00002772", "billing_unknown": false}`

READY_TO_REAUTHORIZE_PUBLIC_CALIBRATION
