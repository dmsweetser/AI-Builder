#!/usr/bin/env bash
# ============================================================================
# AI-Builder — llama.cpp Server (Linux — CUDA or CPU)
# ============================================================================
# Downloads pre-built llama.cpp release, downloads the requested model(s), and
# starts llama-server in the foreground.
#
# GPU: CUDA (NVIDIA) — auto-detected (CUDA 12 or 13)
# CPU: native x86_64 / aarch64 fallback
#
# Usage:
#   ./scripts/llama_server_linux.sh              # interactive menu
#   ./scripts/llama_server_linux.sh qwen35b      # start Qwen3.6-35B-A3B
#   ./scripts/llama_server_linux.sh ministral    # start Ministral-3-14B
#   ./scripts/llama_server_linux.sh devstral     # start Devstral-Small-2-24B
#   ./scripts/llama_server_linux.sh gemma4       # start Gemma-4-26B-A4B-it
#   ./scripts/llama_server_linux.sh all          # download all models (don't start)
# ============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"
LLAMACPP_DIR="$WORKDIR/llama.cpp-bin"
MODEL_BASE_DIR="$WORKDIR/models"

# Pinned llama.cpp release (binaries live on the bNNNNN pre-releases, NOT on
# /releases/latest, which is a source-only "v1.0.0" release). Bump this to
# upgrade; asset names verified against b12387.
LLAMACPP_TAG="b12387"

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

# n_predict: -1 = unlimited (bounded by context size). The previous values
# (131072 / 65536) were passed to `-n`, which is tokens-to-generate, not a
# context window — almost certainly not what was intended.
declare -A MODEL_NPREDICT=(
  [qwen35b]="-1"
  [ministral]="-1"
  [devstral]="-1"
  [gemma4]="-1"
)

declare -A MODEL_PORTS=(
  [qwen35b]="8080"
  [ministral]="8081"
  [devstral]="8082"
  [gemma4]="8083"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf "\033[1;34m[llama_server]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn] \033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m[error]\033[0m %s\n" "$*" >&2; exit 1; }

backend_label() {
  [[ "$HAS_CUDA_GPU" == true ]] && echo "CUDA" || echo "CPU"
}

# TLS bypass: run with INSECURE_TLS=1 to skip certificate verification
# (e.g. behind a corporate SSL-inspecting proxy).
CURL_EXTRA=()
if [[ "${INSECURE_TLS:-0}" == "1" ]]; then
  warn "INSECURE_TLS=1 — certificate verification is DISABLED."
  CURL_EXTRA+=(-k)
fi
fetch() { curl -fSL "${CURL_EXTRA[@]}" "$@"; }

# ---------------------------------------------------------------------------
# Platform check
# ---------------------------------------------------------------------------
[[ "$(uname -s)" == "Linux" ]] || die "This script targets Linux."

# ---------------------------------------------------------------------------
# GPU detection
# ---------------------------------------------------------------------------
HAS_CUDA_GPU=false

detect_cuda_gpu() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    local driver_ver
    if driver_ver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1); then
      HAS_CUDA_GPU=true
      log "NVIDIA GPU detected (driver ${driver_ver:-unknown})."
    else
      log "nvidia-smi present but no GPU responded — treating as CPU-only."
    fi
  fi
}

# Detect CUDA toolkit version on the system (12 or 13); empty if unknown.
detect_cuda_toolkit_version() {
  local cuda_ver=""
  if command -v nvcc >/dev/null 2>&1; then
    cuda_ver=$(nvcc --version 2>&1 | grep -oP 'release \K[0-9]+' | head -n1 || true)
  fi
  # Fallback: check common CUDA paths. Only accept a major version we support.
  if [[ -z "$cuda_ver" ]]; then
    local d v
    for d in /usr/local/cuda-13* /usr/local/cuda-12*; do
      if [[ -d "$d" ]]; then
        v=$(basename "$d" | grep -oP '\d+' | head -n1 || true)
        if [[ -n "$v" ]]; then
          cuda_ver="$v"
          break
        fi
      fi
    done
  fi
  echo "$cuda_ver"
}

