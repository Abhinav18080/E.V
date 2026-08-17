"""
Trip planner workflow — a multi-step, stateful flow that researches a
destination, drafts a day-by-day itinerary, and (optionally) turns itinerary
days into calendar-event requests.

Research and drafting are done directly here since neither has side effects
and doesn't need approval. Turning a day into a real calendar event is
delegated back to the agent graph (app/agent/graph.py's start_turn) rather
than calling app.mcp.client directly, so it goes through the same
planner -> executor -> approval_gate path as any other agent action — one
approval flow for the whole app, not a separate one for workflows.
"""

from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.agent.graph import start_turn
from app.integrations.llm.model_config import PLANNER_CONFIG
from app.integrations.llm.provider import get_chat_model
from app.mcp.client import call as call_mcp_tool


class ItineraryActivity(BaseModel):
    time: str = Field(description="Rough time of day, e.g. 'Morning', '2:00 PM'")
    title: str
    notes: str | None = None


class ItineraryDay(BaseModel):
    date: str = Field(description="ISO 8601 date for this day")
    theme: str = Field(description="Short label for the day, e.g. 'Temple hopping in Higashiyama'")
    activities: list[ItineraryActivity]


class TripItinerary(BaseModel):
    destination: str
    days: list[ItineraryDay]


RESEARCH_QUERY_TEMPLATES = [
    "best time of year to visit {destination}",
    "top things to do in {destination}",
]

ITINERARY_PROMPT = (
    "You are planning a {num_days}-day trip to {destination}, starting {start_date}. "
    "User preferences: {preferences}\n\n"
    "Research notes:\n{research}\n\n"
    "Produce a day-by-day itinerary. Keep each day realistic (2-4 activities, "
    "accounting for travel time) and grounded in the research notes above "
    "rather than a generic tourist list."
)


def _unwrap(result: Any) -> list | None:
    """MCP list-returning tools sometimes come back as {"result": [...]}; normalize."""
    if isinstance(result, dict) and "result" in result:
        return result["result"]
    return result


async def _research(destination: str) -> str:
    """Gather background info via the free web_search MCP tool. Best-effort — a
    down search server, or one it can't reach, degrades to an empty research
    block rather than failing the whole workflow."""
    notes: list[str] = []
    for template in RESEARCH_QUERY_TEMPLATES:
        query = template.format(destination=destination)
        try:
            raw_results = await call_mcp_tool("web_search.search", {"query": query, "max_results": 3})
        except Exception:
            continue
        for item in _unwrap(raw_results) or []:
            notes.append(f"- {item.get('title')}: {item.get('snippet')}")
    return "\n".join(notes) if notes else "(no research results available)"


async def draft_itinerary(
    destination: str,
    start_date: str,
    num_days: int,
    preferences: str = "",
) -> TripItinerary:
    """
    Research the destination and draft a day-by-day itinerary. Read-only —
    no calendar events are created here; call request_calendar_events()
    separately once the user is happy with the draft.
    """
    research = await _research(destination)

    model = get_chat_model(PLANNER_CONFIG).with_structured_output(TripItinerary)
    prompt = ITINERARY_PROMPT.format(
        num_days=num_days,
        destination=destination,
        start_date=start_date,
        preferences=preferences or "none specified",
        research=research,
    )
    return await model.ainvoke([HumanMessage(content=prompt)])


async def request_calendar_events(user_id: str, itinerary: TripItinerary) -> list[dict[str, Any]]:
    """
    Turn each itinerary day into a calendar-event request via the agent
    graph, so each goes through the normal human-approval flow rather than
    writing directly. Each result includes the thread_id the request ran
    on (needed to resume it via app.agent.graph.resume_with_decision once
    approved) plus the graph's state after this turn — which will contain
    an interrupt if approval is pending.
    """
    import uuid

    results = []
    for day in itinerary.days:
        thread_id = f"trip-planner-{uuid.uuid4()}"
        activity_summary = ", ".join(a.title for a in day.activities) or day.theme
        message = f"Create a calendar event on {day.date} titled '{day.theme}' covering: {activity_summary}"

        state = await start_turn(
            user_id=user_id,
            thread_id=thread_id,
            state_update={"messages": [HumanMessage(content=message)]},
        )
        results.append({"date": day.date, "thread_id": thread_id, "state": state})

    return results