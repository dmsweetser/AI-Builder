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
echo Installing required Python packages...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Error: Unable to install required Python packages.
    exit /b 1
)
echo Required Python packages installed successfully.


REM -------------------------------
REM Install latest llama.cpp binary
REM -------------------------------
echo Downloading latest llama.cpp release...

REM Create folder if missing
if not exist llama.cpp (
    mkdir llama.cpp
)

REM Download latest Windows release zip
powershell -Command ^
    "(Invoke-WebRequest -Uri 'https://api.github.com/repos/ggerganov/llama.cpp/releases/latest').Content |" ^
    "ConvertFrom-Json |" ^
    "Select-Object -ExpandProperty assets |" ^
    "Where-Object { $_.name -match 'windows-x64.zip' } |" ^
    "ForEach-Object { Invoke-WebRequest -Uri $_.browser_download_url -OutFile 'llama_latest.zip' }"

if not exist llama_latest.zip (
    echo Error: Failed to download llama.cpp release.
    exit /b 1
)

echo Extracting llama.cpp...
powershell -Command "Expand-Archive -Path 'llama_latest.zip' -DestinationPath 'llama.cpp' -Force"
del llama_latest.zip

REM Ensure consistent bin path
if not exist llama.cpp\bin (
    echo Error: llama.cpp binary folder not found after extraction.
    exit /b 1
)

echo llama.cpp installed successfully.
echo Binary located at: llama.cpp\bin\llama-cli.exe


echo.
echo Environment setup complete.
echo To activate the virtual environment later, run: venv\Scripts\activate
