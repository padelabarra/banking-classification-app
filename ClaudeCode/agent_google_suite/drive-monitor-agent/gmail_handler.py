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
            service.users().messages().trash(
                userId="me",
                id=msg_id,
            ).execute
        )
        logger.info(f"  → TRASHED (spam) message {msg_id}")

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
