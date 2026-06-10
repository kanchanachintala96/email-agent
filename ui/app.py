from __future__ import annotations
import httpx
import streamlit as st

API = "http://localhost:8000"

INTENT_COLORS = {
    "APPROVAL_REQUEST": "#e74c3c",
    "GENERAL_INQUIRY": "#3498db",
    "ACTION_ITEM": "#f39c12",
    "SPAM_PROMOTIONAL": "#95a5a6",
}
URGENCY_ICONS = {"high": "🔴", "medium": "🟡", "low": "🟢"}


# ── Helpers ───────────────────────────────────────────────────────────────────
def api_get(path: str) -> dict | list | None:
    try:
        r = httpx.get(f"{API}{path}", timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def api_post(path: str, json: dict | None = None) -> dict | None:
    try:
        r = httpx.post(f"{API}{path}", json=json, timeout=120)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def api_put(path: str, json: dict) -> dict | None:
    try:
        r = httpx.put(f"{API}{path}", json=json, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def intent_badge(intent: str) -> str:
    color = INTENT_COLORS.get(intent, "#7f8c8d")
    label = intent.replace("_", " ").title()
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:12px">{label}</span>'


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Email Intelligence Dashboard",
    page_icon="📧",
    layout="wide",
)

st.markdown(
    """
    <style>
    .email-card {
        border: 1px solid #ddd; border-radius: 6px; padding: 10px 14px;
        margin-bottom: 8px; cursor: pointer; background: #fafafa;
    }
    .email-card.selected { border-color: #3498db; background: #eaf4fd; }
    .email-card:hover { background: #f0f0f0; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📧 Email Intelligence Dashboard")
st.caption("AI-powered inbox — reads, classifies, and drafts replies. You control what gets sent.")

# ── Session state ─────────────────────────────────────────────────────────────
if "selected_id" not in st.session_state:
    st.session_state.selected_id = None
if "emails" not in st.session_state:
    st.session_state.emails = []
if "edited_draft" not in st.session_state:
    st.session_state.edited_draft = {}

# ── Top toolbar ───────────────────────────────────────────────────────────────
col_btn, col_filter, col_stats = st.columns([2, 3, 3])

with col_btn:
    if st.button("Fetch & Process Emails", type="primary", use_container_width=True):
        with st.spinner("Running agent on unread emails…"):
            result = api_post("/emails/process")
            if result:
                st.success(f"Processed {result['processed']} email(s).")
                emails_raw = api_get("/emails") or []
                st.session_state.emails = emails_raw

with col_filter:
    intent_filter = st.selectbox(
        "Filter by intent",
        ["All", "APPROVAL_REQUEST", "GENERAL_INQUIRY", "ACTION_ITEM", "SPAM_PROMOTIONAL"],
        label_visibility="collapsed",
    )

with col_stats:
    if st.session_state.emails:
        total = len(st.session_state.emails)
        pending = sum(1 for e in st.session_state.emails if e["status"] in ("pending", "draft_created"))
        st.metric("Emails", total, delta=f"{pending} need review")

st.divider()

# ── Refresh emails if store is empty ─────────────────────────────────────────
if not st.session_state.emails:
    raw = api_get("/emails")
    if raw:
        st.session_state.emails = raw

# ── Filter ────────────────────────────────────────────────────────────────────
emails = st.session_state.emails
if intent_filter != "All":
    emails = [e for e in emails if e["intent"]["intent"] == intent_filter]

# ── Two-column layout ─────────────────────────────────────────────────────────
left, right = st.columns([1, 2], gap="large")

# ── Left: email list ──────────────────────────────────────────────────────────
with left:
    st.subheader(f"Inbox ({len(emails)})")
    if not emails:
        st.info("No emails to display. Click 'Fetch & Process Emails'.")
    for email_data in emails:
        eid = email_data["email"]["id"]
        intent = email_data["intent"]["intent"]
        urgency = email_data["intent"].get("urgency", "medium")
        subject = email_data["email"]["subject"] or "(no subject)"
        sender = email_data["email"]["sender"]
        status = email_data["status"]

        is_selected = eid == st.session_state.selected_id
        card_class = "email-card selected" if is_selected else "email-card"

        status_icon = {"sent": "✅", "rejected": "❌", "draft_created": "📝", "pending": "⏳"}.get(status, "")
        urgency_icon = URGENCY_ICONS.get(urgency, "")

        st.markdown(
            f'<div class="{card_class}">'
            f"{urgency_icon} {status_icon} <b>{subject[:40]}</b><br>"
            f'<small style="color:#555">{sender[:35]}</small><br>'
            + intent_badge(intent)
            + "</div>",
            unsafe_allow_html=True,
        )
        if st.button("Select", key=f"sel_{eid}", use_container_width=True):
            st.session_state.selected_id = eid
            st.rerun()

# ── Right: email detail + draft panel ─────────────────────────────────────────
with right:
    selected_id = st.session_state.selected_id
    selected = next((e for e in st.session_state.emails if e["email"]["id"] == selected_id), None)

    if not selected:
        st.info("Select an email from the list to review it.")
    else:
        email = selected["email"]
        intent_data = selected["intent"]
        draft_data = selected.get("draft")
        status = selected["status"]

        # Intent summary row
        intent_str = intent_data["intent"]
        urgency = intent_data.get("urgency", "medium")
        confidence = intent_data.get("confidence", 0.0)
        color = INTENT_COLORS.get(intent_str, "#7f8c8d")

        st.markdown(
            f'<h3 style="margin-bottom:4px">{email["subject"] or "(no subject)"}</h3>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"**From:** {email['sender']} &nbsp;|&nbsp; "
            + intent_badge(intent_str)
            + f" &nbsp; {URGENCY_ICONS.get(urgency, '')} {urgency.capitalize()} urgency",
            unsafe_allow_html=True,
        )

        conf_pct = int(confidence * 100)
        st.markdown(
            f'<div style="background:#eee;border-radius:4px;height:6px;margin:6px 0">'
            f'<div style="background:{color};width:{conf_pct}%;height:6px;border-radius:4px"></div></div>'
            f'<small style="color:#666">Confidence: {conf_pct}% — {intent_data.get("reasoning","")}</small>',
            unsafe_allow_html=True,
        )

        # Action items
        action_items = intent_data.get("action_items", [])
        if action_items:
            st.markdown("**Action items detected:**")
            for item in action_items:
                st.markdown(f"- {item}")

        # Original email
        with st.expander("Original email", expanded=False):
            st.text(email.get("body", email.get("snippet", "")))

        st.divider()

        # Draft panel
        if status == "sent":
            st.success("Reply sent successfully.")
        elif status == "rejected":
            st.warning("Email rejected — draft deleted.")
        elif intent_str == "SPAM_PROMOTIONAL":
            st.info("Spam/promotional email — no draft created. Labeled in Gmail.")
        else:
            st.subheader("Draft Reply")
            current_body = st.session_state.edited_draft.get(
                selected_id,
                draft_data["body"] if draft_data else "",
            )
            new_body = st.text_area(
                "Edit draft before sending:",
                value=current_body,
                height=200,
                key=f"draft_{selected_id}",
            )
            st.session_state.edited_draft[selected_id] = new_body

            if not draft_data:
                st.warning("No draft available — email may still be processing.")
            else:
                c1, c2, c3 = st.columns(3)

                with c1:
                    if st.button("Save Draft", use_container_width=True, type="secondary"):
                        updated = api_put(f"/emails/{selected_id}/draft", {"body": new_body})
                        if updated:
                            idx = next(
                                (i for i, e in enumerate(st.session_state.emails) if e["email"]["id"] == selected_id),
                                None,
                            )
                            if idx is not None:
                                st.session_state.emails[idx] = updated
                            st.success("Draft saved.")
                            st.rerun()

                with c2:
                    if st.button("Send Draft", use_container_width=True, type="primary"):
                        # Save edits first if body changed
                        if new_body != draft_data["body"]:
                            api_put(f"/emails/{selected_id}/draft", {"body": new_body})
                        result = api_post(f"/emails/{selected_id}/send")
                        if result and result.get("status") == "sent":
                            idx = next(
                                (i for i, e in enumerate(st.session_state.emails) if e["email"]["id"] == selected_id),
                                None,
                            )
                            if idx is not None:
                                st.session_state.emails[idx]["status"] = "sent"
                            st.success("Email sent!")
                            st.rerun()

                with c3:
                    if st.button("Reject", use_container_width=True):
                        result = api_post(f"/emails/{selected_id}/reject")
                        if result and result.get("status") == "rejected":
                            idx = next(
                                (i for i, e in enumerate(st.session_state.emails) if e["email"]["id"] == selected_id),
                                None,
                            )
                            if idx is not None:
                                st.session_state.emails[idx]["status"] = "rejected"
                                st.session_state.emails[idx]["draft"] = None
                            st.warning("Draft rejected and deleted.")
                            st.rerun()
