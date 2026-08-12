"""
Email-specific endpoints — direct REST access to Gmail, separate from the
conversational /chat path.

Backed by app.integrations.google.gmail_client (not built yet). Sending is
always side-effecting, so once approvals exist, POST /send should route
through app.agent.nodes.approval_gate rather than sending directly.
"""

from fastapi import APIRouter, HTTPException, status

from app.api.schemas.email import EmailSummary, SendEmailRequest, SendEmailResponse
from app.dependencies import CurrentUserDep

router = APIRouter()


@router.get("/inbox", response_model=list[EmailSummary])
async def list_inbox(user_id: CurrentUserDep, max_results: int = 20) -> list[EmailSummary]:
    # TODO: wire to app.integrations.google.gmail_client.list_messages(user_id, max_results)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Gmail integration not wired up yet",
    )


@router.post("/send", response_model=SendEmailResponse)
async def send_email(request: SendEmailRequest, user_id: CurrentUserDep) -> SendEmailResponse:
    # NOTE: this is the canonical side-effecting action — once the approval
    # flow exists, this endpoint should create a pending approval instead of
    # sending immediately. See app/api/routes/approvals.py.
    # TODO: wire to app.integrations.google.gmail_client.send_message(...)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Gmail integration not wired up yet",
    )