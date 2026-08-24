
#!/bin/bash
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

# Upgrade pip and install dependencies
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
    --name ai-builder \
    --hidden-import=flask \
    --hidden-import=dotenv \
    --hidden-import=azure.ai.inference \
    --hidden-import=azure.ai.projects \
    --hidden-import=azure.identity \
    --hidden-import=azure.core.credentials \
    --add-data "templates:templates" \
    --add-data "aib_instance:aib_instance" \
    ui.py

# Check build success
if [ -f "dist/ai-builder" ]; then
    echo "[SUCCESS] Packaging complete!"
    echo "[INFO] Executable location: dist/ai-builder"
    echo "[INFO] To run: ./dist/ai-builder"
    chmod +x dist/ai-builder
else
    echo "[ERROR] Build failed. Check PyInstaller output above."
    exit 1
fi
