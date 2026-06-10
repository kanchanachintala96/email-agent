"""Tests for GmailClient — all Gmail API calls are mocked."""
import base64
import email as email_lib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from gmail.client import GmailClient
from gmail.models import Draft, Email


@pytest.fixture
def mock_service():
    return MagicMock()


@pytest.fixture
def client(mock_service, tmp_path):
    creds_file = tmp_path / "credentials.json"
    token_file = tmp_path / "token.json"
    with patch.object(GmailClient, "_authenticate", return_value=mock_service):
        c = GmailClient(
            credentials_file=str(creds_file),
            token_file=str(token_file),
            scopes=["https://www.googleapis.com/auth/gmail.modify"],
        )
    c._service = mock_service
    return c


def _encode_body(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _make_gmail_message(
    msg_id="msg_1",
    thread_id="thread_1",
    subject="Hello",
    from_addr="alice@example.com",
    body_text="This is the body.",
    internal_date="1749542400000",
    label_ids=None,
):
    return {
        "id": msg_id,
        "threadId": thread_id,
        "internalDate": internal_date,
        "snippet": body_text[:50],
        "labelIds": label_ids or ["UNREAD", "INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_addr},
            ],
            "body": {"data": _encode_body(body_text)},
        },
    }


class TestListUnread:
    def test_returns_messages(self, client, mock_service):
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "1"}, {"id": "2"}]
        }
        result = client.list_unread(max_results=5)
        assert len(result) == 2
        assert result[0]["id"] == "1"

    def test_returns_empty_when_none(self, client, mock_service):
        mock_service.users().messages().list().execute.return_value = {}
        result = client.list_unread()
        assert result == []


class TestGetEmail:
    def test_parses_plain_text_email(self, client, mock_service):
        mock_service.users().messages().get().execute.return_value = (
            _make_gmail_message(subject="Project Update", body_text="Please review the doc.")
        )
        email = client.get_email("msg_1")
        assert isinstance(email, Email)
        assert email.subject == "Project Update"
        assert "Please review" in email.body
        assert email.sender == "alice@example.com"
        assert email.is_read is False

    def test_parses_multipart_email(self, client, mock_service):
        body_data = _encode_body("Multipart body here.")
        mock_service.users().messages().get().execute.return_value = {
            "id": "m2", "threadId": "t2", "internalDate": "1749542400000",
            "snippet": "Multipart", "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "Subject", "value": "Multi"},
                    {"name": "From", "value": "b@example.com"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": body_data}},
                    {"mimeType": "text/html", "body": {"data": body_data}},
                ],
            },
        }
        email = client.get_email("m2")
        assert "Multipart body here." in email.body

    def test_is_read_when_no_unread_label(self, client, mock_service):
        mock_service.users().messages().get().execute.return_value = (
            _make_gmail_message(label_ids=["INBOX"])
        )
        email = client.get_email("msg_1")
        assert email.is_read is True

    def test_received_at_parsed_correctly(self, client, mock_service):
        mock_service.users().messages().get().execute.return_value = (
            _make_gmail_message(internal_date="1749542400000")
        )
        email = client.get_email("msg_1")
        assert isinstance(email.received_at, datetime)
        assert email.received_at.tzinfo is not None


class TestCreateDraft:
    def test_creates_draft_and_returns_model(self, client, mock_service):
        mock_service.users().drafts().create().execute.return_value = {
            "id": "draft_xyz",
            "message": {"id": "msg_new"},
        }
        draft = client.create_draft(
            to="bob@example.com",
            subject="Re: Hello",
            body="Thanks for your message.",
            thread_id="thread_1",
        )
        assert isinstance(draft, Draft)
        assert draft.draft_id == "draft_xyz"
        assert draft.to == "bob@example.com"
        assert draft.subject == "Re: Hello"

    def test_raw_payload_is_base64url(self, client, mock_service):
        captured = {}

        def capture_create(userId, body):
            captured["body"] = body
            return MagicMock(execute=lambda: {"id": "d1", "message": {"id": "m1"}})

        mock_service.users().drafts().create = capture_create
        client.create_draft("a@b.com", "Sub", "Body text", "thread_x")
        raw = captured["body"]["message"]["raw"]
        decoded = base64.urlsafe_b64decode(raw + "==").decode()
        assert "Body text" in decoded


class TestApplyLabel:
    def test_creates_label_if_not_exists(self, client, mock_service):
        mock_service.users().labels().list().execute.return_value = {"labels": []}
        mock_service.users().labels().create().execute.return_value = {"id": "Label_99"}
        mock_service.users().messages().modify().execute.return_value = {}
        client.apply_label("msg_1", "my-new-label")
        mock_service.users().labels().create.assert_called()

    def test_reuses_existing_label(self, client, mock_service):
        mock_service.users().labels().list().execute.return_value = {
            "labels": [{"id": "Label_5", "name": "spam-ai"}]
        }
        mock_service.users().messages().modify().execute.return_value = {}
        client.apply_label("msg_1", "spam-ai")
        mock_service.users().labels().create.assert_not_called()


class TestMarkRead:
    def test_removes_unread_label(self, client, mock_service):
        mock_service.users().messages().modify().execute.return_value = {}
        client.mark_read("msg_1")
        mock_service.users().messages().modify.assert_called()


class TestSendDraft:
    def test_calls_drafts_send(self, client, mock_service):
        mock_service.users().drafts().send().execute.return_value = {"id": "sent_msg"}
        result = client.send_draft("draft_1")
        assert result == {"id": "sent_msg"}


class TestDeleteDraft:
    def test_calls_drafts_delete(self, client, mock_service):
        mock_service.users().drafts().delete().execute.return_value = None
        client.delete_draft("draft_1")
        mock_service.users().drafts().delete.assert_called()
