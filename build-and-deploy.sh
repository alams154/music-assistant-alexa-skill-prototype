#!/bin/bash
# Build and Deploy Script for Music Assistant Alexa Skill

set -e  # Exit on error

echo "=== Building Music Assistant Alexa Skill Docker Image ==="
docker compose build

echo ""
echo "=== Stopping existing container ==="
docker compose down

echo ""
echo "=== Starting updated container ==="
docker compose up -d

echo ""
echo "=== Deployment complete! ==="
echo ""
echo "View logs with: docker compose logs -f music-assistant-skill"
echo ""
