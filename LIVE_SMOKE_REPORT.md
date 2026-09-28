# LIVE SMOKE REPORT

```json
{
  "authorization_config": "experiments/experience_value/live_smoke_config.authorized_20260921.json",
  "authorization_config_hash": "ff3cadeb389e213d97e65c242a3530710ed843a1e46696c20fdaaa809278e25e",
  "billing_unknown": false,
  "episodes": [
    {
      "artifact_files_read": [],
      "artifact_files_written": [],
      "artifact_write_provenance": [],
      "actual_model_id": "deepseek-v4-pro",
      "attempt_id": "e182a9c6db724f7ebdf7b30182010771",
      "condition": "U1",
      "cost_by_request": [
        "0.00105468",
        "0.0011748",
        "0.00120516",
        "0.0013068",
        "0.0015378",
        "0.00184536"
      ],
      "episode": 1,
      "file_reads": 0,
      "file_writes": 0,
      "final_answer": "Based on inspection of the `regions` table (which maps `region` to `cluster`):\n\n- **North region** → cluster **alpine**\n- **South region** → cluster **coastal**\n\nThe `regions` table rows confirmed this directly:\n- `north` → `alpine`\n- `south` → `coastal`",
      "finish_reasons": [
        "tool_calls",
        "tool_calls",
        "tool_calls",
        "tool_calls",
        "tool_calls",
        "stop"
      ],
      "initial_memory": "EMPTY",
      "metrics": {
        "completion_tokens": 430,
        "latency_seconds": 10.664189,
        "llm_calls": 6,
        "prompt_tokens": 4865,
        "runner_stop_reason": "model_finished",
        "success": true,
        "tool_calls": 5,
        "total_tokens": 5295
      },
      "model_requests": 6,
      "provider_config_hash": "ff3cadeb389e213d97e65c242a3530710ed843a1e46696c20fdaaa809278e25e",
      "output_snapshot_files": [],
      "output_snapshot_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "runner_stop_reason": "model_finished",
      "source_snapshot_hash_before_probes": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "source_snapshot_unchanged_after_all_probes": true,
      "sql_queries_completed": 4,
      "sql_queries_failed": 1,
      "task_score": {
        "correct": true,
        "reference_kind": "local_fixture_only",
        "scored": true
      },
      "usage_by_request": [
        {
          "cached_tokens": 0,
          "completion_tokens": 73,
          "prompt_cache_hit_tokens": 0,
          "prompt_tokens": 580,
          "reasoning_tokens": 17,
          "total_tokens": 653
        },
        {
          "cached_tokens": 640,
          "completion_tokens": 71,
          "prompt_cache_hit_tokens": 640,
          "prompt_tokens": 677,
          "reasoning_tokens": 14,
          "total_tokens": 748
        },
        {
          "cached_tokens": 640,
          "completion_tokens": 48,
          "prompt_cache_hit_tokens": 640,
          "prompt_tokens": 769,
          "reasoning_tokens": 0,
          "total_tokens": 817
        },
        {
          "cached_tokens": 768,
          "completion_tokens": 48,
          "prompt_cache_hit_tokens": 768,
          "prompt_tokens": 846,
          "reasoning_tokens": 0,
          "total_tokens": 894
        },
        {
          "cached_tokens": 768,
          "completion_tokens": 73,
          "prompt_cache_hit_tokens": 768,
          "prompt_tokens": 946,
          "reasoning_tokens": 9,
          "total_tokens": 1019
        },
        {
          "cached_tokens": 896,
          "completion_tokens": 117,
          "prompt_cache_hit_tokens": 896,
          "prompt_tokens": 1047,
          "reasoning_tokens": 42,
          "total_tokens": 1164
        }
      ]
    },
    {
      "artifact_files_read": [],
      "artifact_files_written": [],
      "artifact_write_provenance": [],
      "actual_model_id": "deepseek-v4-pro",
      "attempt_id": "72c5c8466a6a4164a9330f7d83273b23",
      "condition": "E*",
      "cost_by_request": [
        "0.00158532",
        "0.0016236",
        "0.00156288",
        "0.0019734",
        "0.00138996"
      ],
      "episode": 2,
      "file_reads": 0,
      "file_writes": 0,
      "final_answer": "<｜｜DSML｜｜tool_calls>\n<｜｜DSML｜｜invoke name=\"query_sql\">\n<｜｜DSML｜｜parameter name=\"sql\" string=\"true\">SELECT COUNT(*) AS n, AVG(o.value) AS mean_value FROM observations o JOIN regions r ON o.region = r.region WHERE r.cluster = 'coastal'</｜｜DSML｜｜parameter>\n</｜｜DSML｜｜invoke>\n</｜｜DSML｜｜tool_calls>",
      "finish_reasons": [
        "tool_calls",
        "tool_calls",
        "tool_calls",
        "tool_calls",
        "stop"
      ],
      "initial_memory": "M_U",
      "metrics": {
        "completion_tokens": 710,
        "latency_seconds": 13.910019,
        "llm_calls": 5,
        "prompt_tokens": 4033,
        "runner_stop_reason": "tool_budget_exhausted",
        "success": true,
        "tool_calls": 6,
        "total_tokens": 4743
      },
      "model_requests": 5,
      "provider_config_hash": "ff3cadeb389e213d97e65c242a3530710ed843a1e46696c20fdaaa809278e25e",
      "output_snapshot_files": [],
      "output_snapshot_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "parent_snapshot_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "parent_snapshot_unchanged": true,
      "runner_stop_reason": "tool_budget_exhausted",
      "sql_queries_completed": 2,
      "sql_queries_failed": 2,
      "task_score": {
        "correct": false,
        "reference_kind": "local_fixture_only",
        "scored": true
      },
      "usage_by_request": [
        {
          "cached_tokens": 0,
          "completion_tokens": 228,
          "prompt_cache_hit_tokens": 0,
          "prompt_tokens": 517,
          "reasoning_tokens": 146,
          "total_tokens": 745
        },
        {
          "cached_tokens": 640,
          "completion_tokens": 145,
          "prompt_cache_hit_tokens": 640,
          "prompt_tokens": 795,
          "reasoning_tokens": 45,
          "total_tokens": 940
        },
        {
          "cached_tokens": 768,
          "completion_tokens": 66,
          "prompt_cache_hit_tokens": 768,
          "prompt_tokens": 986,
          "reasoning_tokens": 11,
          "total_tokens": 1052
        },
        {
          "cached_tokens": 1024,
          "completion_tokens": 121,
          "prompt_cache_hit_tokens": 1024,
          "prompt_tokens": 1132,
          "reasoning_tokens": 35,
          "total_tokens": 1253
        },
        {
          "cached_tokens": 0,
          "completion_tokens": 150,
          "prompt_cache_hit_tokens": 0,
          "prompt_tokens": 603,
          "reasoning_tokens": 69,
          "total_tokens": 753
        }
      ]
    },
    {
      "artifact_files_read": [],
      "artifact_files_written": [],
      "artifact_write_provenance": [],
      "actual_model_id": "deepseek-v4-pro",
      "attempt_id": "b24cfb4d4a0e410a9e3c1497d5426e3e",
      "condition": "E*",
      "cost_by_request": [
        "0.00089628",
        "0.00115368",
        "0.00141636",
        "0.0014784",
        "0.00125664"
      ],
      "episode": 3,
      "file_reads": 0,
      "file_writes": 0,
      "final_answer": "<｜｜DSML｜｜tool_calls>\n<｜｜DSML｜｜invoke name=\"query_sql\">\n<｜｜DSML｜｜parameter name=\"sql\" string=\"true\">SELECT sql FROM sqlite_master WHERE type='table'</｜｜DSML｜｜parameter>\n</｜｜DSML｜｜invoke>\n</｜｜DSML｜｜tool_calls>",
      "finish_reasons": [
        "tool_calls",
        "tool_calls",
        "tool_calls",
        "tool_calls",
        "stop"
      ],
      "initial_memory": "EMPTY",
      "metrics": {
        "completion_tokens": 472,
        "latency_seconds": 10.201966,
        "llm_calls": 5,
        "prompt_tokens": 3282,
        "runner_stop_reason": "tool_budget_exhausted",
        "success": true,
        "tool_calls": 6,
        "total_tokens": 3754
      },
      "model_requests": 5,
      "provider_config_hash": "ff3cadeb389e213d97e65c242a3530710ed843a1e46696c20fdaaa809278e25e",
      "output_snapshot_files": [],
      "output_snapshot_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "parent_snapshot_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "parent_snapshot_unchanged": true,
      "runner_stop_reason": "tool_budget_exhausted",
      "sql_queries_completed": 1,
      "sql_queries_failed": 0,
      "task_score": {
        "correct": false,
        "reference_kind": "local_fixture_only",
        "scored": true
      },
      "usage_by_request": [
        {
          "cached_tokens": 512,
          "completion_tokens": 54,
          "prompt_cache_hit_tokens": 512,
          "prompt_tokens": 517,
          "reasoning_tokens": 9,
          "total_tokens": 571
        },
        {
          "cached_tokens": 512,
          "completion_tokens": 92,
          "prompt_cache_hit_tokens": 512,
          "prompt_tokens": 598,
          "reasoning_tokens": 10,
          "total_tokens": 690
        },
        {
          "cached_tokens": 512,
          "completion_tokens": 111,
          "prompt_cache_hit_tokens": 512,
          "prompt_tokens": 740,
          "reasoning_tokens": 29,
          "total_tokens": 851
        },
        {
          "cached_tokens": 768,
          "completion_tokens": 73,
          "prompt_cache_hit_tokens": 768,
          "prompt_tokens": 901,
          "reasoning_tokens": 17,
          "total_tokens": 974
        },
        {
          "cached_tokens": 0,
          "completion_tokens": 142,
          "prompt_cache_hit_tokens": 0,
          "prompt_tokens": 526,
          "reasoning_tokens": 86,
          "total_tokens": 668
        }
      ]
    }
  ],
  "fourth_episode_started": false,
  "generated_at": "2026-09-21T06:20:15.747042+00:00",
  "hard_cap_usd": "0.20",
  "included_in_primary_analysis": false,
  "ledger": [
    {
      "actual": "0.00105468",
      "id": "6f39c635fba54f91ad1e1bb0a8c861ab",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 0,
        "completion_tokens": 73,
        "prompt_cache_hit_tokens": 0,
        "prompt_tokens": 580,
        "reasoning_tokens": 17,
        "total_tokens": 653
      }
    },
    {
      "actual": "0.0011748",
      "id": "d02b63aef7ec46cb952915873105e61a",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 640,
        "completion_tokens": 71,
        "prompt_cache_hit_tokens": 640,
        "prompt_tokens": 677,
        "reasoning_tokens": 14,
        "total_tokens": 748
      }
    },
    {
      "actual": "0.00120516",
      "id": "e3635fded5984edf995904a67721741a",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 640,
        "completion_tokens": 48,
        "prompt_cache_hit_tokens": 640,
        "prompt_tokens": 769,
        "reasoning_tokens": 0,
        "total_tokens": 817
      }
    },
    {
      "actual": "0.0013068",
      "id": "e4135624956940c582174f1b24be314b",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 768,
        "completion_tokens": 48,
        "prompt_cache_hit_tokens": 768,
        "prompt_tokens": 846,
        "reasoning_tokens": 0,
        "total_tokens": 894
      }
    },
    {
      "actual": "0.0015378",
      "id": "e55a634d3c6f4f99904fdebbf39cafa4",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 768,
        "completion_tokens": 73,
        "prompt_cache_hit_tokens": 768,
        "prompt_tokens": 946,
        "reasoning_tokens": 9,
        "total_tokens": 1019
      }
    },
    {
      "actual": "0.00184536",
      "id": "308cda107b26426891d696a7fcd11c85",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 896,
        "completion_tokens": 117,
        "prompt_cache_hit_tokens": 896,
        "prompt_tokens": 1047,
        "reasoning_tokens": 42,
        "total_tokens": 1164
      }
    },
    {
      "actual": "0.00158532",
      "id": "d25c45828726484cb0676fe1e12d6fe5",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 0,
        "completion_tokens": 228,
        "prompt_cache_hit_tokens": 0,
        "prompt_tokens": 517,
        "reasoning_tokens": 146,
        "total_tokens": 745
      }
    },
    {
      "actual": "0.0016236",
      "id": "1659194a73f442eea067dba0777d0f3b",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 640,
        "completion_tokens": 145,
        "prompt_cache_hit_tokens": 640,
        "prompt_tokens": 795,
        "reasoning_tokens": 45,
        "total_tokens": 940
      }
    },
    {
      "actual": "0.00156288",
      "id": "6d385fac4277434cb95bf2550e456f8d",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 768,
        "completion_tokens": 66,
        "prompt_cache_hit_tokens": 768,
        "prompt_tokens": 986,
        "reasoning_tokens": 11,
        "total_tokens": 1052
      }
    },
    {
      "actual": "0.0019734",
      "id": "c30712972c6145ebad52116296fbe3f0",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 1024,
        "completion_tokens": 121,
        "prompt_cache_hit_tokens": 1024,
        "prompt_tokens": 1132,
        "reasoning_tokens": 35,
        "total_tokens": 1253
      }
    },
    {
      "actual": "0.00138996",
      "id": "e45eba3581e8445d8d12f6fefea3cfe6",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 0,
        "completion_tokens": 150,
        "prompt_cache_hit_tokens": 0,
        "prompt_tokens": 603,
        "reasoning_tokens": 69,
        "total_tokens": 753
      }
    },
    {
      "actual": "0.00089628",
      "id": "eb7d35bad75a4eb8800c4e33bf6e3687",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 512,
        "completion_tokens": 54,
        "prompt_cache_hit_tokens": 512,
        "prompt_tokens": 517,
        "reasoning_tokens": 9,
        "total_tokens": 571
      }
    },
    {
      "actual": "0.00115368",
      "id": "3a8b54322c864d76bc50ae0a9445add3",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 512,
        "completion_tokens": 92,
        "prompt_cache_hit_tokens": 512,
        "prompt_tokens": 598,
        "reasoning_tokens": 10,
        "total_tokens": 690
      }
    },
    {
      "actual": "0.00141636",
      "id": "ff5dbcef907a4aaca8471cd7ecab2247",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 512,
        "completion_tokens": 111,
        "prompt_cache_hit_tokens": 512,
        "prompt_tokens": 740,
        "reasoning_tokens": 29,
        "total_tokens": 851
      }
    },
    {
      "actual": "0.0014784",
      "id": "3276d38b1d554ed6a3d678e5b96b1af3",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 768,
        "completion_tokens": 73,
        "prompt_cache_hit_tokens": 768,
        "prompt_tokens": 901,
        "reasoning_tokens": 17,
        "total_tokens": 974
      }
    },
    {
      "actual": "0.00125664",
      "id": "ba20c7622fb1435c969e90d7e67a5f58",
      "reserved": "0.00878592",
      "status": "settled",
      "usage": {
        "cached_tokens": 0,
        "completion_tokens": 142,
        "prompt_cache_hit_tokens": 0,
        "prompt_tokens": 526,
        "reasoning_tokens": 86,
        "total_tokens": 668
      }
    }
  ],
  "ledger_summary": {
    "actual_provider_invoice_available": false,
    "usage_based_peak_price_estimate_usd": "0.011681472",
    "usage_based_peak_price_estimate_basis": "16 returned usage records; provider-reported cached input at USD 0.044/M, non-cached input at USD 1.32/M, and output at USD 3.96/M. This remains an estimate, not an invoice.",
    "reserved_usd": "0.14057472",
    "settled_conservative_cache_miss_estimate_usd": "0.02246112",
    "unknown_billing_request_count": 0,
    "non_charge_conservative_reservation_difference_usd": "0.11811360"
  },
  "no_code_execution_calls": true,
  "post_run_interpretation": {
    "episode_1_memory_artifact": "NO_ARTIFACT_OBSERVED; the source snapshot was empty and unchanged.",
    "episode_2_and_3": "Each reached the six-tool cap. A later response contained unexecuted tool-markup text; it is not accepted as a final task answer or normal completion.",
    "causal_memory_claim": "NOT_ESTABLISHED: no source artifact was written or read."
  },
  "provider_requests_sent": 16,
  "status": "COMPLETED",
  "study_kind": "engineering_smoke",
  "worst_case_all_18_requests_usd": "0.15814656",
  "worst_case_per_request_usd": "0.00878592"
}
```
