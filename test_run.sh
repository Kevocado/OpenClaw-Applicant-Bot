#!/bin/bash
export PYTHONPATH=/root/OpenClaw-Applicant-Bot
echo "Running Omni Scout manually for a test..."
python3 /root/OpenClaw-Applicant-Bot/omni_scout.py

echo -e "\nRunning Auto Bridge (Apply + LLM Bouncer)..."
python3 /root/OpenClaw-Applicant-Bot/auto_bridge.py
