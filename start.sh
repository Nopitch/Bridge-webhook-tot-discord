#!/bin/bash

echo ""
echo "========================================"
echo "   Starting Discord Bridge"
echo "========================================"
echo ""

# Automatically navigates to the folder where the script is located
cd "$(dirname "$0")"

echo "Launching Discord bridge..."
# Launches the script (uses python3 by default on Linux/Mac)
python3 tot_discord_bridge.py

echo ""
echo "========================================"
echo "   Bridge stopped!"
echo "========================================"
