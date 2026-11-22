#!/bin/zsh
cd "$(dirname "$0")"
(sleep 1 && open "http://localhost:8765") &
python3 web_app.py --host 0.0.0.0 --port 8765
