#!/bin/bash
# Double-click this file to start PO Tracker (macOS).
# First run installs everything needed (takes a minute or two and needs
# internet access); every run after that starts in a few seconds.
cd "$(dirname "$0")"

PYTHON=python3
# macOS ships a stub "python3" that pops up an "Install Command Line
# Developer Tools" dialog instead of running, even when Python isn't
# properly installed - so we actually try to run it, not just check it exists.
if ! command -v $PYTHON &> /dev/null || [ "$($PYTHON -c 'print("OK")' 2>/dev/null)" != "OK" ]; then
    echo "============================================================"
    echo "  Python 3 was not found (or only a placeholder is)"
    echo "============================================================"
    echo
    echo "If a popup appeared asking to install 'Command Line Developer"
    echo "Tools', that's a different, incomplete install - close that popup."
    echo
    echo "Install real Python 3 from https://www.python.org/downloads/"
    echo "(download the macOS installer, run it, then come back here)."
    echo
    echo "Then double-click this file again."
    read -p "Press Enter to close this window..."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "First-time setup - this takes a minute..."
    $PYTHON -m venv .venv
    if [ ! -f "./.venv/bin/python" ]; then
        echo
        echo "Something went wrong creating the Python environment."
        echo "Try closing this window and double-clicking this file again."
        read -p "Press Enter to close this window..."
        exit 1
    fi
    ./.venv/bin/pip install --upgrade pip -q
    ./.venv/bin/pip install -r requirements.txt -q
fi

./.venv/bin/python run_local.py

echo
read -p "Press Enter to close this window..."
