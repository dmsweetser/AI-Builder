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

echo "Installation complete"

# Make run script executable
chmod +x ./scripts/run.sh
