from __future__ import annotations
import base64
import email as email_lib
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from gmail.models import Draft, Email


class GmailClient:
    def __init__(self, credentials_file: str, token_file: str, scopes: list[str]):
        self._credentials_file = Path(credentials_file)
        self._token_file = Path(token_file)
        self._scopes = scopes
        self._service = self._authenticate()

    def _authenticate(self):
        creds: Credentials | None = None
        if self._token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_file), self._scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_file), self._scopes
                )
                creds = flow.run_local_server(port=0)
            self._token_file.write_text(creds.to_json())
        return build("gmail", "v1", credentials=creds)

    def list_unread(self, max_results: int = 20) -> list[dict]:
        result = (
            self._service.users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=max_results)
            .execute()
        )
        return result.get("messages", [])

    def get_email(self, message_id: str) -> Email:
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        body = self._extract_body(msg["payload"])
        received_ms = int(msg.get("internalDate", 0))
        return Email(
            id=msg["id"],
            thread_id=msg["threadId"],
            subject=headers.get("Subject", "(no subject)"),
            sender=headers.get("From", ""),
            body=body,
            snippet=msg.get("snippet", ""),
            received_at=datetime.fromtimestamp(received_ms / 1000, tz=timezone.utc),
            is_read="UNREAD" not in msg.get("labelIds", []),
        )

    def _extract_body(self, payload: dict) -> str:
        mime = payload.get("mimeType", "")
        if mime == "text/plain":
            data = payload.get("body", {}).get("data", "")
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        if mime.startswith("multipart/"):
            for part in payload.get("parts", []):
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            for part in payload.get("parts", []):
                result = self._extract_body(part)
                if result:
                    return result
        return ""

    def create_draft(self, to: str, subject: str, body: str, thread_id: str) -> Draft:
        mime_message = email_lib.message.EmailMessage()
        mime_message["To"] = to
        mime_message["Subject"] = subject
        mime_message.set_content(body)
        raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode()
        draft_body: dict = {"message": {"raw": raw, "threadId": thread_id}}
        draft = (
            self._service.users().drafts().create(userId="me", body=draft_body).execute()
        )
        return Draft(
            draft_id=draft["id"],
            message_id=draft["message"]["id"],
            to=to,
            subject=subject,
            body=body,
        )

    def update_draft(self, draft_id: str, to: str, subject: str, body: str, thread_id: str) -> Draft:
        mime_message = email_lib.message.EmailMessage()
        mime_message["To"] = to
        mime_message["Subject"] = subject
        mime_message.set_content(body)
        raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode()
        draft_body: dict = {"message": {"raw": raw, "threadId": thread_id}}
        draft = (
            self._service.users()
            .drafts()
            .update(userId="me", id=draft_id, body=draft_body)
            .execute()
        )
        return Draft(
            draft_id=draft["id"],
            message_id=draft["message"]["id"],
            to=to,
            subject=subject,
            body=body,
        )

    def send_draft(self, draft_id: str) -> dict:
        return (
            self._service.users()
            .drafts()
            .send(userId="me", body={"id": draft_id})
            .execute()
        )

    def delete_draft(self, draft_id: str) -> None:
        self._service.users().drafts().delete(userId="me", id=draft_id).execute()

    def apply_label(self, message_id: str, label_name: str) -> None:
        label_id = self._get_or_create_label(label_name)
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()

    def mark_read(self, message_id: str) -> None:
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()

    def _get_or_create_label(self, name: str) -> str:
        labels = self._service.users().labels().list(userId="me").execute()
        for label in labels.get("labels", []):
            if label["name"].lower() == name.lower():
                return label["id"]
        new_label = (
            self._service.users()
            .labels()
            .create(userId="me", body={"name": name})
            .execute()
        )
        return new_label["id"]
