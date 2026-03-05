# Drive + Gmail Monitor Agent — Design

**Date:** 2026-03-04
**Status:** Approved

## Overview

A Python agent that monitors Google Drive (every 24h) and Gmail (every 1h) autonomously. Uses Claude to summarize Drive files and classify emails, then takes automatic actions.

## Architecture

Single-process loop with two independent time counters. No external scheduler dependencies.

```
agent_google_suite/
├── oauth_credentials.json       ← OAuth Desktop App credentials
└── drive-monitor-agent/
    ├── monitor_agent.py         ← main loop (Drive 24h, Gmail 1h)
    ├── drive_handler.py         ← detect new/modified files, upload reports
    ├── gmail_handler.py         ← read inbox, execute actions
    ├── claude_processor.py      ← Claude API calls (summarize, classify)
    ├── auth.py                  ← OAuth flow, token management
    ├── state.json               ← persistent timestamps (auto-generated)
    ├── token.json               ← OAuth token (auto-generated on first run)
    └── agent.log                ← timestamped logs (auto-generated)
```

## Main Loop (`monitor_agent.py`)

```
infinite loop:
  ├── if ≥1h since last gmail check  → gmail_handler.check_inbox() → claude → execute actions
  ├── if ≥24h since last drive check → drive_handler.check_drive() → claude → upload report
  └── sleep 5 minutes
```

## Components

### `auth.py`
- OAuth scopes: `drive`, `gmail.modify`
- First run: opens browser for manual auth, saves `token.json`
- Subsequent runs: loads and auto-refreshes token

### `drive_handler.py`
1. Read `last_drive_check` from `state.json`
2. Call `files.list` with `modifiedTime > last_drive_check`
3. Download content (Google Docs → text, PDF, txt)
4. Call `claude_processor.summarize_file()` → summary + topic
5. Create `.md` report in `_AgentReports` folder on Drive
6. Update `state.json`

### `gmail_handler.py`
1. Fetch unread emails (`UNREAD` in INBOX)
2. Extract subject, sender, snippet per email
3. Call `claude_processor.classify_email()` → `{"action": "archive"|"spam"|"important", "reason": "..."}`
4. Execute action: archive (remove INBOX label), spam (move to spam), important (add star)
5. Log action taken

### `claude_processor.py`
- `summarize_file(name, content)` → summary + thematic category
- `classify_email(subject, sender, body)` → recommended action + reason
- Model: `claude-sonnet-4-20250514`

## State (`state.json`)

```json
{
  "last_drive_check": "2026-03-04T10:00:00Z",
  "last_gmail_check": "2026-03-04T14:00:00Z",
  "drive_reports_folder_id": "1AbC..."
}
```

## Error Handling

- Try/except per handler — if Drive fails, Gmail continues
- Auto-retry on 429/5xx: up to 3 attempts with exponential backoff
- All errors logged to `agent.log`

## Logging Format

```
2026-03-04 14:00:01 [INFO] Gmail check started — 3 unread emails
2026-03-04 14:00:02 [INFO] Email "Promo Amazon" → SPAM (executed)
2026-03-04 14:00:03 [INFO] Email "Reunión equipo" → IMPORTANT (starred)
```

## First Run Flow

1. `pip install google-auth google-auth-oauthlib google-api-python-client anthropic`
2. `python monitor_agent.py`
3. Browser opens → Google auth → generates `token.json`
4. Creates `_AgentReports` folder in Drive, saves folder ID to `state.json`
5. Loop begins

## Dependencies

```
google-auth
google-auth-oauthlib
google-api-python-client
anthropic
```
