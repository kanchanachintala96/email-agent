"""Tests for Pydantic models."""
from datetime import datetime, timezone
import pytest
from gmail.models import Draft, Email, IntentResult, ProcessedEmail


def make_email(**kwargs) -> Email:
    defaults = dict(
        id="msg_001",
        thread_id="thread_001",
        subject="Test Subject",
        sender="sender@example.com",
        body="Hello, this is a test email.",
        snippet="Hello, this is...",
        received_at=datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc),
        is_read=False,
    )
    return Email(**(defaults | kwargs))


def make_intent(**kwargs) -> IntentResult:
    defaults = dict(
        intent="GENERAL_INQUIRY",
        confidence=0.95,
        reasoning="Looks like a question.",
        action_items=[],
        urgency="medium",
    )
    return IntentResult(**(defaults | kwargs))


# ── Email model ───────────────────────────────────────────────────────────────
class TestEmail:
    def test_valid_email(self):
        e = make_email()
        assert e.id == "msg_001"
        assert e.sender == "sender@example.com"
        assert e.is_read is False

    def test_email_serializes_to_dict(self):
        e = make_email()
        d = e.model_dump()
        assert isinstance(d["received_at"], datetime)

    def test_email_json_round_trip(self):
        e = make_email()
        json_str = e.model_dump_json()
        e2 = Email.model_validate_json(json_str)
        assert e2.id == e.id
        assert e2.subject == e.subject


# ── IntentResult model ────────────────────────────────────────────────────────
class TestIntentResult:
    @pytest.mark.parametrize("intent", [
        "APPROVAL_REQUEST", "GENERAL_INQUIRY", "ACTION_ITEM", "SPAM_PROMOTIONAL"
    ])
    def test_valid_intents(self, intent):
        ir = make_intent(intent=intent)
        assert ir.intent == intent

    def test_invalid_intent_raises(self):
        with pytest.raises(Exception):
            IntentResult(
                intent="UNKNOWN_TYPE",
                confidence=0.5,
                reasoning="test",
                urgency="low",
            )

    @pytest.mark.parametrize("urgency", ["high", "medium", "low"])
    def test_valid_urgency(self, urgency):
        ir = make_intent(urgency=urgency)
        assert ir.urgency == urgency

    def test_invalid_urgency_raises(self):
        with pytest.raises(Exception):
            IntentResult(
                intent="GENERAL_INQUIRY",
                confidence=0.5,
                reasoning="test",
                urgency="critical",
            )

    def test_confidence_stored(self):
        ir = make_intent(confidence=0.73)
        assert abs(ir.confidence - 0.73) < 0.001

    def test_action_items_default_empty(self):
        ir = IntentResult(
            intent="GENERAL_INQUIRY",
            confidence=0.9,
            reasoning="test",
            urgency="low",
        )
        assert ir.action_items == []

    def test_action_items_populated(self):
        ir = make_intent(intent="ACTION_ITEM", action_items=["Do X", "Review Y"])
        assert len(ir.action_items) == 2


# ── Draft model ───────────────────────────────────────────────────────────────
class TestDraft:
    def test_draft_fields(self):
        d = Draft(
            draft_id="draft_abc",
            message_id="msg_001",
            to="recipient@example.com",
            subject="Re: Test",
            body="Thanks for reaching out.",
        )
        assert d.draft_id == "draft_abc"
        assert d.subject == "Re: Test"


# ── ProcessedEmail model ──────────────────────────────────────────────────────
class TestProcessedEmail:
    def test_defaults(self):
        pe = ProcessedEmail(email=make_email(), intent=make_intent())
        assert pe.status == "pending"
        assert pe.draft is None
        assert pe.processed_at is None

    @pytest.mark.parametrize("status", ["pending", "draft_created", "sent", "rejected"])
    def test_valid_statuses(self, status):
        pe = ProcessedEmail(email=make_email(), intent=make_intent(), status=status)
        assert pe.status == status

    def test_invalid_status_raises(self):
        with pytest.raises(Exception):
            ProcessedEmail(email=make_email(), intent=make_intent(), status="archived")

    def test_with_draft(self):
        draft = Draft(
            draft_id="d1", message_id="m1",
            to="a@b.com", subject="Re: X", body="Reply text"
        )
        pe = ProcessedEmail(
            email=make_email(), intent=make_intent(),
            draft=draft, status="draft_created"
        )
        assert pe.draft is not None
        assert pe.draft.draft_id == "d1"

    def test_json_mode_serialization(self):
        pe = ProcessedEmail(email=make_email(), intent=make_intent())
        d = pe.model_dump(mode="json")
        assert isinstance(d["email"]["received_at"], str)
