#!/bin/bash
source venv/bin/activate
URL=${1:-"https://www.linkedin.com/jobs/view/data-analyst-at-insight-digital-innovation-4122137681"}
python apply_agent.py "$URL"
