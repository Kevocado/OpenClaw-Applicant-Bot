#!/bin/bash
# ─── n8n Workflow Sync Script ───
# Pulls latest from GitHub and imports/updates workflow JSON files into n8n
# via the n8n REST API.
#
# Usage:
#   cd /root/OpenClaw-Applicant-Bot
#   bash sync_workflows.sh
#
# Can also be run as a git post-merge hook or cron job.

set -e

N8N_URL="${N8N_URL:-http://localhost:5678}"
N8N_API_KEY="${N8N_API_KEY}"
WORKFLOW_DIR="./n8n_workflows"

# ─── Check prerequisites ───
if [ -z "$N8N_API_KEY" ]; then
    echo "❌ N8N_API_KEY not set."
    echo ""
    echo "To generate one:"
    echo "  1. Open n8n dashboard → Settings (gear icon) → API"
    echo "  2. Click 'Create an API key'"
    echo "  3. Add to your .env: N8N_API_KEY=your_key_here"
    echo "  4. Run: source .env && bash sync_workflows.sh"
    exit 1
fi

# ─── Pull latest from GitHub ───
echo "[SYNC] Pulling latest from GitHub..."
git pull origin main --quiet

# ─── Import each workflow JSON ───
echo "[SYNC] Scanning $WORKFLOW_DIR for workflow files..."
for file in "$WORKFLOW_DIR"/*.json; do
    [ -f "$file" ] || continue
    
    name=$(basename "$file" .json)
    echo ""
    echo "[SYNC] Processing: $name"

    # Check if workflow already exists by name
    workflow_name=$(python3 -c "import json; print(json.load(open('$file'))['name'])" 2>/dev/null || echo "$name")
    
    existing_id=$(curl -s -H "X-N8N-API-KEY: $N8N_API_KEY" \
        "$N8N_URL/api/v1/workflows" | \
        python3 -c "
import json, sys
data = json.load(sys.stdin)
for wf in data.get('data', []):
    if wf['name'] == '$workflow_name':
        print(wf['id'])
        break
" 2>/dev/null || echo "")

    if [ -n "$existing_id" ]; then
        # Update existing workflow
        echo "  → Updating existing workflow (ID: $existing_id)"
        curl -s -X PUT \
            -H "X-N8N-API-KEY: $N8N_API_KEY" \
            -H "Content-Type: application/json" \
            -d @"$file" \
            "$N8N_URL/api/v1/workflows/$existing_id" > /dev/null
        echo "  ✅ Updated: $workflow_name"
    else
        # Create new workflow
        echo "  → Creating new workflow"
        curl -s -X POST \
            -H "X-N8N-API-KEY: $N8N_API_KEY" \
            -H "Content-Type: application/json" \
            -d @"$file" \
            "$N8N_URL/api/v1/workflows" > /dev/null
        echo "  ✅ Created: $workflow_name"
    fi
done

echo ""
echo "[SYNC] ✅ All workflows synced!"
echo ""
echo "Tip: To auto-sync on every git pull, run:"
echo "  cp sync_workflows.sh .git/hooks/post-merge && chmod +x .git/hooks/post-merge"
