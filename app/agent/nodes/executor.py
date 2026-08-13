"""
Executor node — runs the tool call chosen by the planner, dispatched via MCP.

Side-effecting tools (currently: calendar.create_event, email.send) require
human approval before they actually run. The first time this node sees such
a tool call, it returns a `pending_approval` instead of executing — that
routes the graph to approval_gate (see route_after_executor in
app/agent/graph.py) rather than running the action immediately. Once a human
approves and the graph resumes, this node runs again with
state["approval_decision"] set, and either executes the tool or records the
rejection.
"""

from typing import Any

from app.agent.state import AgentState, PendingApproval, ToolResult
from app.mcp.client import MCPToolError, call as call_mcp_tool

SIDE_EFFECTING_TOOLS = {"calendar.create_event", "email.send"}


def _summarize_action(tool_name: str, tool_args: dict[str, Any]) -> str:
    if tool_name == "email.send":
        return f"Send an email to {tool_args.get('to')} — subject: '{tool_args.get('subject')}'"
    if tool_name == "calendar.create_event":
        return f"Create calendar event '{tool_args.get('summary')}' at {tool_args.get('start')}"
    return f"Run {tool_name} with {tool_args}"


async def executor(state: AgentState) -> dict:
    tool_call = state.get("tool_call")
    if not tool_call:
        # Planner routed here without a tool selected — nothing to do.
        return {}

    tool_name = tool_call["name"]
    tool_args = {**tool_call["args"], "user_id": state["user_id"]}

    needs_approval = tool_name in SIDE_EFFECTING_TOOLS
    decision = state.get("approval_decision")

    # First pass: side-effecting tool, no decision recorded yet -> pause for approval.
    if needs_approval and decision is None:
        pending: PendingApproval = {
            "id": "",  # filled in by create_pending_approval when it's persisted
            "action_type": tool_name,
            "summary": _summarize_action(tool_name, tool_args),
            "payload": tool_args,
        }
        return {"pending_approval": pending}

    # Resumed after a human rejected the action — don't run it.
    if needs_approval and decision == "rejected":
        result: ToolResult = {"status": "rejected", "tool_name": tool_name, "result": None}
        return {"pending_approval": None, "approval_decision": None, "tool_result": result}

    # Either approved, or the tool never needed approval in the first place.
    try:
        raw_result = await call_mcp_tool(tool_name, tool_args)
        result: ToolResult = {"status": "ok", "tool_name": tool_name, "result": raw_result}
    except MCPToolError as exc:
        result: ToolResult = {"status": "error", "tool_name": tool_name, "result": str(exc)}

    return {"pending_approval": None, "approval_decision": None, "tool_result": result}