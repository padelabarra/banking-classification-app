# Drive + Gmail Monitor Agent — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python agent that monitors Google Drive (every 24h) and Gmail (every 1h), uses Claude to summarize/classify content, and automatically executes actions.

**Architecture:** Single-process infinite loop with two independent time counters (Drive 24h, Gmail 1h), sleeping 5 minutes between iterations. Five modules: auth, drive_handler, gmail_handler, claude_processor, monitor_agent. State persisted in state.json.

**Tech Stack:** Python 3, google-auth, google-auth-oauthlib, google-api-python-client, anthropic SDK, claude-sonnet-4-20250514

---

## Setup

**Working directory for all tasks:** `/Users/padelabarra/Documents/Python/ClaudeCode/agent_google_suite/drive-monitor-agent/`

**Python interpreter:** `/opt/anaconda3/bin/python3`

**Credentials file location:** `../oauth_credentials.json` (relative to working dir)

---

### Task 1: Install dependencies and create project directory

**Files:**
- Create: `drive-monitor-agent/requirements.txt`

**Step 1: Create the working directory**

```bash
mkdir -p /Users/padelabarra/Documents/Python/ClaudeCode/agent_google_suite/drive-monitor-agent
```

**Step 2: Create requirements.txt**

```
google-auth>=2.0.0
google-auth-oauthlib>=1.0.0
google-api-python-client>=2.0.0
anthropic>=0.40.0
```

Save to: `drive-monitor-agent/requirements.txt`

**Step 3: Install dependencies**

```bash
/opt/anaconda3/bin/pip install google-auth google-auth-oauthlib google-api-python-client anthropic
```

Expected: All packages install successfully (or "already satisfied").

**Step 4: Verify imports work**

```bash
/opt/anaconda3/bin/python3 -c "import google.auth; import googleapiclient; import anthropic; print('OK')"
```

Expected output: `OK`

**Step 5: Commit**

```bash
git add drive-monitor-agent/requirements.txt
git commit -m "feat: add drive-monitor-agent requirements"
```

---

### Task 2: Create `auth.py` — OAuth flow

**Files:**
- Create: `drive-monitor-agent/auth.py`

**Step 1: Write the module**

```python
# drive-monitor-agent/auth.py
import os
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.modify",
]

CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "..", "oauth_credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")


def get_credentials() -> Credentials:
    """Load or refresh OAuth credentials, running browser flow if needed."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired token...")
            creds.refresh(Request())
        else:
            logger.info("No valid token found. Opening browser for authentication...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        logger.info("Token saved to token.json")

    return creds
```

**Step 2: Verify syntax**

```bash
/opt/anaconda3/bin/python3 -c "import sys; sys.path.insert(0, 'drive-monitor-agent'); import auth; print('auth.py OK')"
```

Expected: `auth.py OK`

**Step 3: Commit**

```bash
git add drive-monitor-agent/auth.py
git commit -m "feat: add OAuth authentication module"
```

---

### Task 3: Create `claude_processor.py` — Claude API calls

**Files:**
- Create: `drive-monitor-agent/claude_processor.py`

**Step 1: Write the module**

```python
# drive-monitor-agent/claude_processor.py
import logging
import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


def summarize_file(filename: str, content: str) -> dict:
    """
    Summarize a Drive file and classify it by topic.
    Returns: {"summary": str, "topic": str}
    """
    if len(content) > 50000:
        content = content[:50000] + "\n\n[... contenido truncado ...]"

    prompt = f"""Analiza el siguiente archivo de Google Drive y proporciona:
1. Un resumen conciso (máximo 200 palabras)
2. Una categoría temática (ej: Finanzas, Trabajo, Personal, Tecnología, Salud, Legal, Educación, Otro)

Nombre del archivo: {filename}

Contenido:
{content}

Responde en formato JSON exacto:
{{"summary": "...", "topic": "..."}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        text = response.content[0].text.strip()
        # Extract JSON even if there's surrounding text
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except Exception as e:
        logger.error(f"Claude summarize_file error for {filename}: {e}")
        return {"summary": "Error al procesar con Claude.", "topic": "Desconocido"}


def classify_email(subject: str, sender: str, body: str) -> dict:
    """
    Classify an email and recommend an action.
    Returns: {"action": "archive"|"spam"|"important", "reason": str}
    """
    body_preview = body[:2000] if len(body) > 2000 else body

    prompt = f"""Analiza el siguiente email y decide qué hacer con él.

De: {sender}
Asunto: {subject}
Cuerpo: {body_preview}

Clasifícalo y elige UNA acción:
- "important": email importante que requiere atención (trabajo, personal relevante, facturas, citas)
- "archive": email informativo que no requiere acción (newsletters útiles, notificaciones, confirmaciones)
- "spam": publicidad no deseada, phishing, o correo basura

Responde en formato JSON exacto:
{{"action": "archive", "reason": "..."}}"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        text = response.content[0].text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        result = json.loads(text[start:end])
        if result.get("action") not in ("archive", "spam", "important"):
            result["action"] = "archive"
        return result
    except Exception as e:
        logger.error(f"Claude classify_email error: {e}")
        return {"action": "archive", "reason": "Error al clasificar, se archiva por seguridad."}
```

