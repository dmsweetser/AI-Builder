@echo off
setlocal enabledelayedexpansion

echo Setting up Python virtual environment...

REM -------------------------------
REM Check if Python is installed
REM -------------------------------
where py > nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed. Please install Python before running this script.
    exit /b 1
)

REM -------------------------------
REM Create virtual environment
REM -------------------------------
if not exist venv (
    py -m venv venv
    if %errorlevel% neq 0 (
        echo Error: Unable to create virtual environment.
        exit /b 1
    )
    echo Virtual environment created successfully.
) else (
    echo Virtual environment already exists.
)

REM -------------------------------
REM Activate virtual environment
REM -------------------------------
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo Error: Unable to activate virtual environment.
    exit /b 1
)

echo Virtual environment activated successfully.

REM -------------------------------
REM Install Python dependencies
REM -------------------------------
if exist requirements.txt (
    echo Installing required Python packages...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo Error: Unable to install required Python packages.
        exit /b 1
    )
    echo Required Python packages installed successfully.
)

REM -------------------------------
REM Clone or update llama.cpp source
REM -------------------------------
echo Checking llama.cpp source folder...

if not exist llama.cpp (
    echo Cloning llama.cpp repository...
    git clone https://github.com/ggerganov/llama.cpp
    if %errorlevel% neq 0 (
        echo Error: Failed to clone llama.cpp.
        exit /b 1
    )
) else (
    echo llama.cpp already exists. Updating...
    pushd llama.cpp
    git pull
    popd
)

REM -------------------------------
REM Download prebuilt Windows binaries (direct link)
REM -------------------------------
echo Downloading latest llama.cpp Windows binary release...

set DOWNLOAD_URL=https://github.com/ggml-org/llama.cpp/releases/download/b8400/llama-b8400-bin-win-cpu-x64.zip

powershell -Command ^
    "Invoke-WebRequest '%DOWNLOAD_URL%' -OutFile 'llama_latest.zip' -UseBasicParsing"

if not exist llama_latest.zip (
    echo Error: Failed to download llama.cpp binary.
    echo URL attempted: %DOWNLOAD_URL%
    exit /b 1
)

echo Extracting llama.cpp binaries...
powershell -Command "Expand-Archive -Path 'llama_latest.zip' -DestinationPath 'llama.cpp\build\bin' -Force"
del llama_latest.zip

REM Ensure bin folder exists
if not exist llama.cpp\build\bin (
    echo Error: llama.cpp binary folder not found after extraction.
    exit /b 1
)

echo llama.cpp installed successfully.
echo Binaries located at: llama.cpp\build\bin\llama-completion.exe

echo.
echo Environment setup complete.
echo To activate the virtual environment later, run: venv\Scripts\activate
