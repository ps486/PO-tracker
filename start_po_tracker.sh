#!/bin/bash
# Double-click this file to start PO Tracker (Linux), or run it from a
# terminal with: ./start_po_tracker.sh
# First run installs everything needed (takes a minute or two and needs
# internet access); every run after that starts in a few seconds.
cd "$(dirname "$0")"

PYTHON=python3
if ! command -v $PYTHON &> /dev/null; then
    echo "Python 3 is not installed."
    echo "Install it with your package manager (e.g. sudo apt install python3 python3-venv), then run this again."
    read -p "Press Enter to close this window..."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "First-time setup - this takes a minute..."
    $PYTHON -m venv .venv
    if [ ! -f "./.venv/bin/python" ]; then
        echo
        echo "Could not create the Python environment - you likely need the venv module:"
        echo "  sudo apt install python3-venv   (Debian/Ubuntu)"
        echo "Then run this again."
        read -p "Press Enter to close this window..."
        exit 1
    fi
    ./.venv/bin/pip install --upgrade pip -q
    ./.venv/bin/pip install -r requirements.txt -q
fi

./.venv/bin/python run_local.py

echo
read -p "Press Enter to close this window..."
