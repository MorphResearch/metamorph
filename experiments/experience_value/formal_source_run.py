"""Thin, block-scoped formal-source runner; no receiver and no task selection CLI."""
from __future__ import annotations

import argparse, hashlib, json, re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from llm.adapters import ProviderAdapter
from .clbench_database_exploration import DatabaseExplorationAdapter
from .live import PriceSheet, ToolOnlySmokeConfig, build_authorized_client, run_tool_only_episode
from .public_calibration_run import ALLOWED_TOOLS, FILE_TOOLS, NativeQueryTool, _offpeak_status, _provider_connectivity_preflight
from .public_viability_gate_run import _code_hashes, _empty_episode, _episode_report, _events, _mark_authorization_consumed_once
from .records import AuthorizationError, CostLedger, LiveAuthorization
from .runner import ExperimentRunner

ROOT = Path(__file__).resolve().parents[2]

def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()

def _load(pending_path: Path, authorization_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], ToolOnlySmokeConfig, PriceSheet]:
    p, a = json.loads(pending_path.read_text()), json.loads(authorization_path.read_text())
    if p.get("status") != "PENDING_FORMAL_SOURCE_BLOCK_01_USER_SIGNOFF_NO_LIVE_CALLS" or p.get("study_kind") != "formal_source_v1" or p.get("included_in_primary_analysis") is not True:
        raise AuthorizationError("formal source pending scope is invalid")
    for field in ("formal_protocol", "source_manifest", "block_definition"):
        ref = p[field]; path = ROOT / ref["path"]
        if sha(path) != ref["sha256"]: raise AuthorizationError(f"{field} hash differs")
    formal = json.loads((ROOT / p["formal_pending"]["path"]).read_text())
    if sha(ROOT / p["formal_pending"]["path"]) != p["formal_pending"]["sha256"]: raise AuthorizationError("formal pending hash differs")
    source = json.loads((ROOT / p["source_manifest"]["path"]).read_text())
    blocks = json.loads((ROOT / p["block_definition"]["path"]).read_text())
    block = next((x for x in blocks["blocks"] if x["id"] == p["block_id"]), None)
    if block is None or p["block_id"] != "formal_source_block_01": raise AuthorizationError("only frozen formal block 01 is implemented")
    tokens = [source["execution_order"][i - 1] for i in block["manifest_positions"]]
    if tokens != block["expected_tokens"] or tokens != ["t07-F0", "t07-U0", "t07-F1", "t07-U1"]: raise AuthorizationError("block differs from frozen manifest positions 1-4")
    items=[]
    for pos, token in zip(block["manifest_positions"], tokens):
        match=re.fullmatch(r"t(\d+)-(F0|U0|F1|U1)", token)
        if not match: raise AuthorizationError("invalid manifest source token")
        task_id, cond = match.groups(); ordinal=int(task_id)-6
        items.append({"id": f"formal-{token.lower()}", "task_id": task_id, "task_index": int(task_id)-1, "condition": cond, "manifest_position": pos, "artifact_path": f"/memory/experience_{ordinal:03d}.md"})
    if set(source["development_contacted_ids"]) & {int(x["task_id"]) for x in items}: raise AuthorizationError("development task entered formal block")
    frozen=a.get("frozen_pending_config", {})
    if frozen.get("sha256") != sha(pending_path): raise AuthorizationError("authorization does not bind pending")
    if a.get("entry_code",{}).get("sha256") != sha(Path(__file__)) or a.get("code_dependencies") != _code_hashes() | {"entry": sha(Path(__file__))}: raise AuthorizationError("authorization does not bind code")
    req=formal["shared_execution"]
    config=ToolOnlySmokeConfig(provider=formal["provider"],exact_model_id=formal["exact_model_id"],base_url=formal["base_url"],api_key_env=formal["api_key_env_name_only"],max_input_characters=0,max_input_tokens_per_request=req["max_input_tokens_per_request"],max_output_tokens_per_request=req["max_output_tokens_per_request"],max_requests_per_episode=req["max_main_model_decisions_per_episode"],max_tool_calls_per_episode=23,timeout_seconds=req["request_timeout_seconds"],retries=0,max_transport_retries=req["max_pre_response_transport_retries"],temperature=None,thinking_enabled=True,reasoning_effort="low",episode_timeout_seconds=req["episode_timeout_seconds"],max_file_return_bytes=32768,enforce_utf8_input_reservation=True,formal_input_cutoff_estimator=req["formal_input_cutoff"]["name"])
    price=p["budget"]
    prices=PriceSheet(Decimal(price["input_cache_miss_usd_per_million"]),Decimal(price["output_usd_per_million"]),price["price_source"],price["price_checked_on"],Decimal(price["input_cache_hit_usd_per_million"]))
    if config.worst_case_request_cost(prices)*Decimal(price["max_provider_attempts"])>Decimal(price["hard_cap_usd"]): raise AuthorizationError("block reservation exceeds hard cap")
    return p,a,items,config,prices

