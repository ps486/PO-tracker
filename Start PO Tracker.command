#!/bin/bash
# Double-click this file to start PO Tracker (macOS).
# First run installs everything needed (takes a minute or two and needs
# internet access); every run after that starts in a few seconds.
cd "$(dirname "$0")"

PYTHON=python3
if ! command -v $PYTHON &> /dev/null; then
    echo "Python 3 is not installed on this Mac."
    echo "Install it from https://www.python.org/downloads/ , then double-click this file again."
    read -p "Press Enter to close this window..."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "First-time setup - this takes a minute..."
    $PYTHON -m venv .venv
    ./.venv/bin/pip install --upgrade pip -q
    ./.venv/bin/pip install -r requirements.txt -q
fi

./.venv/bin/python run_local.py

echo
read -p "Press Enter to close this window..."
