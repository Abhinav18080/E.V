"""
Calendar-specific endpoints — direct REST access to calendar data, separate
from the conversational /chat path. Useful for a future frontend that wants
to render a calendar view without going through the agent.

Backed by app.integrations.google.calendar_client (not built yet) or, once
the MCP calendar server exists, called via app.mcp.client instead of directly
hitting the Google client here. Left as 501s until that integration lands.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from app.api.schemas.calendar import CalendarEvent, CreateEventRequest
from app.dependencies import CurrentUserDep

router = APIRouter()


@router.get("/events", response_model=list[CalendarEvent])
async def list_events(
    user_id: CurrentUserDep,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[CalendarEvent]:
    # TODO: wire to app.integrations.google.calendar_client.list_events(user_id, start, end)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google Calendar integration not wired up yet",
    )


@router.post("/events", response_model=CalendarEvent, status_code=status.HTTP_201_CREATED)
async def create_event(request: CreateEventRequest, user_id: CurrentUserDep) -> CalendarEvent:
    # NOTE: creating an event is side-effecting — once the approval flow exists,
    # this should go through app.agent.nodes.approval_gate rather than writing
    # directly, so the user confirms before anything hits their real calendar.
    # TODO: wire to app.integrations.google.calendar_client.create_event(...)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google Calendar integration not wired up yet",
    )


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: str, user_id: CurrentUserDep) -> None:
    # TODO: same approval-gate note as create_event above.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google Calendar integration not wired up yet",
    )