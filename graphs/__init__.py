"""Agent graph: the tool-using LLM loop (agent -> tools -> agent).

Mirrors scilink-agent's ``graphs/`` layering with a split between the high-level
executor (``agent.py``) and the core loop + streaming logic (``loop.py``,
``streaming.py``).
"""

from .agent import run_agent

__all__ = ["run_agent"]