def _write(report: dict[str, Any], path: Path) -> None:
    lines=["# Formal source block report","",f"Status: **{report['status']}**","", "`study_kind=formal_source_v1`","", "`included_in_primary_analysis=true`",""]
    for e in report["episodes"]:
        lines.append(f"- pos {e.get('manifest_position')}: task {e['task_id']} {e['condition']}; started={e['started']}; ANSWER={e['native_answer_submitted']}; correct={e['correct']}; score={e['native_score']}; attempts={e['provider_attempts']}; SQL={e['sql_queries']}; artifact={e.get('artifact_paths')}; stop={e['main_stop_reason']}")
    lines += ["",f"- Next frozen manifest position: `{report['next_manifest_position']}`",f"- Attempts/responses: `{report['provider_attempts']}/{report['provider_responses']}`; cost: `{report['known_cost_estimate']}`; unknown billing: `{report['unknown_billing_attempts']}`",""]
    path.write_text("\n".join(lines),encoding="utf-8")

def _consume_after_dispatch(path: Path, events: list[dict[str, Any]], run_id: str) -> None:
    if not any(event.get("type") == "provider.request_started" for event in events): return
    payload=json.loads(path.read_text())
    if payload.get("real_model_requests_sent_under_this_authorization",0): return
    payload.update(status="CONSUMED_FORMAL_SOURCE_BLOCK_01",real_model_requests_sent_under_this_authorization=1,consumption_run_id=run_id,consumed_at=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n")

def execute(*, pending_path: Path, authorization_path: Path, output_root: Path, mode: str, adapter: ProviderAdapter|None=None, report_path: Path|None=None) -> Path:
    p,a,items,config,prices=_load(pending_path,authorization_path)
    if mode not in {"plan-only","fake","live"}: raise ValueError("mode")
    if mode=="live" and not(a.get("status")=="AUTHORIZED_FORMAL_SOURCE_BLOCK_01" and a.get("live_requests_authorized") is True and a.get("real_model_requests_sent_under_this_authorization")==0): raise AuthorizationError("formal block requires independent authorized record")
    runner=ExperimentRunner(output_root); report_path=report_path or ROOT/"FORMAL_SOURCE_BLOCK_REPORT.md"
    if mode=="plan-only": return runner.records.write_json("formal_source_plan.json",{"provider_requests":0,"episodes":items})
    report={"status":"RUNNING","study_kind":"formal_source_v1","included_in_primary_analysis":True,"episodes":[],"provider_attempts":0,"provider_responses":0,"known_cost_estimate":"0","unknown_billing_attempts":0,"next_manifest_position":5,"preflight":None,"time_window":None,"infrastructure_status":"NOT_APPLICABLE"}
    if mode=="live":
        window=_offpeak_status({"offpeak_window":{"timezone":"Asia/Shanghai","start_local":"18:05:00","end_local":"08:55:00","minimum_remaining_seconds_for_new_episode":1080}},for_new_episode=True); report["time_window"]=window
        if not window["new_episode_allowed"]: report.update(status="WAITING_OFFPEAK",infrastructure_status="NOT_DISPATCHED")
        else:
            report["preflight"]=_provider_connectivity_preflight()
            if not report["preflight"]["ok"]: report.update(status="PRECHECK_FAILED",infrastructure_status="INVALID_INFRA_PRECHECK")
            else:
                try: DatabaseExplorationAdapter.assert_real_litellm_available()
                except Exception: report.update(status="INVALID_SYSTEM",infrastructure_status="INVALID_SYSTEM")
                else: adapter=build_authorized_client(LiveAuthorization(True,p["provider"],p["model"],"USD",Decimal(p["budget"]["hard_cap_usd"]),p["budget"]["max_provider_attempts"],p["budget"]["price_source"],max_episodes=4,episode_cap=4),config).adapter
        if report["status"]!="RUNNING":
            report["episodes"]=[{**_empty_episode(i,report["status"]),"manifest_position":i["manifest_position"]} for i in items]; _write(report,report_path); return runner.records.write_json("formal_source_block_run.json",report)
    if adapter is None: raise ValueError("fake requires adapter")
    ledger=CostLedger(LiveAuthorization(True,p["provider"],p["model"],"USD",Decimal(p["budget"]["hard_cap_usd"]),p["budget"]["max_provider_attempts"],p["budget"]["price_source"],max_episodes=4,episode_cap=4)); upstream=ROOT/"benchmarks/continual-learning-bench"
    for n,i in enumerate(items):
        task=DatabaseExplorationAdapter(upstream_root=upstream,db_path=upstream/"data/database_exploration/products.db",questions_path=upstream/"data/database_exploration/questions.json",records=runner.records,seed=42,max_queries_per_question=15,task_index=i["task_index"],allow_no_model_import_shim=mode=="fake"); view=task.reset(); prepared=runner.prepare_task(i["condition"],"formal-source-v1",i["id"],task_text=view.prompt); query=NativeQueryTool(task)
        def submit(answer:str,_m:dict[str,Any]):
            if answer and not task.completed: task.submit_answer(answer)
        try: answer,snap,metrics=run_tool_only_episode(prepared=prepared,manager=runner.manager,records=runner.records,database=query,adapter=adapter,ledger=ledger,config=config,prices=prices,transport_kind="fake_transport" if mode=="fake" else "live_provider",allowed_tool_names=ALLOWED_TOOLS,tool_call_limits={"query_sql":15},tool_call_group_limits={"file_operations":(FILE_TOOLS,8)},pre_request_check=(lambda:_offpeak_status({"offpeak_window":{"timezone":"Asia/Shanghai","start_local":"18:05:00","end_local":"08:55:00","minimum_remaining_seconds_for_new_episode":1080}})) if mode=="live" else None,stop_on_tool_limit_reached=True,terminal_only_after_tool_limit_names={"query_sql"},enable_optional_consolidation=True,before_consolidation=submit,consolidation_mode="deterministic_experience_commit_v1",consolidation_artifact_path=i["artifact_path"],raw_source_label=i["id"])
        except Exception as exc:
            events=_events(runner.records.path,prepared.session.attempt_id)
            if mode=="live": _consume_after_dispatch(authorization_path,events,runner.run_id)
            row=_episode_report(item=i,view=view,prepared=prepared,task=task,query_tool=query,snapshot=None,metrics=None,events=events,native=None,exception_chain={"class":type(exc).__name__,"message":str(exc)}); row["manifest_position"]=i["manifest_position"]; report["episodes"].append(row); report["status"]="INVALID_INFRA" if row["analysis_status"]=="INVALID_INFRA" else "INVALID_SYSTEM"; report["episodes"] += [{**_empty_episode(x,report["status"]),"manifest_position":x["manifest_position"]} for x in items[n+1:]]; break
        events=_events(runner.records.path,prepared.session.attempt_id)
        if mode=="live": _consume_after_dispatch(authorization_path,events,runner.run_id)
        native=task.evaluate_native() if task.completed else None; row=_episode_report(item=i,view=view,prepared=prepared,task=task,query_tool=query,snapshot=snap,metrics=metrics,events=events,native=native); row.update(manifest_position=i["manifest_position"],raw_experience=(metrics.get("raw_experience")),input_snapshot_hash=prepared.session.parent_snapshot_id,inheritance_source=None,contamination_checks={"development_source_mounted":False,"evaluator_reference_visible":False}); report["episodes"].append(row)
    report["provider_attempts"]=sum(x["provider_attempts"] for x in report["episodes"]); report["provider_responses"]=sum(x["provider_responses"] for x in report["episodes"]); report["known_cost_estimate"]=str(ledger.settled); report["unknown_billing_attempts"]=sum(x["billing_unknown"] for x in report["episodes"]); report["status"]="COMPLETED" if report["status"]=="RUNNING" else report["status"]; _write(report,report_path); return runner.records.write_json("formal_source_block_run.json",report)

def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument("--pending",type=Path,required=True); ap.add_argument("--authorization",type=Path,required=True); ap.add_argument("--output-root",type=Path,default=Path("artifacts/experience_value/formal_source")); g=ap.add_mutually_exclusive_group(required=True); g.add_argument("--plan-only",action="store_true"); g.add_argument("--fake",action="store_true"); g.add_argument("--live",action="store_true"); x=ap.parse_args(); print(execute(pending_path=x.pending,authorization_path=x.authorization,output_root=x.output_root,mode="plan-only" if x.plan_only else "fake" if x.fake else "live"))
if __name__=="__main__": main()
