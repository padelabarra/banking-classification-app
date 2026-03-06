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
