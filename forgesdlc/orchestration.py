"""Dependency-free execution or optional LangGraph nodes.

The optional LangGraph path must be integration-tested after installation.
SQLite evidence checkpoints below are not a full crash-resume implementation.
"""
from typing import TypedDict


class StepState(TypedDict):
    completed: list[str]


def execute_steps(steps, backend="stdlib"):
    if backend == "stdlib":
        completed = []
        for name, function in steps:
            function()
            completed.append(name)
        return {"completed": completed}
    if backend != "langgraph":
        raise ValueError("unknown orchestration backend")
    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError:
        raise RuntimeError("LangGraph not installed; use stdlib or install the graph extra") from None
    graph = StateGraph(StepState)
    prior = START
    for name, function in steps:
        def node(state, callback=function, step_name=name):
            callback()
            return {"completed": state["completed"] + [step_name]}
        graph.add_node(name, node)
        graph.add_edge(prior, name)
        prior = name
    graph.add_edge(prior, END)
    return graph.compile().invoke({"completed": []})
