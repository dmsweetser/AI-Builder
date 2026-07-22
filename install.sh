
#!/bin/bash
# AI-Builder Installation Script

set -e

echo "Setting up AI-Builder..."

# Create directories
mkdir -p aib_instance
mkdir -p aib_instance/conversations
mkdir -p aib_instance/llama.cpp/bin
mkdir -p aib_instance/models

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

# Model selection and configuration
echo "Select a model:"
echo "1) Devstral-24B-Instruct-GGUF (Default)"
echo "2) Qwen3.6-35B-A3B"
echo "3) Ministral 3 - 8B"
read -p "Enter choice: " model_choice

MODEL_PATH=""
MMPROJ_PATH=""
CONTEXT_SIZE=""
OUTPUT_TOKENS=""
TEMPERATURE=""
TOP_P=""
TOP_K=""
MIN_P=""

if [ "$model_choice" == "2" ]; then
    MODEL_PATH="aib_instance/models/Qwen3.6-35B-A3B-UD-IQ3_S.gguf"
    if [ ! -f "$MODEL_PATH" ]; then
        echo "Downloading $MODEL_PATH..."
        curl -L "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-IQ3_S.gguf?download=true" -o "$MODEL_PATH"
    else
        echo "$MODEL_PATH already exists, skipping download."
    fi
    CONTEXT_SIZE=262144
    OUTPUT_TOKENS=131072
    TEMPERATURE=0.7
    TOP_P=0.8
    TOP_K=20
    MIN_P=0.0
elif [ "$model_choice" == "3" ]; then
    MODEL_PATH="aib_instance/models/Ministral-3-8B-Instruct-2512-Q4_K_M.gguf"
    if [ ! -f "$MODEL_PATH" ]; then
        echo "Downloading $MODEL_PATH..."
        curl -L "https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF/resolve/main/Ministral-3-8B-Instruct-2512-Q4_K_M.gguf?download=true" -o "$MODEL_PATH"
    else
        echo "$MODEL_PATH already exists, skipping download."
    fi
    CONTEXT_SIZE=131072
    OUTPUT_TOKENS=65536
    TEMPERATURE=0.7
    TOP_P=0.9
    TOP_K=40
    MIN_P=0.00
else
    MODEL_PATH="aib_instance/models/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf"
    if [ ! -f "$MODEL_PATH" ]; then
        echo "Downloading $MODEL_PATH..."
        curl -L "https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf?download=true" -o "$MODEL_PATH"
    else
        echo "$MODEL_PATH already exists, skipping download."
    fi
    CONTEXT_SIZE=131072
    OUTPUT_TOKENS=65536
    TEMPERATURE=0.7
    TOP_P=0.9
    TOP_K=40
    MIN_P=0.05
fi

# Generate .env with selected model hyperparameters
cat > .env << EOF
USE_LOCAL_MODEL=true
MODEL_PATH="$MODEL_PATH"
MODEL_CONTEXT=$CONTEXT_SIZE
OUTPUT_TOKENS=$OUTPUT_TOKENS
TEMPERATURE=$TEMPERATURE
TOP_P=$TOP_P
TOP_K=$TOP_K
MIN_P=$MIN_P
GENERATE_BUT_DO_NOT_APPLY=false
GENERATE_OUTPUT_ONLY=false
USE_GIT_DIFF=false
EOF

echo "Created default .env"
echo "Please edit this file with your specific paths and settings"

# Download llama.cpp binary
echo "Downloading llama.cpp binary..."
if [ ! -f "instance/llama.cpp/bin/llama-server" ]; then
    wget -O llama.cpp.tar.gz \
    "https://github.com/ggml-org/llama.cpp/releases/download/b9279/llama-b9279-bin-ubuntu-x64.tar.gz"

    echo "Extracting llama.cpp binary..."
    tar -xzf llama.cpp.tar.gz -C instance/llama.cpp/bin --strip-components=1
    rm llama.cpp.tar.gz
else
    echo "llama.cpp already exists, skipping download."
fi

echo "Installation complete"

# Make run script executable
chmod +x run.sh
