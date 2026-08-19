#!/bin/bash
# GW-Repo Setup Script
# Creates .env file and starts all services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    python3 setup.py
    echo
fi

# Start services
echo "Starting services..."
docker compose up -d

echo
echo "Services started successfully!"
echo
echo "To view logs:"
echo "  docker compose logs -f"
echo
echo "To stop services:"
echo "  docker compose down"
echo
