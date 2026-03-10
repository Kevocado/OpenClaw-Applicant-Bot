#!/bin/bash
# OpenClaw Startup Script
# Usage: ./start.sh
# Starts the daemon in a persistent tmux session. Safe to run multiple times.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="bot"

echo "🚀 Starting OpenClaw..."

# Kill any existing daemon process
pkill -f "python3 unified_daemon.py" 2>/dev/null

# Create a new detached tmux session (or attach to existing)
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "⚠️  Session '$SESSION' already exists. Sending restart command..."
    tmux send-keys -t "$SESSION" "C-c" ""
    sleep 1
    tmux send-keys -t "$SESSION" "cd $PROJECT_DIR && source venv/bin/activate && python3 unified_daemon.py" Enter
else
    tmux new-session -d -s "$SESSION" -x 220 -y 50
    tmux send-keys -t "$SESSION" "cd $PROJECT_DIR && source venv/bin/activate && python3 unified_daemon.py" Enter
fi

echo ""
echo "✅ OpenClaw is running in tmux session '$SESSION'."
echo ""
echo "   To watch logs:    tmux attach -t $SESSION"
echo "   To detach:        Ctrl+B, then D"
echo "   To stop:          pkill -f 'python3 unified_daemon.py'"
