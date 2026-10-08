#!/bin/bash
# AI-Builder Installation Script (clean - no model/llama.cpp downloads)
# Sets up a virtual environment with all dependencies.
# The app uses a relative ./aib_instance directory for configs,
# model downloads, chat history, etc.

set -e

echo "Setting up AI-Builder..."

# Create directories
mkdir -p aib_instance
mkdir -p aib_instance/conversations
mkdir -p aib_instance/chats

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv
if [ $? -ne 0 ]; then
    echo "Error: Failed to create virtual environment"
    exit 1
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Error: Failed to activate virtual environment"
    exit 1
fi

# Install requirements
pip install --upgrade pip
pip install -r requirements.txt

# Generate a basic .env template (user must fill in their own values)
cat > .env << 'EOF'
# AI-Builder Configuration
# Set USE_LOCAL_MODEL=true for local GGUF models via llama.cpp
# Set USE_CUSTOM_ENDPOINT=true for OpenAI-compatible APIs (Ollama, LM Studio, vLLM, etc.)
# Set Azure AI credentials (ENDPOINT, MODEL_NAME, API_KEY) for cloud inference

USE_LOCAL_MODEL=false
# MODEL_PATH=path/to/your/model.gguf
# LLAMA_BINARY_PATH=path/to/llama-cli

USE_CUSTOM_ENDPOINT=false
# CUSTOM_ENDPOINT_URL=https://localhost:11434/v1/chat/completions
# CUSTOM_API_KEY=your-api-key
# CUSTOM_MODEL_NAME=llama3

# Azure AI Settings
# ENDPOINT=https://your-endpoint.ai.azure.com
# MODEL_NAME=your-model-name
# API_KEY=your-api-key

# Common settings
TEMPERATURE=0.1
TOP_P=0.9
TOP_K=40
MIN_P=0.0
OUTPUT_TOKENS=8192
MODEL_CONTEXT=128000
AIB_MAX_STEPS=50
GENERATE_BUT_DO_NOT_APPLY=false
GENERATE_OUTPUT_ONLY=false
USE_GIT_DIFF=false
AIB_ENGINE_MODE=agent
EOF

echo "Created .env template - please edit with your settings"
echo "Installation complete"

# Make run script executable
chmod +x run.sh
