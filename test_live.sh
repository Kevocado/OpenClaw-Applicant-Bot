#!/bin/bash
source venv/bin/activate
echo "====================================="
echo "   🚀 LAUNCHING LIVE OMNI-SCOUT      "
echo "====================================="
echo "Fetching fresh, active jobs..."
python auto_bridge.py