**Step 2: Verify syntax**

```bash
/opt/anaconda3/bin/python3 -c "import sys; sys.path.insert(0, 'drive-monitor-agent'); import claude_processor; print('claude_processor.py OK')"
```

Expected: `claude_processor.py OK`

**Step 3: Commit**

```bash
git add drive-monitor-agent/claude_processor.py
git commit -m "feat: add Claude processor for file summaries and email classification"
```

---

### Task 4: Create `drive_handler.py` — Google Drive monitoring

**Files:**
- Create: `drive-monitor-agent/drive_handler.py`

**Step 1: Write the module**

```python
# drive-monitor-agent/drive_handler.py
import io
import logging
import time
from datetime import datetime, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

import claude_processor

logger = logging.getLogger(__name__)

REPORTS_FOLDER_NAME = "_AgentReports"
MAX_RETRIES = 3


def _retry(fn, *args, **kwargs):
    """Call fn with retries on 429/5xx errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except HttpError as e:
            if e.resp.status in (429, 500, 502, 503) and attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                logger.warning(f"HTTP {e.resp.status}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def _get_or_create_reports_folder(service) -> str:
    """Find or create _AgentReports folder, return its ID."""
    query = f"name='{REPORTS_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = _retry(
        service.files().list(q=query, fields="files(id, name)").execute
    )
    files = results.get("files", [])
    if files:
        folder_id = files[0]["id"]
        logger.info(f"Found existing {REPORTS_FOLDER_NAME} folder: {folder_id}")
        return folder_id

    # Create folder
    metadata = {
        "name": REPORTS_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = _retry(service.files().create(body=metadata, fields="id").execute)
    folder_id = folder["id"]
    logger.info(f"Created {REPORTS_FOLDER_NAME} folder: {folder_id}")
    return folder_id


def _download_file_content(service, file_id: str, mime_type: str) -> str:
    """Download file content as text. Returns empty string on failure."""
    try:
        # Google Docs → export as plain text
        if mime_type == "application/vnd.google-apps.document":
            request = service.files().export_media(fileId=file_id, mimeType="text/plain")
        elif mime_type == "application/vnd.google-apps.spreadsheet":
            request = service.files().export_media(fileId=file_id, mimeType="text/csv")
        elif mime_type in ("text/plain", "text/csv", "text/markdown"):
            request = service.files().get_media(fileId=file_id)
        elif mime_type == "application/pdf":
            # PDFs: download raw bytes, return placeholder
            return "[Archivo PDF — contenido no extraíble en texto plano]"
        else:
            return f"[Tipo de archivo no soportado: {mime_type}]"

        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue().decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"Failed to download file {file_id}: {e}")
        return ""


def _upload_report(service, folder_id: str, report_name: str, content: str):
    """Upload a markdown report to _AgentReports folder."""
    from googleapiclient.http import MediaInMemoryUpload

    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain")
    metadata = {"name": report_name, "parents": [folder_id]}
    _retry(service.files().create(body=metadata, media_body=media, fields="id").execute)
    logger.info(f"Uploaded report: {report_name}")


def check_drive(creds, state: dict) -> str | None:
    """
    Check Drive for new/modified files since last check.
    Summarizes each with Claude and uploads a report to _AgentReports.
    Returns updated reports_folder_id (or None on total failure).
    """
    try:
        service = build("drive", "v3", credentials=creds)

        # Ensure _AgentReports folder exists
        folder_id = state.get("drive_reports_folder_id")
        if not folder_id:
            folder_id = _get_or_create_reports_folder(service)

        last_check = state.get("last_drive_check", "2000-01-01T00:00:00Z")
        logger.info(f"Drive check — files modified since {last_check}")

        # List files modified since last check, excluding _AgentReports folder itself
        query = (
            f"modifiedTime > '{last_check}' "
            f"and trashed = false "
            f"and '{folder_id}' not in parents"
        )
        results = _retry(
            service.files().list(
                q=query,
                fields="files(id, name, mimeType, modifiedTime)",
                pageSize=50,
                orderBy="modifiedTime desc",
            ).execute
        )
        files = results.get("files", [])
        logger.info(f"Found {len(files)} new/modified files")

        if not files:
            return folder_id

        report_lines = [
            f"# Drive Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"Files processed: {len(files)}",
            "",
        ]

        for f in files:
            name = f["name"]
            file_id = f["id"]
            mime = f["mimeType"]
            modified = f["modifiedTime"]
            logger.info(f"Processing: {name} ({mime})")

            content = _download_file_content(service, file_id, mime)
            if content:
                result = claude_processor.summarize_file(name, content)
                summary = result.get("summary", "")
                topic = result.get("topic", "Desconocido")
            else:
                summary = "No se pudo leer el contenido."
                topic = "Desconocido"

            report_lines += [
                f"## {name}",
                f"- **Tema:** {topic}",
                f"- **Modificado:** {modified}",
                f"- **Resumen:** {summary}",
                "",
            ]

        report_content = "\n".join(report_lines)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        _upload_report(service, folder_id, f"report_{ts}.md", report_content)

        return folder_id

    except Exception as e:
        logger.error(f"Drive check failed: {e}")
        return state.get("drive_reports_folder_id")
```

