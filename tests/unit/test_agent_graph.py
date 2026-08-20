"""
Unit tests for app/agent/graph.py.

These don't require Ollama (or any LLM provider) — the routing functions
are pure, and the full-turn tests patch each node's get_chat_model reference
directly with a fake model. They DO require real Redis, since the graph's
checkpointer keys off thread_id and app/redis_client.py-backed pieces are
exercised indirectly via the nodes.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import get_agent_graph, route_after_executor, route_after_planner, start_turn
from app.agent.nodes.planner import PlannerDecision


def test_graph_compiles_with_expected_nodes():
    graph = get_agent_graph()
    nodes = set(graph.get_graph().nodes.keys())
    assert {"planner", "executor", "approval_gate", "responder"} <= nodes


class TestRouteAfterPlanner:
    def test_tool_call_routes_to_executor(self):
        assert route_after_planner({"next_action": "tool_call"}) == "executor"

    def test_await_approval_routes_to_approval_gate(self):
        assert route_after_planner({"next_action": "await_approval"}) == "approval_gate"

    def test_respond_routes_to_responder(self):
        assert route_after_planner({"next_action": "respond"}) == "responder"

    def test_missing_next_action_defaults_to_responder(self):
        assert route_after_planner({"next_action": None}) == "responder"


class TestRouteAfterExecutor:
    def test_pending_approval_routes_to_approval_gate(self):
        state = {"pending_approval": {"id": "x", "action_type": "email.send"}}
        assert route_after_executor(state) == "approval_gate"

    def test_no_pending_approval_routes_to_responder(self):
        assert route_after_executor({"pending_approval": None}) == "responder"


@pytest.mark.usefixtures("redis_client")
class TestFullTurns:
    """Drives real graph.ainvoke() calls with the LLM layer swapped out."""

    async def test_direct_response_turn(self, monkeypatch):
        structured_model = MagicMock()
        structured_model.ainvoke = AsyncMock(return_value=PlannerDecision(next_action="respond"))
        planner_base_model = MagicMock()
        planner_base_model.with_structured_output.return_value = structured_model
        monkeypatch.setattr(
            "app.agent.nodes.planner.get_chat_model", lambda config: planner_base_model
        )

        responder_model = MagicMock()
        responder_model.ainvoke = AsyncMock(return_value=AIMessage(content="Hi there!"))
        monkeypatch.setattr(
            "app.agent.nodes.responder.get_chat_model", lambda config: responder_model
        )

        result = await start_turn(
            user_id="test-user",
            thread_id="test-graph-direct-response",
            state_update={"messages": [HumanMessage(content="Hello")]},
        )

        assert result["messages"][-1].content == "Hi there!"
        assert "__interrupt__" not in result

    async def test_side_effecting_tool_call_pauses_for_approval(self, monkeypatch):
        structured_model = MagicMock()
        structured_model.ainvoke = AsyncMock(
            return_value=PlannerDecision(
                next_action="tool_call",
                tool_name="email.send",
                tool_args={"to": ["friend@example.com"], "subject": "Hi", "body": "Hello!"},
            )
        )
        planner_base_model = MagicMock()
        planner_base_model.with_structured_output.return_value = structured_model
        monkeypatch.setattr(
            "app.agent.nodes.planner.get_chat_model", lambda config: planner_base_model
        )

        result = await start_turn(
            user_id="test-user",
            thread_id="test-graph-approval-pause",
            state_update={"messages": [HumanMessage(content="Email my friend")]},
        )

        assert "__interrupt__" in result
        interrupt = result["__interrupt__"][0]
        assert interrupt.value["type"] == "approval_request"
        assert interrupt.value["approval"]["action_type"] == "email.send"
        assert result["pending_approval"]["action_type"] == "email.send"

    async def test_non_side_effecting_tool_call_skips_approval(self, monkeypatch):
        """tasks.create isn't in SIDE_EFFECTING_TOOLS, so the graph should run
        it straight through to a real MCP call rather than pausing."""
        structured_model = MagicMock()
        structured_model.ainvoke = AsyncMock(
            return_value=PlannerDecision(
                next_action="tool_call",
                tool_name="tasks.create",
                tool_args={"title": "Book flights"},
            )
        )
        planner_base_model = MagicMock()
        planner_base_model.with_structured_output.return_value = structured_model
        monkeypatch.setattr(
            "app.agent.nodes.planner.get_chat_model", lambda config: planner_base_model
        )

        responder_model = MagicMock()
        responder_model.ainvoke = AsyncMock(return_value=AIMessage(content="Task created."))
        monkeypatch.setattr(
            "app.agent.nodes.responder.get_chat_model", lambda config: responder_model
        )

        async def fake_call_mcp_tool(tool_name, args):
            assert tool_name == "tasks.create"
            return {"id": "task-1", "title": args["title"]}

        monkeypatch.setattr("app.agent.nodes.executor.call_mcp_tool", fake_call_mcp_tool)

        result = await start_turn(
            user_id="test-user",
            thread_id="test-graph-non-side-effecting",
            state_update={"messages": [HumanMessage(content="Add a task to book flights")]},
        )

        assert "__interrupt__" not in result
        assert result["tool_result"]["status"] == "ok"
        assert result["messages"][-1].content == "Task created."