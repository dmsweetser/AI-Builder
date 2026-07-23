
@echo off
setlocal enabledelayedexpansion

echo Setting up AI-Builder...

REM -------------------------------
REM Create directories
REM -------------------------------
mkdir aib_instance
mkdir aib_instance\conversations
mkdir aib_instance\llama.cpp\bin
mkdir aib_instance\models

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

REM -------------------------------
REM Model selection and configuration
REM -------------------------------
echo Select a model:
echo 1) Devstral-24B-Instruct-GGUF (Default)
echo 2) Qwen3.6-35B-A3B
echo 3) Ministral 3 - 8B
set /p model_choice="Enter choice: "

set MODEL_PATH=
set MMPROJ_PATH=
set CONTEXT_SIZE=
set OUTPUT_TOKENS=
set TEMPERATURE=
set TOP_P=
set TOP_K=
set MIN_P=

if "%model_choice%"=="2" (
    set MODEL_PATH=aib_instance\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
    if not exist "!MODEL_PATH!" (
        echo Downloading !MODEL_PATH!...
        powershell -Command "Invoke-WebRequest 'https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf?download=true' -OutFile '!MODEL_PATH!'"
    ) else (
        echo !MODEL_PATH! already exists, skipping download.
    )
    set CONTEXT_SIZE=262144
    set OUTPUT_TOKENS=131072
    set TEMPERATURE=0.7
    set TOP_P=0.8
    set TOP_K=20
    set MIN_P=0.0
) else if "%model_choice%"=="3" (
    set MODEL_PATH=aib_instance\models\Ministral-3-8B-Instruct-2512-Q4_K_M.gguf
    if not exist "!MODEL_PATH!" (
        echo Downloading !MODEL_PATH!...
        powershell -Command "Invoke-WebRequest 'https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF/resolve/main/Ministral-3-8B-Instruct-2512-Q4_K_M.gguf?download=true' -OutFile '!MODEL_PATH!'"
    ) else (
        echo !MODEL_PATH! already exists, skipping download.
    )
    set CONTEXT_SIZE=131072
    set OUTPUT_TOKENS=65536
    set TEMPERATURE=0.7
    set TOP_P=0.9
    set TOP_K=40
    set MIN_P=0.00
) else (
    set MODEL_PATH=aib_instance\models\Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf
    if not exist "!MODEL_PATH!" (
        echo Downloading !MODEL_PATH!...
        powershell -Command "Invoke-WebRequest 'https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf?download=true' -OutFile '!MODEL_PATH!'"
    ) else (
        echo !MODEL_PATH! already exists, skipping download.
    )
    set CONTEXT_SIZE=131072
    set OUTPUT_TOKENS=65536
    set TEMPERATURE=0.7
    set TOP_P=0.9
    set TOP_K=40
    set MIN_P=0.05
)

REM Generate .env with selected model hyperparameters
(
echo USE_LOCAL_MODEL=true
echo LLAMA_BINARY_PATH="aib_instance\llama.cpp\bin\llama-completion.exe"
echo MODEL_PATH="!MODEL_PATH!"
echo MODEL_CONTEXT=!CONTEXT_SIZE!
echo OUTPUT_TOKENS=!OUTPUT_TOKENS!
echo TEMPERATURE=!TEMPERATURE!
echo TOP_P=!TOP_P!
echo TOP_K=!TOP_K!
echo MIN_P=!MIN_P!
echo GENERATE_BUT_DO_NOT_APPLY=false
echo GENERATE_OUTPUT_ONLY=false
echo USE_GIT_DIFF=false
) > .env

echo Created default .env
echo Please edit this file with your specific paths and settings

REM Download llama.cpp binary
echo Downloading llama.cpp binary...
if not exist "aib_instance\llama.cpp\bin\llama-completion.exe" (
    echo Downloading latest Windows binary...
    powershell -Command "Invoke-WebRequest 'https://github.com/ggml-org/llama.cpp/releases/download/b8400/llama-b8400-bin-win-cpu-x64.zip' -OutFile 'llama_latest.zip' -UseBasicParsing"
    if %errorlevel% neq 0 (
        echo Error: Failed to download llama.cpp binary.
        exit /b 1
    )
    echo Extracting llama.cpp binary...
    powershell -Command "Expand-Archive -Path 'llama_latest.zip' -DestinationPath 'aib_instance\llama.cpp\bin' -Force"
    del llama_latest.zip
) else (
    echo llama.cpp already exists, skipping download.
)

echo Installation complete
echo To activate the virtual environment later, run: venv\Scripts\activate.bat