**Step 2: Verify syntax**

```bash
/opt/anaconda3/bin/python3 -c "import sys; sys.path.insert(0, 'drive-monitor-agent'); import drive_handler; print('drive_handler.py OK')"
```

Expected: `drive_handler.py OK`

**Step 3: Commit**

```bash
git add drive-monitor-agent/drive_handler.py
git commit -m "feat: add Drive monitoring handler"
```

---

### Task 5: Create `gmail_handler.py` — Gmail monitoring

**Files:**
- Create: `drive-monitor-agent/gmail_handler.py`

**Step 1: Write the module**

```python
# drive-monitor-agent/gmail_handler.py
import base64
import logging
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import claude_processor

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
MAX_EMAILS_PER_RUN = 20  # avoid processing hundreds at once


def _retry(fn, *args, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except HttpError as e:
            if e.resp.status in (429, 500, 502, 503) and attempt < MAX_RETRIES - 1:
                wait = 2 ** attempt
                logger.warning(f"HTTP {e.resp.status}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def _get_email_body(payload: dict) -> str:
    """Recursively extract plain text body from email payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _get_email_body(part)
        if result:
            return result
    return ""


def _apply_action(service, msg_id: str, action: str):
    """Apply the recommended action to a Gmail message."""
    if action == "archive":
        _retry(
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["INBOX"]},
            ).execute
        )
        logger.info(f"  → ARCHIVED message {msg_id}")

    elif action == "spam":
        _retry(
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]},
            ).execute
        )
        logger.info(f"  → SPAM message {msg_id}")

    elif action == "important":
        _retry(
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": ["STARRED"]},
            ).execute
        )
        logger.info(f"  → STARRED (important) message {msg_id}")


def check_inbox(creds):
    """
    Fetch unread emails, classify with Claude, and execute actions.
    """
    try:
        service = build("gmail", "v1", credentials=creds)

        results = _retry(
            service.users().messages().list(
                userId="me",
                labelIds=["INBOX", "UNREAD"],
                maxResults=MAX_EMAILS_PER_RUN,
            ).execute
        )
        messages = results.get("messages", [])
        logger.info(f"Gmail check — {len(messages)} unread emails")

        for msg_ref in messages:
            msg_id = msg_ref["id"]
            try:
                msg = _retry(
                    service.users().messages().get(
                        userId="me", id=msg_id, format="full"
                    ).execute
                )

                headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
                subject = headers.get("Subject", "(sin asunto)")
                sender = headers.get("From", "(desconocido)")
                body = _get_email_body(msg["payload"])
                if not body:
                    body = msg.get("snippet", "")

                logger.info(f"Processing email: '{subject}' from {sender}")

                result = claude_processor.classify_email(subject, sender, body)
                action = result.get("action", "archive")
                reason = result.get("reason", "")
                logger.info(f"  Claude says: {action} — {reason}")

                _apply_action(service, msg_id, action)

                # Mark as read after processing
                _retry(
                    service.users().messages().modify(
                        userId="me",
                        id=msg_id,
                        body={"removeLabelIds": ["UNREAD"]},
                    ).execute
                )

            except Exception as e:
                logger.error(f"Failed to process email {msg_id}: {e}")
                continue

    except Exception as e:
        logger.error(f"Gmail check failed: {e}")
```

**Step 2: Verify syntax**

```bash
/opt/anaconda3/bin/python3 -c "import sys; sys.path.insert(0, 'drive-monitor-agent'); import gmail_handler; print('gmail_handler.py OK')"
```

