from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent.email_agent import EmailIntelligenceAgent
from config import settings
from gmail.client import GmailClient
from gmail.models import ProcessedEmail


# ── Shared state ──────────────────────────────────────────────────────────────
_store: dict[str, ProcessedEmail] = {}
_gmail_client: GmailClient | None = None
_agent: EmailIntelligenceAgent | None = None


@lru_cache(maxsize=1)
def _get_gmail_client() -> GmailClient:
    return GmailClient(
        credentials_file=settings.gmail_credentials_file,
        token_file=settings.gmail_token_file,
        scopes=settings.gmail_scopes,
    )


def _get_agent() -> EmailIntelligenceAgent:
    global _agent
    if _agent is None:
        _agent = EmailIntelligenceAgent(_get_gmail_client())
    return _agent


# ── App ───────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _get_gmail_client()  # warm-up OAuth on startup
    yield


app = FastAPI(title="Email Intelligence Agent API", lifespan=lifespan)


# ── Request/Response schemas ──────────────────────────────────────────────────
class UpdateDraftRequest(BaseModel):
    body: str


class ProcessResponse(BaseModel):
    processed: int
    email_ids: list[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/emails", response_model=list[dict])
def list_emails(intent: str | None = None, status: str | None = None) -> list[dict]:
    results = list(_store.values())
    if intent:
        results = [e for e in results if e.intent.intent == intent.upper()]
    if status:
        results = [e for e in results if e.status == status]
    return [e.model_dump(mode="json") for e in results]


@app.get("/emails/{email_id}", response_model=dict)
def get_email(email_id: str) -> dict:
    pe = _store.get(email_id)
    if not pe:
        raise HTTPException(status_code=404, detail="Email not found")
    return pe.model_dump(mode="json")


@app.post("/emails/process", response_model=ProcessResponse)
def process_all() -> ProcessResponse:
    agent = _get_agent()
    processed = agent.process_all_unread(max_results=settings.max_unread_fetch)
    ids: list[str] = []
    for pe in processed:
        _store[pe.email.id] = pe
        ids.append(pe.email.id)
    return ProcessResponse(processed=len(ids), email_ids=ids)


@app.post("/emails/{email_id}/process", response_model=dict)
def process_one(email_id: str) -> dict:
    agent = _get_agent()
    pe = agent.process_email(email_id)
    _store[email_id] = pe
    return pe.model_dump(mode="json")


@app.put("/emails/{email_id}/draft", response_model=dict)
def update_draft(email_id: str, req: UpdateDraftRequest) -> dict:
    pe = _store.get(email_id)
    if not pe:
        raise HTTPException(status_code=404, detail="Email not found")
    if not pe.draft:
        raise HTTPException(status_code=400, detail="No draft exists for this email")

    gmail = _get_gmail_client()
    updated = gmail.update_draft(
        draft_id=pe.draft.draft_id,
        to=pe.draft.to,
        subject=pe.draft.subject,
        body=req.body,
        thread_id=pe.email.thread_id,
    )
    pe.draft = updated
    _store[email_id] = pe
    return pe.model_dump(mode="json")


@app.post("/emails/{email_id}/send", response_model=dict)
def send_draft(email_id: str) -> dict:
    pe = _store.get(email_id)
    if not pe:
        raise HTTPException(status_code=404, detail="Email not found")
    if not pe.draft:
        raise HTTPException(status_code=400, detail="No draft to send")
    if pe.status == "sent":
        raise HTTPException(status_code=409, detail="Already sent")

    gmail = _get_gmail_client()
    gmail.send_draft(pe.draft.draft_id)
    pe.status = "sent"
    _store[email_id] = pe
    return {"email_id": email_id, "status": "sent"}


@app.post("/emails/{email_id}/reject", response_model=dict)
def reject_email(email_id: str) -> dict:
    pe = _store.get(email_id)
    if not pe:
        raise HTTPException(status_code=404, detail="Email not found")

    if pe.draft:
        try:
            _get_gmail_client().delete_draft(pe.draft.draft_id)
        except Exception:
            pass
        pe.draft = None

    pe.status = "rejected"
    _store[email_id] = pe
    return {"email_id": email_id, "status": "rejected"}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "store_size": len(_store)}
