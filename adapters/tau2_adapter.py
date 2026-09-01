"""τ²-Bench adapter for the routing arms and legacy S0--S4 ablations.

The adapter deliberately keeps τ²'s Environment, Orchestrator, and evaluator
as the source of truth.  It only controls which tools the agent sees and how a
planner/executor/verifier handoff is represented.

S3/S4 use an isolated, same-action replay after the official write.  This is a
safe smoke-test implementation of causal replay: the copied environment is
never used for the official score.  Edge-masking ablations can be added later
without changing the τ² integration boundary.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from tau2.agent.base import BaseAgent, ValidAgentInputMessage
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from tau2.environment.environment import Environment
from tau2.environment.tool import Tool
from tau2.environment.toolkit import ToolType
from tau2.utils.llm_utils import generate
from multiagent.routing import LEGACY_CONDITIONS, ROUTING_CONDITIONS


CONDITIONS = {
    **ROUTING_CONDITIONS,
    **LEGACY_CONDITIONS,
}


@dataclass
class Tau2AdapterState:
    """Mutable state carried through τ²'s turn-based agent interface."""

    messages: list[Message] = field(default_factory=list)
    phase: str = "conversation"
    handoff: Optional[dict[str, Any]] = None
    pre_write_environment: Optional[Environment] = None
    replay: Optional[dict[str, Any]] = None
    route: Optional[str] = None
    route_decision: Optional[dict[str, Any]] = None


