"""Pydantic models for app/api/routes/calendar.py."""

from datetime import datetime

from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    id: str | None = None
    summary: str
    start: datetime
    end: datetime
    description: str | None = None
    attendees: list[str] = Field(default_factory=list)


class CreateEventRequest(BaseModel):
    summary: str
    start: datetime
    end: datetime
    description: str | None = None
    attendees: list[str] = Field(default_factory=list)