@echo off
setlocal enabledelayedexpansion

echo Setting up AI-Builder...

REM -------------------------------
REM Create directories
REM -------------------------------
mkdir aib_instance
mkdir aib_instance\conversations
mkdir aib_instance\chats

REM -------------------------------
REM Create virtual environment
REM -------------------------------
echo Creating Python virtual environment...
py -m venv venv
if %errorlevel% neq 0 (
    echo Error: Failed to create virtual environment
    exit /b 1
)

REM -------------------------------
REM Activate virtual environment
REM -------------------------------
echo Activating virtual environment...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo Error: Failed to activate virtual environment
    exit /b 1
)

REM -------------------------------
REM Install requirements
REM -------------------------------
pip install --upgrade pip
pip install -r requirements.txt

echo Installation complete
echo To activate the virtual environment later, run: venv\Scripts\activate.bat