def _usage_total(left: Optional[dict], right: Optional[dict]) -> dict:
    left = left or {}
    right = right or {}
    return {
        "prompt_tokens": int(left.get("prompt_tokens", 0) or 0)
        + int(right.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(left.get("completion_tokens", 0) or 0)
        + int(right.get("completion_tokens", 0) or 0),
    }


def _merge_hidden_call(
    visible: AssistantMessage,
    hidden: AssistantMessage,
    *,
    phase: str,
) -> AssistantMessage:
    """Account for an internal planner call on the visible τ² message."""

    visible.cost = (visible.cost or 0.0) + (hidden.cost or 0.0)
    visible.usage = _usage_total(visible.usage, hidden.usage)
    raw_data = dict(visible.raw_data or {})
    adapter_data = dict(raw_data.get("tau2_adapter") or {})
    adapter_data.setdefault("internal_calls", []).append(
        {
            "phase": phase,
            "cost": hidden.cost,
            "usage": hidden.usage,
            "content": hidden.content,
            "tool_calls": [call.name for call in (hidden.tool_calls or [])],
        }
    )
    raw_data["tau2_adapter"] = adapter_data
    visible.raw_data = raw_data
    return visible


class Tau2AdapterAgent(BaseAgent[Tau2AdapterState]):
    """S0--S4 agent that runs inside the official τ² orchestrator."""

    FALLBACK_ALLOWLIST = {"transfer_to_human_agents"}

    def __init__(
        self,
        *,
        condition: str,
        environment: Environment,
        llm: str,
        llm_args: Optional[dict[str, Any]] = None,
        lesson_context: str = "（无历史 lesson）",
        task_context: str = "",
        complex_condition: str = "S3",
        route_override: Optional[str] = None,
    ) -> None:
        if condition not in CONDITIONS:
            raise ValueError(f"Unknown τ² adapter condition: {condition}")
        self.condition = condition
        if complex_condition not in LEGACY_CONDITIONS:
            raise ValueError(f"Unknown complex controller: {complex_condition}")
        self.complex_condition = complex_condition
        if condition == "Complex-only":
            self.execution_condition = complex_condition
        elif condition == "Oracle":
            if route_override not in {"single_agent", "complex"}:
                raise ValueError("Oracle requires route_override=single_agent or complex")
            self.execution_condition = "S0" if route_override == "single_agent" else complex_condition
        elif condition == "Adaptive":
            self.execution_condition = None
        else:
            self.execution_condition = condition
        self.route_override = route_override
        self.environment = environment
        self.llm = llm
        self.llm_args = dict(llm_args or {})
        self.lesson_context = lesson_context
        self.task_context = task_context
        self.all_tools = list(environment.get_tools())
        self.tool_by_name = {tool.name: tool for tool in self.all_tools}
        toolkit = environment.tools
        if toolkit is None:
            raise ValueError("τ² adapter requires an assistant tool kit")
        self.tool_types = {
            tool.name: toolkit.tool_type(tool.name) for tool in self.all_tools
        }
        self.read_tools = [
            tool
            for tool in self.all_tools
            if self.tool_types[tool.name] == ToolType.READ
        ]
        self.write_tools = [
            tool
            for tool in self.all_tools
            if self.tool_types[tool.name] == ToolType.WRITE
        ]
        self.executor_tools = self.write_tools + [
            self.tool_by_name[name]
            for name in self.FALLBACK_ALLOWLIST
            if name in self.tool_by_name
        ]
        self.events: list[dict[str, Any]] = []

    @property
    def system_prompt(self) -> str:
        return (
            "You are a τ²-Bench customer-service agent. Follow the domain policy "
            "exactly, use tools only when needed, and never claim a state change "
            "without evidence. Return valid JSON-compatible tool calls.\n\n"
            f"DOMAIN POLICY:\n{self.environment.get_policy()}"
        )

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> Tau2AdapterState:
        state = Tau2AdapterState(messages=copy.deepcopy(message_history or []))
        if self.condition == "Adaptive":
            state.phase = "routing"
        elif self.execution_condition != "S0":
            state.phase = "planning"
        else:
            state.phase = "conversation"
        return state

    def _call(
        self,
        *,
        state: Tau2AdapterState,
        system_prompt: str,
        tools: Optional[list[Tool]],
        phase: str,
        tool_choice: Optional[str] = None,
    ) -> AssistantMessage:
        messages = [SystemMessage(role="system", content=system_prompt)] + state.messages
        kwargs = dict(self.llm_args)
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if phase == "planner":
            # DeepSeek supports JSON mode.  The prompt still contains the
            # schema so providers that ignore this hint remain diagnosable.
            kwargs.setdefault("response_format", {"type": "json_object"})
        response = generate(
            model=self.llm,
            messages=messages,
            tools=tools,
            **kwargs,
        )
        self.events.append(
            {
                "phase": phase,
                "cost": response.cost,
                "usage": response.usage,
                "content": response.content,
                "tool_calls": [call.name for call in (response.tool_calls or [])],
            }
        )
        return response

    @staticmethod
    def _append(state: Tau2AdapterState, message: Optional[Message]) -> None:
        if message is not None:
            state.messages.append(message)

    @staticmethod
    def _json_object(content: Optional[str]) -> Optional[dict[str, Any]]:
        if not content:
            return None
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                value = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        return value if isinstance(value, dict) else None

    def _planner_prompt(self) -> str:
        style = {
            "S1": "Use the fixed read-plan-write-verify controller.",
            "S2": "Adapt retrieval to the request and use the minimum sufficient reads.",
            "S3": "Use the adaptive plan; the selected write will be replayed on an isolated copy.",
            "S4": "Use the adaptive plan and the bounded lesson context below.",
        }[self.execution_condition]
        return (
            f"{self.system_prompt}\n\n"
            "You are now the read-only planner. You may call READ tools only. "
            "Do not call write tools or fallback tools. When you have enough evidence, "
            "stop calling tools and return exactly one JSON object with this schema:\n"
            '{"status":"READY","tool":"<write tool>","arguments":{},'
            '"evidence":["..."],"reason":"..."}\n'
            'or {"status":"BLOCKED","tool":null,"arguments":{},'
            '"evidence":[],"reason":"..."}.\n'
            f"{style}\n"
            f"LESSON CONTEXT:\n{self.lesson_context}"
        )

    def _router_prompt(self) -> str:
        return (
            f"{self.system_prompt}\n\n"
            "You are a task-complexity router. Do not call tools and do not solve the task. "
            "Choose single_agent when one direct action or a short linear interaction is enough. "
            "Choose complex when the task needs conditional dependencies, multiple records/tools, "
            "ordering, bulk changes, verification, or recovery. Be conservative when uncertain. "
            "Return exactly one JSON object: {\"route\":\"single_agent|complex\","
            "\"complexity\":\"simple|complex|uncertain\",\"confidence\":0.0,"
            "\"predicted_steps\":1,\"reason\":\"...\"}.\n\n"
            f"TASK:\n{self.task_context}"
        )

    def _apply_route(self, state: Tau2AdapterState, response: AssistantMessage) -> None:
        parsed = self._json_object(response.content) or {}
        route = parsed.get("route")
        confidence = parsed.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if route == "single_agent" and confidence >= 0.65:
            state.route = "single_agent"
            self.execution_condition = "S0"
        else:
            state.route = "complex"
            self.execution_condition = self.complex_condition
        state.route_decision = {
            "route": state.route,
            "complexity": parsed.get("complexity", "uncertain"),
            "confidence": confidence,
            "predicted_steps": parsed.get("predicted_steps", 1),
            "reason": str(parsed.get("reason") or ""),
        }
        self.events.append({"phase": "route_selection", **state.route_decision})

    def _executor_prompt(self, handoff: dict[str, Any]) -> str:
        return (
            f"{self.system_prompt}\n\n"
            "You are now the write-only executor. Use exactly the validated tool "
            "and arguments below, with one tool call. Do not search or invent values. "
            "If the handoff is insufficient, return a short BLOCKED message and make "
            "no tool call.\n\n"
            "VALIDATED HANDOFF:\n"
            + json.dumps(handoff, ensure_ascii=False)
        )

    def _verifier_prompt(self) -> str:
        return (
            f"{self.system_prompt}\n\n"
            "You are now the read-only verifier. Inspect the available tool results "
            "and verify whether the user's requested state change is present. Return "
            "a concise final response to the user. Do not claim success without state evidence."
        )

    def _safe_block(self, reason: str) -> AssistantMessage:
        return AssistantMessage(
            role="assistant",
            content=f"BLOCKED: {reason} ###TRANSFER###",
            raw_data={"tau2_adapter": {"blocked": reason}},
        )

    def set_seed(self, seed: int) -> None:
        """Pass τ²'s per-trial seed through to the model when supported."""
        self.llm_args["seed"] = seed

    def _validate_planner_handoff(self, response: AssistantMessage) -> Optional[dict[str, Any]]:
        parsed = self._json_object(response.content)
        if parsed is None:
            return None
        status = parsed.get("status")
        if status == "BLOCKED":
            return parsed
        tool_name = parsed.get("tool")
        arguments = parsed.get("arguments")
        if status != "READY" or not isinstance(tool_name, str) or not isinstance(arguments, dict):
            return None
        if tool_name not in {tool.name for tool in self.write_tools} | self.FALLBACK_ALLOWLIST:
            return None
        if tool_name not in self.tool_by_name:
            return None
        tool = self.tool_by_name[tool_name]
        required = {
            name
            for name, field in tool.params.model_fields.items()
            if field.is_required()
        }
        missing = sorted(required - set(arguments))
        if missing:
            return {
                "status": "BLOCKED",
                "tool": None,
                "arguments": {},
                "evidence": list(parsed.get("evidence") or []),
                "reason": f"Planner handoff is missing required arguments: {', '.join(missing)}",
            }
        return {
            "status": "READY",
            "tool": tool_name,
            "arguments": arguments,
            "evidence": parsed.get("evidence") or [],
            "reason": str(parsed.get("reason") or ""),
        }

    def _capture_replay_snapshot(self, state: Tau2AdapterState) -> None:
        if self.execution_condition in {"S3", "S4"} and state.pre_write_environment is None:
            state.pre_write_environment = copy.deepcopy(self.environment)

    def _run_isolated_replay(self, state: Tau2AdapterState) -> None:
        if self.execution_condition not in {"S3", "S4"} or not state.handoff or not state.pre_write_environment:
            return
        handoff = state.handoff
        try:
            replay_env = copy.deepcopy(state.pre_write_environment)
            replay_call = ToolCall(
                id="tau2-adapter-replay",
                name=handoff["tool"],
                arguments=handoff["arguments"],
                requestor="assistant",
            )
            replay_response = replay_env.get_response(replay_call)
            state.replay = {
                "mode": "isolated_same_action",
                "tool": handoff["tool"],
                "pre_db_hash": state.pre_write_environment.get_db_hash(),
                "replay_db_hash": replay_env.get_db_hash(),
                "replay_response_error": replay_response.error,
                "official_db_hash": self.environment.get_db_hash(),
            }
            state.replay["replay_matches_official"] = (
                state.replay["replay_db_hash"] == state.replay["official_db_hash"]
            )
        except Exception as exc:  # pragma: no cover - diagnostic path
            state.replay = {"mode": "isolated_same_action", "error": str(exc)}
        self.events.append({"phase": "causal_replay", **(state.replay or {})})

    def _s0(self, message: ValidAgentInputMessage, state: Tau2AdapterState) -> AssistantMessage:
        self._append(state, message)
        response = self._call(
            state=state,
            system_prompt=self.system_prompt,
            tools=self.all_tools,
            phase="single_agent",
        )
        self._append(state, response)
        return response

    def _phased(self, message: ValidAgentInputMessage, state: Tau2AdapterState) -> AssistantMessage:
        self._append(state, message)
        routing_response: Optional[AssistantMessage] = None

        if state.phase == "routing":
            router = self._call(
                state=state,
                system_prompt=self._router_prompt(),
                tools=[],
                phase="router",
            )
            self._apply_route(state, router)
            if state.route == "single_agent":
                state.phase = "conversation"
                response = self._call(
                    state=state,
                    system_prompt=self.system_prompt,
                    tools=self.all_tools,
                    phase="single_agent",
                )
                response = _merge_hidden_call(response, router, phase="router")
                self._append(state, response)
                return response
            routing_response = router
            state.phase = "planning"

        if state.phase == "planning":
            planner = self._call(
                state=state,
                system_prompt=self._planner_prompt(),
                tools=self.read_tools,
                phase="planner",
            )
            if routing_response is not None:
                planner = _merge_hidden_call(planner, routing_response, phase="router")
            if planner.is_tool_call():
                if any(call.name not in {tool.name for tool in self.read_tools} for call in planner.tool_calls or []):
                    state.phase = "done"
                    return self._safe_block("planner attempted a non-read tool")
                self._append(state, planner)
                return planner

            handoff = self._validate_planner_handoff(planner)
            if handoff is None:
                state.phase = "done"
                return self._safe_block("planner did not return a valid JSON contract")
            if handoff.get("status") == "BLOCKED":
                # BLOCKED means that the planner needs user information; it
                # is not a terminal failure.  Keep planning active and turn
                # the structured reason into a normal assistant question so
                # τ²'s user simulator can supply the missing evidence.
                reason = str(handoff.get("reason") or "some required information")
                clarification = AssistantMessage(
                    role="assistant",
                    content=f"Before I proceed, I need one clarification: {reason}",
                    cost=planner.cost,
                    usage=planner.usage,
                    raw_data={
                        "tau2_adapter": {
                            "phase": "planner",
                            "status": "BLOCKED",
                            "contract": handoff,
                        }
                    },
                )
                self._append(state, clarification)
                return clarification

            state.handoff = handoff
            self._capture_replay_snapshot(state)
            executor = self._call(
                state=state,
                system_prompt=self._executor_prompt(handoff),
                tools=self.executor_tools,
                phase="executor",
                tool_choice="required",
            )
            executor = _merge_hidden_call(executor, planner, phase="planner")
            if not executor.is_tool_call():
                state.phase = "done"
                self._append(state, executor)
                return executor
            if len(executor.tool_calls or []) != 1:
                state.phase = "done"
                return self._safe_block("executor must emit exactly one tool call")
            call = executor.tool_calls[0]
            if call.name != handoff["tool"] or call.arguments != handoff["arguments"]:
                state.phase = "done"
                return self._safe_block("executor call did not match the validated handoff")
            state.phase = "executing"
            self._append(state, executor)
            return executor

        if state.phase == "executing":
            self._run_isolated_replay(state)
            verifier = self._call(
                state=state,
                system_prompt=self._verifier_prompt(),
                tools=self.read_tools,
                phase="verifier",
            )
            if verifier.is_tool_call():
                if any(call.name not in {tool.name for tool in self.read_tools} for call in verifier.tool_calls or []):
                    state.phase = "done"
                    return self._safe_block("verifier attempted a non-read tool")
                state.phase = "verifying"
                self._append(state, verifier)
                return verifier
            state.phase = "done"
            self._append(state, verifier)
            return verifier

        if state.phase == "verifying":
            verifier = self._call(
                state=state,
                system_prompt=self._verifier_prompt(),
                tools=self.read_tools,
                phase="verifier",
            )
            if verifier.is_tool_call():
                if any(call.name not in {tool.name for tool in self.read_tools} for call in verifier.tool_calls or []):
                    state.phase = "done"
                    return self._safe_block("verifier attempted a non-read tool")
                self._append(state, verifier)
                return verifier
            state.phase = "done"
            self._append(state, verifier)
            return verifier

        return self._safe_block("adapter phase already completed")

    def generate_next_message(
        self, message: ValidAgentInputMessage, state: Tau2AdapterState
    ) -> tuple[AssistantMessage, Tau2AdapterState]:
        if self.condition == "S0" or (
            self.condition in {"Complex-only", "Adaptive", "Oracle"}
            and self.execution_condition == "S0"
            and state.phase != "routing"
        ):
            response = self._s0(message, state)
        else:
            response = self._phased(message, state)
        return response, state
