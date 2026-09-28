"""Core agent loop: agent -> tools -> agent orchestration.

Drives the LLM client through ``max_turns`` iterations, dispatches tool calls,
feeds results back into the conversation, and emits events (``model.decision``,
``reasoning``, ``tool.completed``) to both the ``EventLogger`` and an optional
``emit`` callback for live UI streaming.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from prompts.system_prompt import SYSTEM_PROMPT
from tools import dispatch, tool_schemas
from memory.formatter import format_memories

from llm.adapters import OpenAICompatibleAdapter


def _build_conversation(
    messages: list[dict[str, str]],
    data_dir: Path,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Prepend the system prompt (with memory injection) to user messages.

    ``history`` is a list of prior ``role``/``content`` messages from the
    same conversation.  They are spliced in *before* the newest user turn so
    the model sees the full conversation context.
    """
    system_content = SYSTEM_PROMPT.format(today=datetime.now().strftime("%Y-%m-%d"))
    memories = format_memories(data_dir)
    if memories:
        system_content += "\n\n# 已知的用户长期记忆\n" + memories
    convo: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    if history:
        convo.extend(list(history))
    convo.extend(list(messages))
    return convo


def run_loop(
    *,
    client: Any,
    model_name: str,
    convo: list[dict[str, Any]],
    logger: Any,
    max_turns: int,
    emit: Callable[[str, dict[str, Any]], None] | None,
    ctx: dict[str, Any],
    adapter: Any | None = None,
    metrics: dict[str, Any] | None = None,
    allowed_tool_names: set[str] | None = None,
    max_tool_calls: int | None = None,
    tool_call_limits: dict[str, int] | None = None,
    tool_call_group_limits: dict[str, tuple[set[str], int]] | None = None,
    stop_on_tool_limit_reached: bool = False,
    terminal_only_after_tool_limit_names: set[str] | None = None,
    max_total_tokens: int | None = None,
    max_latency_seconds: float | None = None,
    should_stop: Callable[[], bool] | None = None,
    tool_schema_provider: Callable[[set[str] | None], list[dict[str, Any]]] | None = None,
    tool_dispatcher: Callable[[str, dict[str, Any], dict[str, Any], set[str] | None], str] | None = None,
) -> str:
    """Execute the agent loop. Returns the final assistant answer.

    ``should_stop`` is polled at turn boundaries, between stream chunks and
    after each tool execution; when it returns True the loop stops early
    (collaborative cancellation for the UI stop button).
    """
    adapter = adapter or OpenAICompatibleAdapter(client)
    run_metrics = metrics if metrics is not None else {}
    started = time.perf_counter()
    run_metrics.update({
        "llm_calls": 0,
        "tool_calls": 0,
        # Count proposals separately from dispatched calls.  A proposal can be
        # intentionally rejected before dispatch by a stage with an empty
        # schema (for example deterministic experience generation).
        "tool_calls_proposed": 0,
        "tool_calls_by_name": {},
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "success": False,
        "runner_stop_reason": None,
    })
    answer = ""
    cancelled = False
    # A public native-query cap may still need one ordinary-text decision after
    # the last legal feedback.  This state is deliberately narrow: it removes
    # every tool schema and consumes one of ``max_turns``; it is not a bonus
    # request or a way to execute another query.
    terminal_only_next = False
    try:
        for turn in range(1, max_turns + 1):
            if should_stop is not None and should_stop():
                cancelled = True
                run_metrics["runner_stop_reason"] = "cancelled"
                logger.emit("run.cancelled", step=turn, reason="stopped by user")
                break
            budget_reasons: list[str] = []
            if max_total_tokens is not None and run_metrics["total_tokens"] >= max_total_tokens:
                budget_reasons.append("token budget exhausted")
            if max_latency_seconds is not None and time.perf_counter() - started >= max_latency_seconds:
                budget_reasons.append("latency budget exhausted")
            if budget_reasons:
                logger.emit("budget.stopped", step=turn, reasons=budget_reasons)
                run_metrics["runner_stop_reason"] = "; ".join(budget_reasons)
                break
            reasoning_parts: list[str] = []
            assistant_content = ""
            tool_calls: list[dict[str, Any]] = []
            usage: dict[str, int] = {}
            remaining_tool_calls = (
                None
                if max_tool_calls is None
                else max(0, max_tool_calls - run_metrics["tool_calls"])
            )

            try:
                schema_provider = tool_schema_provider or tool_schemas
                available_tools = [] if (terminal_only_next or remaining_tool_calls == 0) else schema_provider(allowed_tool_names)
                for chunk in adapter.stream(model_name=model_name, messages=convo, tools=available_tools):
                    if should_stop is not None and should_stop():
                        cancelled = True
                        break
                    if chunk.reasoning:
                        reasoning_parts.append(chunk.reasoning)
                        logger.emit("reasoning", text=chunk.reasoning)
                        if emit:
                            emit("reasoning", {"text": chunk.reasoning})
                    if chunk.content:
                        assistant_content += chunk.content
                        # 回答增量实时落盘，前端轮询即可获得打字机流式效果
                        logger.emit("answer.delta", step=turn, text=chunk.content)
                        if emit:
                            emit("answer.delta", {"text": chunk.content, "step": turn})
                    if chunk.tool_call is not None:
                        tool_calls.append(chunk.tool_call)
                    if chunk.usage:
                        usage.update(chunk.usage)
            except (TypeError, NotImplementedError):
                # Preserve stage-level tool isolation on non-streaming fallback.
                response = adapter.complete(
                    model_name=model_name,
                    messages=convo,
                    tools=available_tools,
                )
                assistant_content = response.content
                reasoning_parts.append(response.reasoning)
                tool_calls.extend(response.tool_calls)
                usage.update(response.usage)
                # 非流式回退路径：整段回答作为一次增量下发，保持前端渲染一致
                if assistant_content:
                    logger.emit("answer.delta", step=turn, text=assistant_content)
                    if emit:
                        emit("answer.delta", {"text": assistant_content, "step": turn})

            # Persist the model-proposed calls before budget truncation.  This
            # keeps an audit trail for calls which were proposed but not
            # dispatched because the per-episode cap was reached.
            proposed_call_ids = [str(tc.get("id", "")) for tc in tool_calls]
            run_metrics["tool_calls_proposed"] += len(tool_calls)
            for tc in tool_calls:
                logger.emit(
                    "tool.proposed", step=turn, attempt_id=ctx.get("attempt_id"),
                    tool_call_id=tc.get("id"), tool=tc.get("name"),
                    raw_arguments=tc.get("arguments"), proposed_by_model=True,
                )

            budget_rejected_calls: list[dict[str, Any]] = []
            rejection_reasons: dict[str, str] = {}
            if remaining_tool_calls is not None and len(tool_calls) > remaining_tool_calls:
                budget_rejected_calls = tool_calls[remaining_tool_calls:]
                rejection_reasons.update({str(call.get("id", "")): "tool_budget_exhausted" for call in budget_rejected_calls})
                logger.emit(
                    "tool.budget_truncated",
                    step=turn,
                    requested=len(tool_calls),
                    permitted=remaining_tool_calls,
                    proposed_tool_call_ids=proposed_call_ids,
                    dropped_tool_call_ids=proposed_call_ids[remaining_tool_calls:],
                )
                tool_calls = tool_calls[:remaining_tool_calls]
            # A public task can have a native SQL allowance alongside a
            # separate optional file-operation allowance.  Enforce both here,
            # before dispatch, so one category cannot silently consume the
            # other.  Rejected proposals still receive paired feedback.
            if tool_call_limits is not None:
                per_turn_counts: dict[str, int] = {}
                permitted_calls: list[dict[str, Any]] = []
                for call in tool_calls:
                    name = str(call.get("name", ""))
                    limit = tool_call_limits.get(name)
                    used = int(run_metrics["tool_calls_by_name"].get(name, 0)) + per_turn_counts.get(name, 0)
                    if limit is not None and used >= limit:
                        budget_rejected_calls.append(call)
                        rejection_reasons[str(call.get("id", ""))] = f"{name}_budget_exhausted"
                    elif tool_call_group_limits is not None and any(
                        sum(int(run_metrics["tool_calls_by_name"].get(member, 0)) + per_turn_counts.get(member, 0) for member in members) >= group_limit
                        for _group, (members, group_limit) in tool_call_group_limits.items()
                        if name in members
                    ):
                        group = next(group for group, (members, group_limit) in tool_call_group_limits.items()
                                     if name in members and sum(int(run_metrics["tool_calls_by_name"].get(member, 0)) + per_turn_counts.get(member, 0) for member in members) >= group_limit)
                        budget_rejected_calls.append(call)
                        rejection_reasons[str(call.get("id", ""))] = f"{group}_budget_exhausted"
                    else:
                        permitted_calls.append(call)
                        per_turn_counts[name] = per_turn_counts.get(name, 0) + 1
                tool_calls = permitted_calls

            run_metrics["llm_calls"] += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                run_metrics[key] += usage.get(key, 0)

            reasoning = "".join(reasoning_parts)
            logger.emit(
                "model.decision",
                step=turn,
                action="terminal_only" if terminal_only_next else ("tool_call" if tool_calls else "finish"),
                summary=assistant_content[:200] or "(调用工具)",
                reasoning=reasoning,
            )
            if emit and reasoning:
                emit("reasoning", {"text": "", "done": True})

            if terminal_only_next:
                # No dispatched/rejected tool loop follows the terminal-only
                # decision.  A provider that nevertheless emits a call has
                # not supplied an ordinary text answer and cannot obtain a
                # sixteenth SQL action or another chance.
                if tool_calls:
                    for tc in tool_calls:
                        logger.emit(
                            "tool.rejected", step=turn, attempt_id=ctx.get("attempt_id"), tool_call_id=tc.get("id"),
                            tool=tc.get("name"), arguments={}, proposed_by_model=True,
                            arguments_parsed=False, dispatched=False, rejection_reason="terminal_only_no_tools",
                            counted_against="tool_calls", count_units=0,
                        )
                    logger.emit("terminal_answer.rejected", step=turn, reason="terminal_only_model_proposed_tool")
                    run_metrics["runner_stop_reason"] = "terminal_only_tool_call_rejected"
                    break
                answer = assistant_content
                logger.emit(
                    "terminal_answer.submitted", step=turn, attempt_id=ctx.get("attempt_id"),
                    text_present=bool(answer), tool_schema_count=0,
                )
                run_metrics["runner_stop_reason"] = "terminal_answer_submitted" if answer else "terminal_only_empty_answer"
                break

            # A locally rejected call still needs paired tool feedback so the
            # model can choose another action or give a terminal answer while
            # request capacity remains.  Only a genuine no-tool response is
            # terminal here.
            if not tool_calls and not budget_rejected_calls:
                answer = assistant_content
                # A provider can return text that looks like a tool request
                # after the runner has removed schemas at the tool cap.  It is
                # not a normal terminal answer: make the enforced limit
                # visible to callers and reports.
                run_metrics["runner_stop_reason"] = (
                    "tool_budget_exhausted" if remaining_tool_calls == 0 else "model_finished"
                )
                break

            run_metrics["tool_calls"] += len(tool_calls)
            for call in tool_calls:
                name = str(call.get("name", ""))
                run_metrics["tool_calls_by_name"][name] = int(run_metrics["tool_calls_by_name"].get(name, 0)) + 1
            # 防御性过滤：确保 name 和 arguments 非空，避免 API 400
            valid_tool_calls = [
                tc for tc in tool_calls
                if tc.get("name") and tc.get("arguments")
            ]
            if not valid_tool_calls and tool_calls:
                logger.emit("tool.filtered_empty", step=turn, count=len(tool_calls))
                answer = assistant_content
                run_metrics["runner_stop_reason"] = "invalid_tool_call"
                break
            # Keep model/provider tool-call pairing explicit even when a
            # proposed call was rejected by the local tool budget. Rejected
            # calls do not increment the tool count or reach a dispatcher.
            history_tool_calls = [
                tc for tc in valid_tool_calls + budget_rejected_calls
                if tc.get("name") and tc.get("arguments")
            ]
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": assistant_content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in history_tool_calls
                ],
            }
            # DeepSeek thinking models require the reasoning trace to be
            # returned with the assistant tool-call message on the next turn.
            # Omitting it causes a 400 in multi-turn tool use.
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            convo.append(assistant_msg)

            rejected_ids = {tc.get("id") for tc in budget_rejected_calls}
            for tc in history_tool_calls:
                if tc.get("id") not in rejected_ids:
                    continue
                try:
                    rejected_arguments = json.loads(tc["arguments"] or "{}")
                    rejected_parse_ok = True
                except json.JSONDecodeError:
                    rejected_arguments = {}
                    rejected_parse_ok = False
                reason = rejection_reasons.get(str(tc.get("id", "")), "tool_budget_exhausted")
                rejection_feedback = f"工具执行被拒绝：{reason.replace('_', ' ')}"
                logger.emit(
                    "tool.rejected", step=turn, attempt_id=ctx.get("attempt_id"), tool_call_id=tc.get("id"),
                    tool=tc.get("name"), arguments=rejected_arguments, proposed_by_model=True,
                    arguments_parsed=rejected_parse_ok, dispatched=False, rejection_reason=reason,
                    counted_against="tool_calls", count_units=0,
                )
                convo.append({"role": "tool", "tool_call_id": tc["id"], "content": rejection_feedback})
                logger.emit(
                    "tool.feedback_appended", step=turn, attempt_id=ctx.get("attempt_id"),
                    tool_call_id=tc.get("id"), feedback_appended_to_conversation=True,
                    feedback_kind="budget_rejection",
                )

            for tc in valid_tool_calls:
                name = tc["name"]
                parse_ok = True
                try:
                    arguments = json.loads(tc["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                    parse_ok = False
                dispatcher = tool_dispatcher or dispatch
                dispatch_ctx = {
                    **ctx,
                    "tool_call_id": tc.get("id"),
                    "step": turn,
                    "visible_tool_feedback_count": sum(1 for message in convo if message.get("role") == "tool"),
                    "agent_trajectory_message_count": len(convo),
                }
                result = dispatcher(name, arguments, dispatch_ctx, allowed_tool_names)
                result = __import__("tools.utils", fromlist=["process_tool_result"]).process_tool_result(result)
                ok = not result.startswith(("参数校验失败：", "工具执行失败：", "工具不存在：", "工具执行被拒绝："))
                logger.emit(
                    "tool.completed",
                    step=turn, attempt_id=ctx.get("attempt_id"), tool_call_id=tc.get("id"),
                    tool=name,
                    arguments=arguments,
                    proposed_by_model=True, arguments_parsed=parse_ok,
                    dispatched=True, allowed_by_tool_policy=allowed_tool_names is None or name in allowed_tool_names,
                    counted_against="tool_calls", count_units=1,
                    result={"ok": ok, "output": result} if ok else {"ok": False, "error": result},
                )
                convo.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
                logger.emit(
                    "tool.feedback_appended", step=turn, attempt_id=ctx.get("attempt_id"),
                    tool_call_id=tc.get("id"), feedback_appended_to_conversation=True,
                )
                if should_stop is not None and should_stop():
                    cancelled = True
                    break
            if stop_on_tool_limit_reached and not cancelled:
                reached: list[str] = []
                if tool_call_limits is not None:
                    reached.extend(
                        name for name, limit in tool_call_limits.items()
                        if int(run_metrics["tool_calls_by_name"].get(name, 0)) >= limit
                    )
                if tool_call_group_limits is not None:
                    reached.extend(
                        group for group, (members, limit) in tool_call_group_limits.items()
                        if sum(int(run_metrics["tool_calls_by_name"].get(member, 0)) for member in members) >= limit
                    )
                if reached:
                    terminal_names = terminal_only_after_tool_limit_names or set()
                    if terminal_names.intersection(reached):
                        if run_metrics["llm_calls"] >= max_turns:
                            logger.emit(
                                "terminal_answer.unavailable", step=turn,
                                reasons=["model_decision_budget_reached"],
                                reached_tool_limits=sorted(terminal_names.intersection(reached)),
                            )
                            run_metrics["runner_stop_reason"] = "terminal_answer_unavailable_model_decision_budget_reached"
                            break
                        logger.emit(
                            "terminal_answer.decision_available", step=turn,
                            reached_tool_limits=sorted(terminal_names.intersection(reached)),
                            next_decision_number=turn + 1, max_turns=max_turns, tool_schema_count=0,
                        )
                        terminal_only_next = True
                        continue
                    logger.emit("budget.stopped", step=turn, reasons=[f"{name}_budget_reached" for name in reached])
                    run_metrics["runner_stop_reason"] = "; ".join(f"{name}_budget_reached" for name in reached)
                    break
            if cancelled:
                logger.emit("run.cancelled", step=turn, reason="stopped by user")
                break
        else:
            # for 循环正常结束 = 达到 max_turns 上限，模型还在调用工具就被截断
            if not answer:
                logger.emit("budget.stopped", step=max_turns, reasons=["max turns reached"])
                run_metrics["runner_stop_reason"] = "max_turns_reached"
        if cancelled and run_metrics["runner_stop_reason"] is None:
            run_metrics["runner_stop_reason"] = "cancelled"
        run_metrics["success"] = bool(answer)
        return answer
    finally:
        run_metrics["total_tokens"] = run_metrics["prompt_tokens"] + run_metrics["completion_tokens"] or run_metrics["total_tokens"]
        run_metrics["latency_seconds"] = round(time.perf_counter() - started, 6)