Expected: `gmail_handler.py OK`

**Step 3: Commit**

```bash
git add drive-monitor-agent/gmail_handler.py
git commit -m "feat: add Gmail inbox monitoring handler"
```

---

### Task 6: Create `monitor_agent.py` — main loop

**Files:**
- Create: `drive-monitor-agent/monitor_agent.py`

**Step 1: Write the module**

```python
#!/usr/bin/env python3
# drive-monitor-agent/monitor_agent.py
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# Ensure local imports work when run from any directory
sys.path.insert(0, os.path.dirname(__file__))

import auth
import drive_handler
import gmail_handler

# ── Logging setup ──────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(__file__), "agent.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ── State ──────────────────────────────────────────────────────────────────────
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

DRIVE_INTERVAL_SECONDS = 24 * 3600   # 24 hours
GMAIL_INTERVAL_SECONDS = 1 * 3600    # 1 hour
SLEEP_INTERVAL_SECONDS = 5 * 60      # 5 minutes between loop iterations


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def seconds_since(iso_timestamp: str | None) -> float:
    if not iso_timestamp:
        return float("inf")
    dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds()


# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    logger.info("=" * 60)
    logger.info("Drive + Gmail Monitor Agent starting...")
    logger.info("=" * 60)

    creds = auth.get_credentials()
    logger.info("OAuth authentication successful")

    state = load_state()

    while True:
        # ── Gmail check (every 1h) ──────────────────────────────────────────
        if seconds_since(state.get("last_gmail_check")) >= GMAIL_INTERVAL_SECONDS:
            logger.info("--- Gmail check started ---")
            gmail_handler.check_inbox(creds)
            state["last_gmail_check"] = now_iso()
            save_state(state)
            logger.info("--- Gmail check done ---")

        # ── Drive check (every 24h) ─────────────────────────────────────────
        if seconds_since(state.get("last_drive_check")) >= DRIVE_INTERVAL_SECONDS:
            logger.info("--- Drive check started ---")
            folder_id = drive_handler.check_drive(creds, state)
            if folder_id:
                state["drive_reports_folder_id"] = folder_id
            state["last_drive_check"] = now_iso()
            save_state(state)
            logger.info("--- Drive check done ---")

        logger.info(f"Sleeping {SLEEP_INTERVAL_SECONDS // 60} minutes...")
        time.sleep(SLEEP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
```

**Step 2: Verify syntax**

```bash
/opt/anaconda3/bin/python3 -c "
import ast, sys
with open('drive-monitor-agent/monitor_agent.py') as f:
    ast.parse(f.read())
print('monitor_agent.py syntax OK')
"
```

Expected: `monitor_agent.py syntax OK`

**Step 3: Commit**

```bash
git add drive-monitor-agent/monitor_agent.py
git commit -m "feat: add main monitor agent loop"
```

---

### Task 7: Run OAuth authentication and start agent

**Step 1: Verify ANTHROPIC_API_KEY is set**

```bash
echo $ANTHROPIC_API_KEY
```

Expected: starts with `sk-ant-...`

If not set:
```bash
export ANTHROPIC_API_KEY="your-key-here"
```

**Step 2: Run the agent (triggers OAuth browser flow on first run)**

```bash
cd /Users/padelabarra/Documents/Python/ClaudeCode/agent_google_suite/drive-monitor-agent && /opt/anaconda3/bin/python3 monitor_agent.py
```

Expected on first run:
1. Browser opens to Google OAuth consent screen
2. User authorizes access
3. Terminal shows: `OAuth authentication successful`
4. `token.json` created in `drive-monitor-agent/`
5. Gmail check begins immediately
6. Drive check begins immediately
7. Loop continues, sleeping 5 minutes between iterations

**Step 3: Verify outputs**

Check `agent.log` was created:
```bash
tail -20 /Users/padelabarra/Documents/Python/ClaudeCode/agent_google_suite/drive-monitor-agent/agent.log
```

Check `state.json` was created:
```bash
cat /Users/padelabarra/Documents/Python/ClaudeCode/agent_google_suite/drive-monitor-agent/state.json
```

**Step 4: Final commit**

```bash
git add drive-monitor-agent/
git commit -m "feat: complete drive+gmail monitor agent"
```

Note: Add `token.json`, `state.json`, and `agent.log` to `.gitignore` to avoid committing secrets/runtime state.

---

## .gitignore additions

Add to project root `.gitignore` (or create if missing):

```
drive-monitor-agent/token.json
drive-monitor-agent/state.json
drive-monitor-agent/agent.log
```
