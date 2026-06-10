from __future__ import annotations
import json
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from agent.prompts import SYSTEM_PROMPT
from agent.tools import ALL_TOOLS, init_tools
from config import settings
from gmail.client import GmailClient
from gmail.models import Draft, Email, IntentResult, ProcessedEmail

_TOOL_MAP = {t.name: t for t in ALL_TOOLS}


class EmailIntelligenceAgent:
    def __init__(self, gmail_client: GmailClient):
        self._gmail = gmail_client
        init_tools(gmail_client)
        base_llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0,
            api_key=settings.openai_api_key,
        )
        self._llm = base_llm.bind_tools(ALL_TOOLS)

    def _run(self, user_prompt: str, max_iterations: int = 15) -> str:
        messages: list = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        for _ in range(max_iterations):
            response: AIMessage = self._llm.invoke(messages)
            messages.append(response)
            if not response.tool_calls:
                return response.content or ""
            for tc in response.tool_calls:
                tool_fn = _TOOL_MAP.get(tc["name"])
                if tool_fn is None:
                    result = f"Unknown tool: {tc['name']}"
                else:
                    try:
                        result = tool_fn.invoke(tc["args"])
                    except Exception as exc:
                        result = f"Tool error: {exc}"
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        return messages[-1].content if hasattr(messages[-1], "content") else ""

    def process_email(self, message_id: str) -> ProcessedEmail:
        prompt = (
            f"Process the email with ID '{message_id}':\n"
            "1. Get its full content with get_email_content\n"
            "2. Detect the intent with detect_email_intent\n"
            "3. If SPAM_PROMOTIONAL: apply label 'spam-ai' with label_and_archive. Done.\n"
            "4. Otherwise: generate a draft reply with draft_reply, save it with "
            "create_gmail_draft, then apply label 'ai-processed' with label_and_archive.\n"
            "Return a JSON summary with keys: message_id, intent, urgency, "
            "confidence, reasoning, action_items, draft_id (or null), draft_body, status."
        )
        output = self._run(prompt)
        return self._build_processed_email(message_id, output)

    def process_all_unread(self, max_results: int = 20) -> list[ProcessedEmail]:
        messages = self._gmail.list_unread(max_results=max_results)
        processed: list[ProcessedEmail] = []
        for msg in messages:
            try:
                pe = self.process_email(msg["id"])
                processed.append(pe)
            except Exception as exc:
                email = self._gmail.get_email(msg["id"])
                processed.append(
                    ProcessedEmail(
                        email=email,
                        intent=IntentResult(
                            intent="GENERAL_INQUIRY",
                            confidence=0.0,
                            reasoning=f"Processing error: {exc}",
                            urgency="low",
                        ),
                        status="pending",
                        processed_at=datetime.now(tz=timezone.utc),
                    )
                )
        return processed

    def _build_processed_email(self, message_id: str, agent_output: str) -> ProcessedEmail:
        email = self._gmail.get_email(message_id)
        now = datetime.now(tz=timezone.utc)

        # Strip markdown code fences if LLM wrapped the JSON
        cleaned = agent_output.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            summary = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            summary = {}

        intent_str = summary.get("intent", "GENERAL_INQUIRY")
        urgency = summary.get("urgency", "medium")
        draft_id = summary.get("draft_id")

        intent = IntentResult(
            intent=intent_str,
            confidence=summary.get("confidence", 0.9),
            reasoning=summary.get("reasoning", "Classified by agent."),
            action_items=summary.get("action_items", []),
            urgency=urgency,
        )

        draft: Draft | None = None
        if draft_id and intent_str != "SPAM_PROMOTIONAL":
            sender_email = email.sender
            if "<" in sender_email:
                sender_email = sender_email.split("<")[1].rstrip(">")
            reply_subject = email.subject
            if not reply_subject.lower().startswith("re:"):
                reply_subject = f"Re: {reply_subject}"
            draft = Draft(
                draft_id=draft_id,
                message_id=message_id,
                to=sender_email,
                subject=reply_subject,
                body=summary.get("draft_body", ""),
            )

        status = "draft_created" if draft else "pending"
        return ProcessedEmail(
            email=email,
            intent=intent,
            draft=draft,
            status=status,
            processed_at=now,
        )
