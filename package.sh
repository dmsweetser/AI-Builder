#!/bin/bash
# AI-Builder Packaging Script (Linux)
# Produces a single ELF executable with all dependencies bundled.
# The executable uses a relative ./aib_instance directory for configs,
# model downloads, chat history, etc.

set -e

echo "========================================"
echo "  AI-Builder Packaging Script (Linux)"
echo "========================================"

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 is not installed or not in PATH. Please install Python 3.8+ and try again."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to activate virtual environment."
    exit 1
fi

# Install dependencies and PyInstaller
echo "[INFO] Installing dependencies and PyInstaller..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

# Clean previous builds
rm -rf dist build ai_builder.spec

# Build single executable
echo "[INFO] Building executable..."
pyinstaller \
    --onefile \
    --name ai_builder.bin \
    --hidden-import=flask \
    --hidden-import=dotenv \
    --hidden-import=azure.ai.inference \
    --hidden-import=azure.ai.inference.models \
    --hidden-import=azure.core.credentials \
    --hidden-import=agent_engine \
    --hidden-import=agent_engine.tools \
    --hidden-import=oneshot_engine \
    --hidden-import=oneshot_engine.parser \
    --hidden-import=oneshot_engine.modifier \
    --hidden-import=oneshot_engine.action_manager \
    --hidden-import=oneshot_engine.code_utility \
    --hidden-import=oneshot_engine.engine \
    --add-data "templates:templates" \
    --add-data "static:static" \
    --add-data "base_config.xml:." \
    --add-data "oneshot_engine:oneshot_engine" \
    --add-data "agent_engine:agent_engine" \
    ui.py

# Check build success
if [ -f "dist/ai_builder.bin" ]; then
    echo "[SUCCESS] Packaging complete!"
    echo "[INFO] Executable location: dist/ai_builder.bin"
    echo "[INFO] To run: ./dist/ai_builder.bin"
    chmod +x dist/ai_builder.bin
else
    echo "[ERROR] Build failed. Check PyInstaller output above."
    exit 1
fi
