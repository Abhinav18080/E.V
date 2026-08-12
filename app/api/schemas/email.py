"""Pydantic models for app/api/routes/email.py."""

from pydantic import BaseModel, EmailStr, Field


class EmailSummary(BaseModel):
    id: str
    subject: str
    sender: str
    snippet: str
    received_at: str
    unread: bool = True


class SendEmailRequest(BaseModel):
    to: list[EmailStr]
    subject: str
    body: str
    cc: list[EmailStr] = Field(default_factory=list)


class SendEmailResponse(BaseModel):
    message_id: str
    status: str