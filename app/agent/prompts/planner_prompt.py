"""
Prompt for the planner node (app/agent/nodes/planner.py) — decides whether
to call a tool or respond directly, and which tool/args if so.

TODO: replace AVAILABLE_TOOLS with a dynamic list from app.mcp.registry once
the MCP servers (app/mcp/servers/*.py) exist, so planner always reflects
what's actually callable instead of this hardcoded snapshot.
"""

from app.agent.prompts.system import BASE_SYSTEM_PROMPT

AVAILABLE_TOOLS = [
    {"name": "calendar.list_events", "description": "List upcoming calendar events in a date range"},
    {
        "name": "calendar.create_event",
        "description": "Create a calendar event (side-effecting, requires human approval)",
    },
    {"name": "email.list_inbox", "description": "List recent inbox messages"},
    {"name": "email.send", "description": "Send an email (side-effecting, requires human approval)"},
    {"name": "tasks.list", "description": "List the user's tasks/todos"},
    {"name": "tasks.create", "description": "Create a task/todo item"},
]


def build_planner_prompt() -> str:
    tool_lines = "\n".join(f"- {t['name']}: {t['description']}" for t in AVAILABLE_TOOLS)
    return (
        f"{BASE_SYSTEM_PROMPT}\n\n"
        "You are currently acting as the PLANNER. Given the conversation so "
        "far, decide whether to call one of the available tools or respond "
        "to the user directly.\n\n"
        f"Available tools:\n{tool_lines}\n\n"
        "If the user's request can be answered directly without a tool, set "
        "next_action='respond'. Otherwise set next_action='tool_call' and "
        "specify tool_name (must exactly match one of the names above) and "
        "tool_args (see app.agent.prompts.tool_use_prompt for expected "
        "argument shapes per tool)."
    )