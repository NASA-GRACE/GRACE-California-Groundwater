#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v pixi >/dev/null 2>&1; then
  echo "ERROR: 'pixi' not found. Install: https://pixi.sh/"
  exit 1
fi

echo "Using pixi $(pixi --version | cut -d' ' -f2)"

echo "Installing dependencies..."
pixi install

echo ""
echo "Setup complete."
echo "  Python: $(pixi run python --version)"
echo ""
echo "To activate environment:  pixi shell"
echo "To run a command:         pixi run python your_script.py"
echo "To add a dependency:      pixi add package-name"
echo "To update lockfile:       pixi update"
