#!/bin/bash

echo "Setting up Python virtual environment..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python is not installed. Please install Python before running this script."
    exit 1
fi

# Check if virtual environment directory already exists
if [ ! -d "venv" ]; then
    # Create a virtual environment
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Error: Unable to create virtual environment."
        exit 1
    fi
    echo "Virtual environment created successfully."
else
    echo "Virtual environment already exists."
fi

# Activate the virtual environment
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Error: Unable to activate virtual environment."
    exit 1
fi

echo "Virtual environment activated successfully."
echo "Installing required Python packages..."


# Install required Python packages
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Error: Unable to install required Python packages."
    exit 1
fi

echo "Required Python packages installed successfully."
echo "Environment setup complete."
echo "To activate the virtual environment, run: source venv/bin/activate"
