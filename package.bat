@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   AI-Builder Packaging Script (Windows)
echo ========================================

REM Check for Python
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH. Please install Python 3.8+ and try again.
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo [INFO] Creating virtual environment...
    py -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate virtual environment.
    exit /b 1
)

REM Upgrade pip and install dependencies
echo [INFO] Installing dependencies and PyInstaller...
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

REM Clean previous builds
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
if exist "ai_builder.spec" del /q "ai_builder.spec"

REM Build single executable
echo [INFO] Building executable...
pyinstaller ^
    --onefile ^
    --name ai-builder ^
    --hidden-import=flask ^
    --hidden-import=dotenv ^
    --hidden-import=azure.ai.inference ^
    --hidden-import=azure.ai.inference.models ^
    --hidden-import=azure.core.credentials ^
    --hidden-import=agent_engine ^
    --hidden-import=agent_engine.tools ^
    --hidden-import=oneshot_engine ^
    --hidden-import=oneshot_engine.parser ^
    --hidden-import=oneshot_engine.modifier ^
    --hidden-import=oneshot_engine.action_manager ^
    --hidden-import=oneshot_engine.code_utility ^
    --hidden-import=oneshot_engine.engine ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "base_config.xml;." ^
    --add-data "oneshot_engine;oneshot_engine" ^
    --add-data "agent_engine;agent_engine" ^
    ui.py

REM Check build success
if exist "dist\ai-builder.exe" (
    echo [SUCCESS] Packaging complete!
    echo [INFO] Executable location: dist\ai-builder.exe
    echo [INFO] To run: dist\ai-builder.exe
    pause
) else (
    echo [ERROR] Build failed. Check PyInstaller output above.
    exit /b 1
)
