# Autonomous Email Intelligence Agent

Reads Gmail, classifies intent, drafts replies, and routes approvals — all in a Streamlit dashboard. **Draft-only safety model**: the agent never sends email autonomously.

## Architecture

```
Gmail API → LangChain Agent (OpenAI functions) → FastAPI backend → Streamlit UI
```

| Component | Purpose |
|---|---|
| `gmail/client.py` | OAuth2 Gmail wrapper (read, draft, label, send-draft) |
| `agent/` | LangChain AgentExecutor with 6 OpenAI function tools |
| `api/main.py` | FastAPI REST API (state store + human-triggered send) |
| `ui/app.py` | Streamlit inbox dashboard |

## Intent Classes

| Intent | Action |
|---|---|
| `APPROVAL_REQUEST` | Draft acknowledgement reply |
| `GENERAL_INQUIRY` | Draft informative reply |
| `ACTION_ITEM` | Extract tasks + draft confirmation |
| `SPAM_PROMOTIONAL` | Label `spam-ai`, no draft |

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Google OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Gmail API**
3. Create **OAuth 2.0 Client ID** (Desktop app type)
4. Download `credentials.json` → place in `credentials/credentials.json`

### 3. Environment variables
```bash
cp .env.example .env
# Edit .env and set your OPENAI_API_KEY
```

### 4. First-run OAuth (opens browser once)
```bash
cd email_agent
python -c "from gmail.client import GmailClient; from config import settings; GmailClient(settings.gmail_credentials_file, settings.gmail_token_file, settings.gmail_scopes)"
```
Authorize in the browser — `credentials/token.json` is saved and reused.

### 5. Run the backend
```bash
uvicorn api.main:app --reload --port 8000
```

### 6. Run the UI (new terminal)
```bash
streamlit run ui/app.py
```

Open `http://localhost:8501` and click **Fetch & Process Emails**.

## Usage

1. Click **Fetch & Process Emails** — the agent reads unread emails, classifies them, and creates Gmail drafts
2. Select an email from the left panel
3. Review the intent classification and confidence score
4. Edit the draft if needed → **Save Draft**
5. Click **Send Draft** to send, or **Reject** to delete the draft

## Gmail Scopes

Uses `gmail.modify` scope only — provides read + draft + label access without full send permission. The `send_draft` call is made only by `POST /emails/{id}/send` (human-triggered endpoint).

## Project Structure

```
email_agent/
├── .env                  ← your secrets (gitignored)
├── config.py
├── requirements.txt
├── gmail/
│   ├── client.py         ← Gmail API wrapper
│   └── models.py         ← Pydantic models
├── agent/
│   ├── prompts.py        ← system prompts
│   ├── tools.py          ← 6 LangChain tools
│   └── email_agent.py    ← AgentExecutor
├── api/
│   └── main.py           ← FastAPI endpoints
├── ui/
│   └── app.py            ← Streamlit dashboard
└── credentials/          ← OAuth files (gitignored)
```
