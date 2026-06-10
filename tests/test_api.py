"""Tests for the FastAPI endpoints — Gmail and agent are fully mocked."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, patch as mock_patch

import pytest
from fastapi.testclient import TestClient

import api.main as api_main  # must import before patch() resolves the string
from api.main import app
from gmail.models import Draft, Email, IntentResult, ProcessedEmail


# ── Fixtures ──────────────────────────────────────────────────────────────────
def _make_email(msg_id="e1") -> Email:
    return Email(
        id=msg_id,
        thread_id="t1",
        subject="Test Subject",
        sender="alice@example.com",
        body="Hello there.",
        snippet="Hello there.",
        received_at=datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc),
        is_read=False,
    )


def _make_intent(intent="GENERAL_INQUIRY") -> IntentResult:
    return IntentResult(
        intent=intent,
        confidence=0.92,
        reasoning="Looks like an inquiry.",
        action_items=[],
        urgency="medium",
    )


def _make_draft(draft_id="d1", message_id="e1") -> Draft:
    return Draft(
        draft_id=draft_id,
        message_id=message_id,
        to="alice@example.com",
        subject="Re: Test Subject",
        body="Thank you for reaching out.",
    )


def _make_pe(msg_id="e1", intent_str="GENERAL_INQUIRY", with_draft=True) -> ProcessedEmail:
    return ProcessedEmail(
        email=_make_email(msg_id),
        intent=_make_intent(intent_str),
        draft=_make_draft(message_id=msg_id) if with_draft else None,
        status="draft_created" if with_draft else "pending",
        processed_at=datetime(2026, 6, 10, 9, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def client():
    mock_gmail = MagicMock()
    mock_agent = MagicMock()

    # Clear lru_cache so the mock replaces it cleanly
    api_main._get_gmail_client.cache_clear()

    with (
        patch.object(api_main, "_get_gmail_client", return_value=mock_gmail),
        patch.object(api_main, "_get_agent", return_value=mock_agent),
    ):
        api_main._store.clear()
        api_main._agent = None
        with TestClient(app, raise_server_exceptions=True) as c:
            c._mock_gmail = mock_gmail
            c._mock_agent = mock_agent
            c._store = api_main._store
            yield c
        api_main._store.clear()
        api_main._get_gmail_client.cache_clear()


# ── GET /emails ───────────────────────────────────────────────────────────────
class TestListEmails:
    def test_empty_store_returns_empty_list(self, client):
        r = client.get("/emails")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_stored_emails(self, client):
        client._store["e1"] = _make_pe("e1")
        client._store["e2"] = _make_pe("e2")
        r = client.get("/emails")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_filters_by_intent(self, client):
        client._store["e1"] = _make_pe("e1", intent_str="APPROVAL_REQUEST")
        client._store["e2"] = _make_pe("e2", intent_str="GENERAL_INQUIRY")
        r = client.get("/emails?intent=APPROVAL_REQUEST")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["intent"]["intent"] == "APPROVAL_REQUEST"

    def test_filters_by_status(self, client):
        client._store["e1"] = _make_pe("e1", with_draft=True)
        client._store["e2"] = _make_pe("e2", with_draft=False)
        r = client.get("/emails?status=draft_created")
        assert r.status_code == 200
        assert all(e["status"] == "draft_created" for e in r.json())


# ── GET /emails/{id} ──────────────────────────────────────────────────────────
class TestGetEmail:
    def test_returns_email_by_id(self, client):
        client._store["e1"] = _make_pe("e1")
        r = client.get("/emails/e1")
        assert r.status_code == 200
        assert r.json()["email"]["id"] == "e1"

    def test_returns_404_for_unknown_id(self, client):
        r = client.get("/emails/nonexistent")
        assert r.status_code == 404


# ── POST /emails/process ──────────────────────────────────────────────────────
class TestProcessAll:
    def test_processes_and_stores_emails(self, client):
        pe1 = _make_pe("e1")
        pe2 = _make_pe("e2")
        client._mock_agent.process_all_unread.return_value = [pe1, pe2]
        r = client.post("/emails/process")
        assert r.status_code == 200
        body = r.json()
        assert body["processed"] == 2
        assert set(body["email_ids"]) == {"e1", "e2"}
        assert "e1" in client._store
        assert "e2" in client._store


# ── POST /emails/{id}/process ─────────────────────────────────────────────────
class TestProcessOne:
    def test_processes_single_email(self, client):
        pe = _make_pe("e1")
        client._mock_agent.process_email.return_value = pe
        r = client.post("/emails/e1/process")
        assert r.status_code == 200
        assert r.json()["email"]["id"] == "e1"


# ── PUT /emails/{id}/draft ────────────────────────────────────────────────────
class TestUpdateDraft:
    def test_updates_draft_body(self, client):
        client._store["e1"] = _make_pe("e1", with_draft=True)
        updated_draft = _make_draft(draft_id="d1", message_id="e1")
        updated_draft.body = "Updated reply text."
        client._mock_gmail.update_draft.return_value = updated_draft

        r = client.put("/emails/e1/draft", json={"body": "Updated reply text."})
        assert r.status_code == 200

    def test_returns_404_for_missing_email(self, client):
        r = client.put("/emails/nope/draft", json={"body": "text"})
        assert r.status_code == 404

    def test_returns_400_when_no_draft(self, client):
        client._store["e1"] = _make_pe("e1", with_draft=False)
        r = client.put("/emails/e1/draft", json={"body": "text"})
        assert r.status_code == 400


# ── POST /emails/{id}/send ────────────────────────────────────────────────────
class TestSendDraft:
    def test_sends_draft_and_updates_status(self, client):
        client._store["e1"] = _make_pe("e1", with_draft=True)
        client._mock_gmail.send_draft.return_value = {"id": "sent_msg"}
        r = client.post("/emails/e1/send")
        assert r.status_code == 200
        assert r.json()["status"] == "sent"
        assert client._store["e1"].status == "sent"

    def test_returns_404_for_missing_email(self, client):
        r = client.post("/emails/nope/send")
        assert r.status_code == 404

    def test_returns_400_when_no_draft(self, client):
        client._store["e1"] = _make_pe("e1", with_draft=False)
        r = client.post("/emails/e1/send")
        assert r.status_code == 400

    def test_returns_409_when_already_sent(self, client):
        pe = _make_pe("e1", with_draft=True)
        pe.status = "sent"
        client._store["e1"] = pe
        r = client.post("/emails/e1/send")
        assert r.status_code == 409


# ── POST /emails/{id}/reject ──────────────────────────────────────────────────
class TestRejectEmail:
    def test_rejects_and_deletes_draft(self, client):
        client._store["e1"] = _make_pe("e1", with_draft=True)
        client._mock_gmail.delete_draft.return_value = None
        r = client.post("/emails/e1/reject")
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"
        assert client._store["e1"].draft is None

    def test_returns_404_for_missing_email(self, client):
        r = client.post("/emails/nope/reject")
        assert r.status_code == 404

    def test_reject_without_draft_still_marks_rejected(self, client):
        client._store["e1"] = _make_pe("e1", with_draft=False)
        r = client.post("/emails/e1/reject")
        assert r.status_code == 200
        assert client._store["e1"].status == "rejected"


# ── GET /health ───────────────────────────────────────────────────────────────
class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_includes_store_size(self, client):
        client._store["e1"] = _make_pe("e1")
        r = client.get("/health")
        assert r.json()["store_size"] == 1
