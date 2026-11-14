#!/usr/bin/env bash
# ============================================================================
# AI-Builder — llama.cpp Server (macOS — Apple Silicon)
# ============================================================================
# Downloads pre-built llama.cpp release, downloads the requested model(s), and
# starts llama-server in the foreground.
#
# GPU: Metal (Apple Silicon — always available)
#
# Usage:
#   ./scripts/llama_server.sh              # interactive menu
#   ./scripts/llama_server.sh qwen35b      # start Qwen3.6-35B-A3B
#   ./scripts/llama_server.sh ministral    # start Ministral-3-14B
#   ./scripts/llama_server.sh devstral     # start Devstral-Small-2-24B
#   ./scripts/llama_server.sh gemma4       # start Gemma-4-26B-A4B-it
#   ./scripts/llama_server.sh all          # download all models (don't start)
# ============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"
LLAMACPP_DIR="$WORKDIR/llama.cpp-bin"
MODEL_BASE_DIR="$WORKDIR/models"

# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------
declare -a MODEL_KEYS=(qwen35b ministral devstral gemma4)

declare -A MODEL_NAMES=(
  [qwen35b]="Qwen3.6-35B-A3B"
  [ministral]="Ministral-3-14B"
  [devstral]="Devstral-Small-2-24B"
  [gemma4]="Gemma-4-26B-A4B"
)

declare -A MODEL_FILES=(
  [qwen35b]="Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
  [ministral]="Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"
  [devstral]="Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf"
  [gemma4]="gemma-4-26B-A4B-it-UD-Q4_K_M.gguf"
)

declare -A MMPROJ_FILES=(
  [qwen35b]="mmproj-F32.gguf"
  [ministral]="mmproj-F16.gguf"
  [devstral]="mmproj-F32.gguf"
  [gemma4]="mmproj-F32.gguf"
)

declare -A MODEL_URLS=(
  [qwen35b]="https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf?download=true"
  [ministral]="https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/Ministral-3-14B-Instruct-2512-Q4_K_M.gguf?download=true"
  [devstral]="https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf?download=true"
  [gemma4]="https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf?download=true"
)

declare -A MMPROJ_URLS=(
  [qwen35b]="https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/mmproj-F32.gguf?download=true"
  [ministral]="https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/mmproj-F16.gguf?download=true"
  [devstral]="https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/mmproj-F32.gguf?download=true"
  [gemma4]="https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/mmproj-F32.gguf?download=true"
)

declare -A MODEL_CONTEXTS=(
  [qwen35b]="262144"
  [ministral]="131072"
  [devstral]="131072"
  [gemma4]="131072"
)

declare -A MODEL_NAMESPACES=(
  [qwen35b]="131072"
  [ministral]="65536"
  [devstral]="65536"
  [gemma4]="65536"
)

declare -A MODEL_PORTS=(
  [qwen35b]="8080"
  [ministral]="8081"
  [devstral]="8082"
  [gemma4]="8083"
)

declare -A MODEL_ALIASES=(
  [qwen35b]="qwen35b"
  [ministral]="ministral"
  [devstral]="devstral"
  [gemma4]="gemma4"
)

