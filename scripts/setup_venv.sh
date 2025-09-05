#!/bin/bash
set -euo pipefail

PY_VERSION="3.12"

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON="${PYTHON:-python${PY_VERSION}}"

# Ensure the interpreter exists
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "❌ '$PYTHON' not found. Install Python ${PY_VERSION} (e.g. 'brew install python@${PY_VERSION}') or set PYTHON to your ${PY_VERSION} path."
  exit 1
fi

echo "➡️ Using interpreter: $("$PYTHON" -V) at $(command -v "$PYTHON")"

# Recreate venv if missing or wrong version
if [ -d "$VENV_DIR" ]; then
  EXISTING_VER="$("$VENV_DIR/bin/python" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "unknown")"
  if [ "$EXISTING_VER" != "${PY_VERSION}" ]; then
    echo "♻️  Existing venv is Python $EXISTING_VER; recreating with Python ${PY_VERSION}..."
    rm -rf "$VENV_DIR"
  else
    echo "✅ Existing venv is already Python ${PY_VERSION}."
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "🧪 Creating venv at $VENV_DIR with $PYTHON ..."
  "$PYTHON" -m venv "$VENV_DIR"
fi

echo "🔌 Activating venv..."
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

# Upgrade pip/setuptools/wheel (fewer build headaches)
python -m pip install --upgrade pip setuptools wheel

# Install requirements
if [ -f "requirements.txt" ]; then
  echo "📦 Installing from requirements.txt ..."
  python -m pip install -r requirements.txt
else
  echo "ℹ️  No requirements.txt found; skipping package install."
fi

echo "✅ Setup complete."
echo "   VIRTUAL_ENV=$VIRTUAL_ENV"
python -V
