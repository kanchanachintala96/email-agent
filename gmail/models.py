from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class Email(BaseModel):
    id: str
    thread_id: str
    subject: str
    sender: str
    body: str
    snippet: str
    received_at: datetime
    is_read: bool


class Draft(BaseModel):
    draft_id: str
    message_id: str
    to: str
    subject: str
    body: str


class IntentResult(BaseModel):
    intent: Literal[
        "APPROVAL_REQUEST",
        "GENERAL_INQUIRY",
        "ACTION_ITEM",
        "SPAM_PROMOTIONAL",
    ]
    confidence: float
    reasoning: str
    action_items: list[str] = []
    urgency: Literal["high", "medium", "low"] = "medium"


class ProcessedEmail(BaseModel):
    email: Email
    intent: IntentResult
    draft: Draft | None = None
    status: Literal["pending", "draft_created", "sent", "rejected"] = "pending"
    processed_at: datetime | None = None
