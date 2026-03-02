#!/bin/bash
# Usage: ./deploy.sh <workflow_id> <path_to_json_file>

N8N_URL="http://localhost:5678/api/v1/workflows"
API_KEY="PASTE_YOUR_N8N_API_KEY_HERE"

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: ./deploy.sh <workflow_id> <path_to_json_file>"
    exit 1
fi

WORKFLOW_ID=$1
FILE_PATH=$2

curl -X PUT "$N8N_URL/$WORKFLOW_ID" \
     -H "X-N8N-API-KEY: $API_KEY" \
     -H "Content-Type: application/json" \
     -d @"$FILE_PATH"

echo -e "\nDeployment complete for workflow: $WORKFLOW_ID"
