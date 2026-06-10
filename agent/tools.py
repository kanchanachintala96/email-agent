from __future__ import annotations
import json
from functools import lru_cache
from typing import TYPE_CHECKING

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool

from config import settings
from gmail.models import IntentResult

if TYPE_CHECKING:
    from gmail.client import GmailClient

_gmail_client: "GmailClient | None" = None
_email_cache: dict = {}


def init_tools(gmail_client: "GmailClient") -> None:
    global _gmail_client
    _gmail_client = gmail_client


def _get_client() -> "GmailClient":
    if _gmail_client is None:
        raise RuntimeError("Gmail client not initialized. Call init_tools() first.")
    return _gmail_client


@tool
def list_unread_emails(max_results: int = 20) -> str:
    """List unread email IDs from Gmail inbox."""
    client = _get_client()
    messages = client.list_unread(max_results=max_results)
    if not messages:
        return json.dumps({"emails": [], "count": 0})
    return json.dumps({"emails": messages, "count": len(messages)})


@tool
def get_email_content(message_id: str) -> str:
    """Retrieve the full content of an email by its message ID."""
    client = _get_client()
    email = client.get_email(message_id)
    _email_cache[message_id] = email
    return json.dumps({
        "id": email.id,
        "thread_id": email.thread_id,
        "subject": email.subject,
        "sender": email.sender,
        "body": email.body[:3000],
        "snippet": email.snippet,
        "received_at": email.received_at.isoformat(),
    })


@tool
def detect_email_intent(message_id: str, subject: str, body: str) -> str:
    """Classify the intent of an email into APPROVAL_REQUEST, GENERAL_INQUIRY, ACTION_ITEM, or SPAM_PROMOTIONAL."""
    from agent.prompts import INTENT_SYSTEM_PROMPT

    llm = ChatAnthropic(
        model=settings.anthropic_model,
        temperature=0,
        api_key=settings.anthropic_api_key,
    ).with_structured_output(IntentResult)

    result: IntentResult = llm.invoke([
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Subject: {subject}\n\n{body[:2000]}"},
    ])
    return json.dumps({
        "message_id": message_id,
        "intent": result.intent,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "action_items": result.action_items,
        "urgency": result.urgency,
    })


@tool
def draft_reply(message_id: str, intent: str, original_body: str) -> str:
    """Generate a professional reply draft for the given email."""
    from agent.prompts import DRAFT_SYSTEM_PROMPT

    llm = ChatAnthropic(
        model=settings.anthropic_model,
        temperature=0.3,
        api_key=settings.anthropic_api_key,
    )
    reply_text = llm.invoke([
        {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Intent: {intent}\n\nOriginal email:\n{original_body[:2000]}",
        },
    ]).content
    return json.dumps({"message_id": message_id, "draft_text": reply_text})


@tool
def create_gmail_draft(message_id: str, reply_text: str) -> str:
    """Save a reply as a Gmail draft. Does NOT send the email."""
    client = _get_client()
    cached = _email_cache.get(message_id)
    if cached is None:
        cached = client.get_email(message_id)
        _email_cache[message_id] = cached

    sender_email = cached.sender
    if "<" in sender_email:
        sender_email = sender_email.split("<")[1].rstrip(">")

    reply_subject = cached.subject
    if not reply_subject.lower().startswith("re:"):
        reply_subject = f"Re: {reply_subject}"

    draft = client.create_draft(
        to=sender_email,
        subject=reply_subject,
        body=reply_text,
        thread_id=cached.thread_id,
    )
    return json.dumps({
        "draft_id": draft.draft_id,
        "message_id": message_id,
        "to": draft.to,
        "subject": draft.subject,
        "status": "draft_created",
    })


@tool
def label_and_archive(message_id: str, label_name: str) -> str:
    """Apply a label to an email in Gmail."""
    client = _get_client()
    client.apply_label(message_id, label_name)
    return json.dumps({"message_id": message_id, "label": label_name, "status": "labeled"})


ALL_TOOLS = [
    list_unread_emails,
    get_email_content,
    detect_email_intent,
    draft_reply,
    create_gmail_draft,
    label_and_archive,
]
