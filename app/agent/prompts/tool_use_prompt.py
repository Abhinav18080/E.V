"""
Tool-use prompt helpers.

Two things live here:
  1. TOOL_ARG_SCHEMAS / describe_tool_args — a human-readable description of
     each tool's expected arguments, so planner's structured-output call has
     a concrete shape to aim for. Keep this in sync with
     app.agent.prompts.planner_prompt.AVAILABLE_TOOLS and, eventually, with
     the real MCP tool schemas once app/mcp/servers/*.py exist (at that
     point this can likely be generated from the MCP tool definitions rather
     than hand-maintained).
  2. RESPONDER_TOOL_RESULT_PROMPT — instructions for how responder.py should
     phrase a reply once a tool has actually run.
"""

TOOL_ARG_SCHEMAS: dict[str, dict[str, str]] = {
    "calendar.list_events": {
        "start": "ISO 8601 datetime",
        "end": "ISO 8601 datetime",
    },
    "calendar.create_event": {
        "summary": "string",
        "start": "ISO 8601 datetime",
        "end": "ISO 8601 datetime",
        "description": "string, optional",
        "attendees": "list of email strings, optional",
    },
    "email.list_inbox": {
        "max_results": "integer, optional, default 20",
    },
    "email.send": {
        "to": "list of email strings",
        "subject": "string",
        "body": "string",
        "cc": "list of email strings, optional",
    },
    "tasks.list": {},
    "tasks.create": {
        "title": "string",
        "description": "string, optional",
        "due_date": "ISO 8601 datetime, optional",
    },
}


def describe_tool_args(tool_name: str) -> str:
    """Human-readable argument description for a tool, for prompt injection."""
    if tool_name not in TOOL_ARG_SCHEMAS:
        return "(no argument schema registered for this tool)"
    schema = TOOL_ARG_SCHEMAS[tool_name]
    if not schema:
        return "(this tool takes no arguments)"
    return "\n".join(f"- {name}: {shape}" for name, shape in schema.items())


RESPONDER_TOOL_RESULT_PROMPT = (
    "Summarize the following tool result for the user in one or two natural "
    "sentences. Do not repeat raw JSON or field names verbatim — describe "
    "what happened in plain language. If status is 'rejected', acknowledge "
    "that the user chose not to approve the action and don't retry it. If "
    "status is 'error', apologize briefly and suggest what might help."
)