# ---------------------------------------------------------------------------
# Prerequisites (curl + tar; git is not used by this script)
# ---------------------------------------------------------------------------
ensure_pkg() {
  local pkg="$1"
  local pm=""
  if command -v apt-get >/dev/null 2>&1; then pm="apt-get"
  elif command -v dnf >/dev/null 2>&1; then pm="dnf"
  elif command -v yum >/dev/null 2>&1; then pm="yum"
  elif command -v pacman >/dev/null 2>&1; then pm="pacman"
  fi

  case "$pm" in
    apt-get)
      if ! dpkg -s "$pkg" >/dev/null 2>&1; then
        log "Installing $pkg via apt…"
        sudo apt-get update -qq && sudo apt-get install -y -qq "$pkg" || warn "Failed to install $pkg via apt."
      fi
      ;;
    dnf)
      if ! rpm -q "$pkg" >/dev/null 2>&1; then
        log "Installing $pkg via dnf…"
        sudo dnf install -y "$pkg" || warn "Failed to install $pkg via dnf."
      fi
      ;;
    yum)
      if ! rpm -q "$pkg" >/dev/null 2>&1; then
        log "Installing $pkg via yum…"
        sudo yum install -y "$pkg" || warn "Failed to install $pkg via yum."
      fi
      ;;
    pacman)
      if ! pacman -Qi "$pkg" >/dev/null 2>&1; then
        log "Installing $pkg via pacman…"
        sudo pacman -Sy --noconfirm "$pkg" || warn "Failed to install $pkg via pacman."
      fi
      ;;
    *)
      warn "Unknown package manager — please install $pkg manually."
      ;;
  esac
}

install_prereqs() {
  log "Checking prerequisites…"
  command -v curl >/dev/null 2>&1 || ensure_pkg curl
  command -v tar  >/dev/null 2>&1 || ensure_pkg tar
  # Fresh CA certificates — stale/missing trust stores are the most common
  # cause of curl certificate errors on minimal installs.
  command -v curl >/dev/null 2>&1 || die "curl is required but not installed."
  command -v tar  >/dev/null 2>&1 || die "tar is required but not installed."
  log "Prerequisites ready."
}

