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
REM Clone or update llama.cpp
REM -------------------------------
echo Checking llama.cpp source...

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
REM Build llama.cpp with CMake
REM -------------------------------
echo Building llama.cpp...

pushd llama.cpp

if not exist build (
    mkdir build
)

pushd build

cmake .. -A x64
if %errorlevel% neq 0 (
    echo Error: CMake configuration failed.
    exit /b 1
)

cmake --build . --config Release
if %errorlevel% neq 0 (
    echo Error: Build failed.
    exit /b 1
)

popd
popd

echo llama.cpp built successfully.
echo Binary should be located at: llama.cpp\build\bin\Release\llama-cli.exe

echo.
echo Environment setup complete.
echo To activate the virtual environment later, run: venv\Scripts\activate