declare -A MODEL_GPU_LAYERS=(
  [qwen35b]="999"
  [ministral]="999"
  [devstral]="999"
  [gemma4]="999"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf "\033[1;34m[llama_server]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn] \033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m[error]\033[0m %s\n" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Platform check
# ---------------------------------------------------------------------------
[[ "$(uname -s)" == "Darwin" ]] || die "This script targets macOS (Darwin)."
[[ "$(uname -m)" == "arm64" ]] || die "Apple Silicon (arm64) required."

# ---------------------------------------------------------------------------
# Fetch latest release tag from GitHub
# ---------------------------------------------------------------------------
fetch_latest_tag() {
  local tag
  tag=$(curl -fsSL https://api.github.com/repos/ggml-org/llama.cpp/releases/latest 2>/dev/null \
    | grep '"tag_name"' \
    | sed -E 's/.*"([^"]+)".*/\1/' \
    || true)
  if [[ -z "$tag" ]]; then
    warn "Could not fetch latest release tag from GitHub."
    die "Check your internet connection or specify a tag manually."
  fi
  echo "$tag"
}

# ---------------------------------------------------------------------------
# Download + install pre-built llama.cpp
# ---------------------------------------------------------------------------
install_llamacpp() {
  if [[ -x "$LLAMACPP_DIR/bin/llama-server" ]]; then
    log "llama-server already installed."
    return 0
  fi

  local tag
  tag="$(fetch_latest_tag)"
  log "Downloading llama.cpp pre-built release (tag: $tag)…"

  local archive_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/llama-${tag}-bin-macos-arm64.tar.gz"
  local tmp_dir
  tmp_dir=$(mktemp -d)

  curl -fSL -o "$tmp_dir/llama.tar.gz" "$archive_url" \
    || die "Failed to download llama.cpp pre-built (macOS arm64)."

  mkdir -p "$LLAMACPP_DIR"
  tar -xzf "$tmp_dir/llama.tar.gz" -C "$tmp_dir"

  # Extract the inner directory (e.g. llama-b12377-bin-macos-arm64/)
  local extracted_dir
  extracted_dir=$(find "$tmp_dir" -maxdepth 1 -type d -name "llama-*" | head -1)

  if [[ -z "$extracted_dir" ]]; then
    die "Could not find extracted directory in archive."
  fi

  # Copy everything from the extracted dir into LLAMACPP_DIR
  cp -R "$extracted_dir"/* "$LLAMACPP_DIR/" 2>/dev/null || true

  rm -rf "$tmp_dir"

  if [[ ! -x "$LLAMACPP_DIR/bin/llama-server" ]] && [[ ! -x "$LLAMACPP_DIR/llama-server" ]]; then
    die "llama-server binary not found after extraction."
  fi

  log "llama-server installed (tag: $tag)."
}

# ---------------------------------------------------------------------------
# Download a single model + mmproj
# ---------------------------------------------------------------------------
download_model() {
  local key="$1"
  local model_dir="$MODEL_BASE_DIR/${MODEL_NAMES[$key]}"
  local model_file="${MODEL_FILES[$key]}"
  local mmproj_file="${MMPROJ_FILES[$key]}"
  local model_url="${MODEL_URLS[$key]}"
  local mmproj_url="${MMPROJ_URLS[$key]}"

  mkdir -p "$model_dir"

  if [[ ! -s "$model_dir/$model_file" ]]; then
    log "Downloading ${MODEL_NAMES[$key]} model…"
    curl -fSL -C - -o "$model_dir/$model_file" "$model_url" \
      || die "Model download failed: $model_file"
  else
    log "Model already present: $model_file"
  fi

  if [[ ! -s "$model_dir/$mmproj_file" ]]; then
    log "Downloading ${MODEL_NAMES[$key]} mmproj…"
    curl -fSL -C - -o "$model_dir/$mmproj_file" "$mmproj_url" \
      || die "mmproj download failed: $mmproj_file"
  else
    log "mmproj already present: $mmproj_file"
  fi
}

# ---------------------------------------------------------------------------
# Start llama-server
# ---------------------------------------------------------------------------
start_server() {
  local key="$1"
  local model_dir="$MODEL_BASE_DIR/${MODEL_NAMES[$key]}"
  local model_file="${MODEL_FILES[$key]}"
  local mmproj_file="${MMPROJ_FILES[$key]}"
  local gpu_layers="${MODEL_GPU_LAYERS[$key]}"

  export PATH="$LLAMACPP_DIR/bin:$PATH"

  log "Starting llama-server (${MODEL_NAMES[$key]})…"
  log "  Model: $model_dir/$model_file"
  log "  mmproj: $model_dir/$mmproj_file"
  log "  Port:  ${MODEL_PORTS[$key]}"
  log "  Context: ${MODEL_CONTEXTS[$key]}"
  log "  GPU layers: $gpu_layers"

  llama-server \
    -m "$model_dir/$model_file" \
    --mmproj "$model_dir/$mmproj_file" \
    --alias "${MODEL_ALIASES[$key]}" \
    --flash-attn on \
    -c "${MODEL_CONTEXTS[$key]}" \
    -n "${MODEL_NAMESPACES[$key]}" \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --batch-size 512 \
    --ubatch-size 512 \
    --temp 0.7 \
    --top-p 0.8 \
    --top-k 20 \
    --host 0.0.0.0 \
    --port "${MODEL_PORTS[$key]}" \
    --n-gpu-layers "$gpu_layers"
}

# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------
show_menu() {
  echo ""
  echo "============================================"
  echo "  AI-Builder — llama.cpp Server (macOS)"
  echo "============================================"
  echo ""
  echo "  1) Qwen3.6-35B-A3B       (port 8080, 256K ctx)"
  echo "  2) Ministral-3-14B        (port 8081, 128K ctx)"
  echo "  3) Devstral-Small-2-24B   (port 8082, 128K ctx)"
  echo "  4) Gemma-4-26B-A4B-it     (port 8083, 128K ctx)"
  echo "  5) Download ALL models"
  echo "  0) Exit"
  echo ""
  echo "  Or run: $0 <qwen35b|ministral|devstral|gemma4|all>"
  echo ""
  read -rp "Select model [1-5, 0=exit]: " choice
  case "$choice" in
    1)    echo "qwen35b" ;;
    2)    echo "ministral" ;;
    3)    echo "devstral" ;;
    4)    echo "gemma4" ;;
    5)    echo "all" ;;
    *)    echo "exit" ;;
  esac
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  local selected="${1:-}"

  if [[ -z "$selected" ]]; then
    selected="$(show_menu)"
  fi

  case "$selected" in
    qwen35b|ministral|devstral|gemma4)
      install_llamacpp
      download_model "$selected"
      start_server "$selected"
      ;;
    all)
      install_llamacpp
      for key in "${MODEL_KEYS[@]}"; do
        download_model "$key"
      done
      log "All models downloaded. Use $0 <model> to start a server."
      ;;
    exit|*)
      log "Goodbye."
      exit 0
      ;;
  esac
}

main "$@"