# ---------------------------------------------------------------------------
# Download + install pre-built llama.cpp
# ---------------------------------------------------------------------------
install_llamacpp() {
  if [[ -x "$LLAMACPP_DIR/bin/llama-server" ]] || [[ -x "$LLAMACPP_DIR/llama-server" ]]; then
    log "llama-server already installed."
    return 0
  fi

  local tag="$LLAMACPP_TAG"
  log "Downloading llama.cpp pre-built release (tag: $tag)…"

  # Choose the right pre-built binary
  local arch
  arch=$(uname -m)
  local archive_url=""
  local cudart_url=""

  if [[ "$HAS_CUDA_GPU" == true ]]; then
    CUDA_LIB_VERSION="$(detect_cuda_toolkit_version)"

    if [[ "$CUDA_LIB_VERSION" == "13" ]]; then
      if [[ "$arch" == "x86_64" ]]; then
        archive_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/llama-${tag}-bin-ubuntu-cuda-13.5-x64.tar.gz"
        cudart_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/cudart-llama-${tag}-bin-ubuntu-cuda-13.5-x64.tar.gz"
      elif [[ "$arch" == "aarch64" ]]; then
        archive_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/llama-${tag}-bin-ubuntu-cuda-13.5-arm64.tar.gz"
        cudart_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/cudart-llama-${tag}-bin-ubuntu-cuda-13.5-arm64.tar.gz"
      fi
    elif [[ "$arch" == "x86_64" ]]; then
      # CUDA 12 or undetectable toolkit on x86_64 — try CUDA 12 (works with newer drivers too).
      archive_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/llama-${tag}-bin-ubuntu-cuda-12.8-x64.tar.gz"
      cudart_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/cudart-llama-${tag}-bin-ubuntu-cuda-12.8-x64.tar.gz"
    fi
    # NOTE: no CUDA 12 arm64 build is published — aarch64 only ships CUDA 13.5,
    # which requires a driver new enough for CUDA 13. On arm64 with an older
    # (CUDA 12) driver we fall back to CPU below.

    if [[ -z "$archive_url" ]]; then
      warn "No CUDA pre-built found for arch=$arch CUDA=${CUDA_LIB_VERSION:-unknown}. Falling back to CPU."
      HAS_CUDA_GPU=false
    else
      log "CUDA pre-built selected (CUDA ${CUDA_LIB_VERSION:-unknown}, $arch)."
    fi
  fi

  # CPU fallback
  if [[ "$HAS_CUDA_GPU" == false ]] && [[ -z "$archive_url" ]]; then
    if [[ "$arch" == "x86_64" ]]; then
      archive_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/llama-${tag}-bin-ubuntu-x64.tar.gz"
    elif [[ "$arch" == "aarch64" ]]; then
      archive_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/llama-${tag}-bin-ubuntu-arm64.tar.gz"
    else
      die "Unsupported architecture: $arch"
    fi
    log "CPU pre-built selected for $arch."
  fi

  log "Downloading llama.cpp pre-built release (tag: $tag)…"

  local tmp_dir
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "$tmp_dir"' RETURN

  fetch -o "$tmp_dir/llama.tar.gz" "$archive_url" \
    || { die "Failed to download llama.cpp pre-built."; }

  mkdir -p "$LLAMACPP_DIR"
  tar -xzf "$tmp_dir/llama.tar.gz" -C "$tmp_dir"

  # Find the extracted payload. Handles both layouts: an archive that extracts
  # into a "llama-<tag>-bin-..." subdirectory, and one that extracts bin/ etc.
  # directly into the tar root.
  local extracted_dir
  extracted_dir=$(find "$tmp_dir" -maxdepth 1 -type d -name "llama-*" | head -n1 || true)
  if [[ -n "$extracted_dir" && -e "$extracted_dir/bin/llama-server" ]]; then
    cp -a "$extracted_dir/." "$LLAMACPP_DIR/"
  elif [[ -e "$tmp_dir/bin/llama-server" ]]; then
    cp -a "$tmp_dir/." "$LLAMACPP_DIR/"
  else
    die "Could not locate llama-server in the downloaded archive."
  fi

  # Download and extract CUDA runtime libraries if needed
  if [[ -n "$cudart_url" ]]; then
    log "Downloading CUDA runtime libraries…"
    if fetch -o "$tmp_dir/cudart.tar.gz" "$cudart_url"; then
      tar -xzf "$tmp_dir/cudart.tar.gz" -C "$tmp_dir"
      local cudart_dir
      cudart_dir=$(find "$tmp_dir" -maxdepth 1 -type d -name "cudart-*" | head -n1 || true)
      mkdir -p "$LLAMACPP_DIR/lib"
      if [[ -n "$cudart_dir" ]]; then
        cp -a "$cudart_dir"/. "$LLAMACPP_DIR/lib/" 2>/dev/null || true
      elif compgen -G "$tmp_dir/*.so*" >/dev/null; then
        cp -a "$tmp_dir"/*.so* "$LLAMACPP_DIR/lib/" 2>/dev/null || true
      fi
      log "CUDA runtime libraries installed."
    else
      warn "Failed to download CUDA runtime libraries (non-fatal) — server may fail to start."
    fi
  fi

  rm -rf "$tmp_dir"
  trap - RETURN

  if [[ ! -x "$LLAMACPP_DIR/bin/llama-server" ]] && [[ ! -x "$LLAMACPP_DIR/llama-server" ]]; then
    die "llama-server binary not found after extraction."
  fi

  log "llama-server installed (tag: $tag, backend: $(backend_label))."
}

# ---------------------------------------------------------------------------
# Download a single model + mmproj (returns non-zero on failure instead of
# killing the whole run, so `all` can skip past a broken download)
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
    fetch -C - -o "$model_dir/$model_file" "$model_url" \
      || { warn "Model download failed: $model_file"; return 1; }
  else
    log "Model already present: $model_file"
  fi

  if [[ ! -s "$model_dir/$mmproj_file" ]]; then
    log "Downloading ${MODEL_NAMES[$key]} mmproj…"
    fetch -C - -o "$model_dir/$mmproj_file" "$mmproj_url" \
      || { warn "mmproj download failed: $mmproj_file"; return 1; }
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

  if [[ ! -s "$model_dir/$model_file" ]]; then
    die "Model file missing: $model_dir/$model_file"
  fi

  export PATH="$LLAMACPP_DIR/bin:$LLAMACPP_DIR:$PATH"
  # Add CUDA libs to LD_LIBRARY_PATH if present (guard against unset under set -u)
  if [[ -d "$LLAMACPP_DIR/lib" ]]; then
    export LD_LIBRARY_PATH="$LLAMACPP_DIR/lib:${LD_LIBRARY_PATH:-}"
  fi

  log "Starting llama-server (${MODEL_NAMES[$key]})…"
  log "  Model: $model_dir/$model_file"
  log "  Port:  ${MODEL_PORTS[$key]}"
  log "  Context: ${MODEL_CONTEXTS[$key]}"
  log "  Backend: $(backend_label)"

  local mmproj_args=()
  if [[ -s "$model_dir/$mmproj_file" ]]; then
    mmproj_args=(--mmproj "$model_dir/$mmproj_file")
  else
    log "  mmproj not found — running text-only."
  fi

  # Only offload layers when a CUDA build was selected; the CPU build ignores
  # the flag but it makes the intent explicit to pass it conditionally.
  local gpu_args=()
  if [[ "$HAS_CUDA_GPU" == true ]]; then
    gpu_args=(--n-gpu-layers 999)
  fi

  # -n is n_predict; -1 means unlimited (bounded by context size).
  exec llama-server \
    -m "$model_dir/$model_file" \
    "${mmproj_args[@]}" \
    --alias "$key" \
    --jinja \
    --flash-attn on \
    -c "${MODEL_CONTEXTS[$key]}" \
    -n "${MODEL_NPREDICT[$key]}" \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    --batch-size 512 \
    --ubatch-size 512 \
    --temp 0.7 \
    --top-p 0.8 \
    --top-k 20 \
    --host 0.0.0.0 \
    --port "${MODEL_PORTS[$key]}" \
    "${gpu_args[@]}"
}

# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------
show_menu() {
  echo ""
  echo "============================================"
  echo "  AI-Builder — llama.cpp Server (Linux)"
  echo "  Backend: $(backend_label)"
  echo "============================================"
  echo ""
  echo "  1) Qwen3.6-35B-A3B       (port 8080, 256K ctx)"
  echo "  2) Ministral-3-14B       (port 8081, 128K ctx)"
  echo "  3) Devstral-Small-2-24B  (port 8082, 128K ctx)"
  echo "  4) Gemma-4-26B-A4B-it    (port 8083, 128K ctx)"
  echo "  5) Download ALL models"
  echo "  0) Exit"
  echo ""
  echo "  Or run: $0 <qwen35b|ministral|devstral|gemma4|all>"
  echo ""

  local choice
  while true; do
    read -rp "Select model [1-5, 0=exit]: " choice
    case "$choice" in
      1) echo "qwen35b"; return 0 ;;
      2) echo "ministral"; return 0 ;;
      3) echo "devstral"; return 0 ;;
      4) echo "gemma4"; return 0 ;;
      5) echo "all"; return 0 ;;
      0) echo "exit"; return 0 ;;
      *) warn "Invalid choice." ;;
    esac
  done
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  local selected="${1:-}"

  detect_cuda_gpu

  if [[ -z "$selected" ]]; then
    selected="$(show_menu)"
  fi

  case "$selected" in
    qwen35b|ministral|devstral|gemma4)
      install_prereqs
      install_llamacpp
      download_model "$selected" || die "Model download failed — aborting."
      start_server "$selected"
      ;;
    all)
      install_prereqs
      install_llamacpp
      local failed=0 key
      for key in "${MODEL_KEYS[@]}"; do
        download_model "$key" || failed=$((failed + 1))
      done
      if [[ "$failed" -gt 0 ]]; then
        warn "$failed model download(s) failed."
      fi
      log "All models downloaded. Use $0 <model> to start a server."
      [[ "$failed" -eq 0 ]] || exit 1
      ;;
    exit)
      log "Goodbye."
      exit 0
      ;;
    *)
      warn "Unknown model: $selected"
      log "Valid choices: ${MODEL_KEYS[*]} all"
      exit 1
      ;;
  esac
}

main "$@"