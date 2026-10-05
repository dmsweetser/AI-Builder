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

REM Generate a basic .env template (user must fill in their own values)
(
echo # AI-Builder Configuration
echo SET USE_LOCAL_MODEL=true for local GGUF models via llama.cpp
echo SET USE_CUSTOM_ENDPOINT=true for OpenAI-compatible APIs (Ollama, LM Studio, vLLM, etc.)
echo SET Azure AI credentials (ENDPOINT, MODEL_NAME, API_KEY) for cloud inference
echo.
echo USE_LOCAL_MODEL=false
echo REM MODEL_PATH=path\to\your\model.gguf
echo REM LLAMA_BINARY_PATH=path\to\llama-cli
echo.
echo USE_CUSTOM_ENDPOINT=false
echo REM CUSTOM_ENDPOINT_URL=https://localhost:11434/v1/chat/completions
echo REM CUSTOM_API_KEY=your-api-key
echo REM CUSTOM_MODEL_NAME=llama3
echo.
echo REM Azure AI Settings
echo REM ENDPOINT=https://your-endpoint.ai.azure.com
echo REM MODEL_NAME=your-model-name
echo REM API_KEY=your-api-key
echo.
echo REM Common settings
echo TEMPERATURE=0.1
echo TOP_P=0.9
echo TOP_K=40
echo MIN_P=0.0
echo OUTPUT_TOKENS=8192
echo MODEL_CONTEXT=128000
echo AIB_MAX_STEPS=50
echo GENERATE_BUT_DO_NOT_APPLY=false
echo GENERATE_OUTPUT_ONLY=false
echo USE_GIT_DIFF=false
echo AIB_ENGINE_MODE=agent
) > .env

echo Created .env template - please edit with your settings
echo Installation complete
echo To activate the virtual environment later, run: venv\Scripts\activate.bat
