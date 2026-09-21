#!/usr/bin/env python3
"""Run the PO Tracker entirely on this machine - no hosting account, no
Postgres, no .env file to edit.

What this does:
  - Creates a folder called `po_tracker_data` right next to this file, and
    puts a single database file and your downloaded attachments in it.
  - Starts the app on your own computer at http://127.0.0.1:8000
  - Opens that address in your default browser automatically.

Everything else (your AI key, your Gmail connection) is set up from inside
the browser - open the Settings tab after your first login.

To stop the app: close this window, or press Ctrl+C in it.
"""
from __future__ import annotations

import os
import secrets
import sys
import threading
import time
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "po_tracker_data")
ATTACHMENTS_DIR = os.path.join(DATA_DIR, "attachments")
DB_PATH = os.path.join(DATA_DIR, "po_tracker.db")
SECRET_KEY_PATH = os.path.join(DATA_DIR, "secret_key.txt")
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8000"))


def _get_or_create_secret_key() -> str:
    """The encryption key for your saved Gmail connection and API keys must
    stay the same across restarts, or they become unreadable. Generated once,
    then reused - never regenerated as long as this file exists."""
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, "r") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w") as f:
        f.write(key)
    return key


def _open_browser_when_ready(url: str) -> None:
    time.sleep(1.5)
    webbrowser.open(url)


def main() -> None:
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

    # These must be set BEFORE importing anything from backend.app, since
    # config.py reads them from the environment exactly once, at import time.
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{DB_PATH}")
    os.environ.setdefault("SECRET_KEY", _get_or_create_secret_key())
    os.environ.setdefault("ATTACHMENT_STORAGE_DIR", ATTACHMENTS_DIR)
    os.environ.setdefault("GOOGLE_OAUTH_REDIRECT_URI", f"http://{HOST}:{PORT}/api/auth/gmail/callback")
    os.environ.setdefault("ENVIRONMENT", "local")

    sys.path.insert(0, BASE_DIR)
    import uvicorn

    url = f"http://{HOST}:{PORT}/dashboard/"
    print("=" * 60)
    print("  PO Tracker is starting...")
    print(f"  Your data is stored in: {DATA_DIR}")
    print(f"  Opening {url} in your browser.")
    print("  To stop: close this window, or press Ctrl+C.")
    print("=" * 60)

    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

    from backend.app.main import app
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
