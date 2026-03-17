#!/bin/bash

echo "Setting up environment and installing llama.cpp..."

# --- Check Python ---
if ! command -v python3 &> /dev/null; then
    echo "Error: Python is not installed. Please install Python before running this script."
    exit 1
fi

# --- Virtual environment ---
if [ ! -d "venv" ]; then
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "Error: Unable to create virtual environment."
        exit 1
    fi
    echo "Virtual environment created successfully."
else
    echo "Virtual environment already exists."
fi

source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Error: Unable to activate virtual environment."
    exit 1
fi

echo "Virtual environment activated."

# --- Install Python deps (non-llama) ---
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "Error: Unable to install Python packages."
        exit 1
    fi
    echo "Python packages installed."
fi

echo "Installing llama.cpp with CMake..."

if [ ! -d "llama.cpp" ]; then
    git clone https://github.com/ggerganov/llama.cpp
else
    cd llama.cpp
    git pull
    cd ..
fi

# Build with CMake
cd llama.cpp
mkdir -p build
cd build

cmake ..
cmake --build . --config Release -j$(nproc)

cd ../..
echo "llama.cpp built successfully."

echo "Checking for PowerShell installation..."

if command -v pwsh &> /dev/null; then
    echo "PowerShell (pwsh) already installed."
else
    echo "PowerShell not found. Installing..."

    # Detect OS
    if [ "$(uname)" = "Linux" ]; then
        # Detect distro family
        if [ -f /etc/debian_version ]; then
            echo "Detected Debian/Ubuntu-based system. Installing PowerShell..."

            sudo apt-get update
            sudo apt-get install -y wget apt-transport-https software-properties-common

            wget -q https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb
            sudo dpkg -i packages-microsoft-prod.deb
            rm packages-microsoft-prod.deb

            sudo apt-get update
            sudo apt-get install -y powershell

        elif [ -f /etc/redhat-release ]; then
            echo "Detected RHEL/Fedora-based system. Installing PowerShell..."

            sudo dnf install -y https://packages.microsoft.com/config/rhel/8/packages-microsoft-prod.rpm
            sudo dnf install -y powershell

        else
            echo "Unsupported Linux distribution. Please install PowerShell manually:"
            echo "https://learn.microsoft.com/powershell/scripting/install/installing-powershell"
        fi
    else
        echo "Non-Linux OS detected. Skipping PowerShell installation."
    fi
fi

echo "PowerShell installation check complete."

echo "Setup complete."
echo "To activate the virtual environment later: source venv/bin/activate"
