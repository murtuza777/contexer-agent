"""Compile the loop: the nodes, the edges from ``routing.py``, and a checkpointer.

LangGraph was chosen for two things the classic loop cannot do: wait for a
person in the middle of a run (``interrupt``) and continue in a later
process (a checkpoint after every node). The spike behind that choice is
recorded in ``docs/agentic/architecture.md`` §8.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from contexer.graph.context import RunContext
from contexer.graph.nodes import make_nodes
from contexer.graph.routing import EDGES, NODES, TARGETS
from contexer.graph.state import LoopState

CHECKPOINT_FILE = "checkpoint.sqlite"


def build_graph(ctx: RunContext, checkpointer: BaseCheckpointSaver[Any]) -> Any:
    graph = StateGraph(LoopState)
    nodes = make_nodes(ctx)
    for name in NODES:
        graph.add_node(name, nodes[name])  # type: ignore[call-overload]
    graph.add_edge(START, "intent")
    for name, router in EDGES.items():
        graph.add_conditional_edges(name, router, list(TARGETS[name]))
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def step_limit(max_repair_rounds: int) -> int:
    """How many nodes one run may visit. An attempt is at most ten; the rest is room for corrections."""
    return 100 + 15 * (max_repair_rounds + 2)
