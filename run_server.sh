#!/bin/bash
set -e

# Load environment variables if .env exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "Starting AfriVest AI FastAPI Server..."
uv run uvicorn afrivest_ai.api.main:app --host 0.0.0.0 --port 8000 --reload
