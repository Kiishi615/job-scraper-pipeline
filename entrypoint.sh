#!/bin/bash
# Start Xvfb virtual display
Xvfb :99 -screen 0 1366x768x24 -nolisten tcp -nolisten unix &
sleep 2

# Run whatever command was passed (scheduler.py by default, or override from GitHub Actions)
exec "$@"
