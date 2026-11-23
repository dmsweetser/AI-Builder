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
#   ./scripts/llama_server_linux.sh ministral    # start Ministral-3-14B
#   ./scripts/llama_server_linux.sh devstral     # start Devstral-Small-2-24B
#   ./scripts/llama_server_linux.sh gemma4       # start Gemma-4-26B-A4B-it
#   ./scripts/llama_server_linux.sh gemma4_small # start Gemma-4-E4B-it
#   ./scripts/llama_server_linux.sh qwen36       # start Qwen3.6-35B-A3B
#   ./scripts/llama_server_linux.sh all          # download all models (don't start)
#
#   MTP=0 ./scripts/llama_server_linux.sh gemma4 # start with MTP speculative
#                                                # decoding disabled
# ============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
LLAMACPP_DIR="$WORKDIR/llama.cpp-bin"
MODEL_BASE_DIR="$WORKDIR/models"

# Pinned llama.cpp release (binaries live on the bNNNNN pre-releases, NOT on
# /releases/latest, which is a source-only "v1.0.0" release). Bump this to
# upgrade; asset names verified against b12387.
LLAMACPP_TAG="b12387"

# Unified port: all models use the same port so client configs need no
# per-model tweaking. The server is started/stopped by model key, but all
# traffic flows through a single port.
UNIFIED_PORT="${LLAMA_SERVER_PORT:-8080}"

# ---------------------------------------------------------------------------
# Model keys
# ---------------------------------------------------------------------------
declare -a MODEL_KEYS=(ministral devstral gemma4 gemma4_small qwen36)

# ---------------------------------------------------------------------------
# Model attribute lookup functions
#
# Each function takes a model key and echoes the attribute value.
# Adding a model = add its key to MODEL_KEYS and one line to each lookup.
# ---------------------------------------------------------------------------
model_name() {
  case "$1" in
    ministral) echo "Ministral-3-14B" ;;
    devstral)  echo "Devstral-Small-2-24B" ;;
    gemma4)    echo "Gemma-4-26B-A4B" ;;
    gemma4_small) echo "Gemma-4-E4B-it" ;;
    qwen36)    echo "Qwen3.6-35B-A3B" ;;
  esac
}

model_file() {
  case "$1" in
    ministral) echo "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf" ;;
    devstral)  echo "Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf" ;;
    gemma4)    echo "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf" ;;
    gemma4_small) echo "gemma-4-E4B-it-Q4_K_M.gguf" ;;
    qwen36)    echo "Qwen3.6-35B-A3B-UD-IQ4_XS.gguf" ;;
  esac
}

model_mmproj_file() {
  case "$1" in
    ministral) echo "mmproj-F16.gguf" ;;
    devstral)  echo "mmproj-F32.gguf" ;;
    gemma4)    echo "mmproj-F32.gguf" ;;
    gemma4_small) echo "mmproj-F16.gguf" ;;
    qwen36)    echo "mmproj-F32.gguf" ;;
  esac
}

model_url() {
  case "$1" in
    ministral) echo "https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/Ministral-3-14B-Instruct-2512-Q4_K_M.gguf?download=true" ;;
    devstral)  echo "https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf?download=true" ;;
    gemma4)    echo "https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf?download=true" ;;
    gemma4_small) echo "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf?download=true" ;;
    qwen36)    echo "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf?download=true" ;;
  esac
}

model_mmproj_url() {
  case "$1" in
    ministral) echo "https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/mmproj-F16.gguf?download=true" ;;
    devstral)  echo "https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/mmproj-F32.gguf?download=true" ;;
    gemma4)    echo "https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/mmproj-F32.gguf?download=true" ;;
    gemma4_small) echo "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/mmproj-F16.gguf?download=true" ;;
    qwen36)    echo "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/mmproj-F32.gguf?download=true" ;;
  esac
}

# MTP (multi-token prediction) draft model, for speculative decoding.
# Only models whose publisher ships an MTP draft have an entry.
model_mtp_file() {
  case "$1" in
    gemma4)    echo "mtp-gemma-4-26B-A4B-it.gguf" ;;
    qwen36)    echo "Qwen3.6-35B-A3B-MTP-draft.gguf" ;;
    *)         echo "" ;;
  esac
}

model_mtp_url() {
  case "$1" in
    gemma4)    echo "https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/mtp-gemma-4-26B-A4B-it.gguf?download=true" ;;
    qwen36)    echo "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/Qwen3.6-35B-A3B-MTP-draft.gguf?download=true" ;;
    *)         echo "" ;;
  esac
}

# Context window
model_context() {
  case "$1" in
    ministral) echo "262144" ;;
    devstral)  echo "262144" ;;
    gemma4)    echo "262144" ;;
    gemma4_small) echo "131072" ;;
    qwen36)    echo "262144" ;;
  esac
}

# n_predict: -1 = unlimited (bounded by context size).
model_npredict() {
  case "$1" in
    ministral) echo "-1" ;;
    devstral)  echo "-1" ;;
    gemma4)    echo "-1" ;;
    gemma4_small) echo "-1" ;;
    qwen36)    echo "-1" ;;
  esac
}

model_port() {
  echo "$UNIFIED_PORT"
}

# Per-model hyperparameters
model_cache_type_k() {
  case "$1" in
    ministral) echo "q8_0" ;;
    devstral)  echo "q8_0" ;;
    gemma4)    echo "q8_0" ;;
    gemma4_small) echo "q4_0" ;;
    qwen36)    echo "q8_0" ;;
  esac
}

model_cache_type_v() {
  case "$1" in
    ministral) echo "q8_0" ;;
    devstral)  echo "q8_0" ;;
    gemma4)    echo "q8_0" ;;
    gemma4_small) echo "q4_0" ;;
    qwen36)    echo "q8_0" ;;
  esac
}

model_batch_size() {
  case "$1" in
    ministral) echo "512" ;;
    devstral)  echo "1024" ;;
    gemma4)    echo "1024" ;;
    gemma4_small) echo "256" ;;
    qwen36)    echo "512" ;;
  esac
}

model_ubatch_size() {
  case "$1" in
    ministral) echo "512" ;;
    devstral)  echo "1024" ;;
    gemma4)    echo "1024" ;;
    gemma4_small) echo "256" ;;
    qwen36)    echo "512" ;;
  esac
}

model_temp() {
  case "$1" in
    ministral) echo "0.7" ;;
    devstral)  echo "0.7" ;;
    gemma4)    echo "0.7" ;;
    gemma4_small) echo "0.7" ;;
    qwen36)    echo "0.7" ;;
  esac
}

model_top_p() {
  case "$1" in
    ministral) echo "0.8" ;;
    devstral)  echo "0.85" ;;
    gemma4)    echo "0.9" ;;
    gemma4_small) echo "0.8" ;;
    qwen36)    echo "0.9" ;;
  esac
}

model_top_k() {
  case "$1" in
    ministral) echo "30" ;;
    devstral)  echo "40" ;;
    gemma4)    echo "50" ;;
    gemma4_small) echo "25" ;;
    qwen36)    echo "50" ;;
  esac
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf "\033[1;34m[llama_server]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn] \033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m[error]\033[0m %s\n" "$*" >&2; exit 1; }

backend_label() {
  [[ "$HAS_CUDA_GPU" == true ]] && echo "CUDA" || echo "CPU"
}

# TLS bypass: certificate verification is DISABLED by default.
# Set INSECURE_TLS=0 to re-enable certificate verification.
CURL_EXTRA=()
if [[ "${INSECURE_TLS:-1}" != "0" ]]; then
  log "INSECURE_TLS=1 — certificate verification is DISABLED."
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

detect_cuda_toolkit_version() {
  local cuda_ver=""
  if command -v nvcc >/dev/null 2>&1; then
    cuda_ver=$(nvcc --version 2>&1 | grep -oP 'release \K[0-9]+' | head -n1 || true)
  fi
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
# Prerequisites
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
      archive_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/llama-${tag}-bin-ubuntu-cuda-12.8-x64.tar.gz"
      cudart_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/cudart-llama-${tag}-bin-ubuntu-cuda-12.8-x64.tar.gz"
    fi

    if [[ -z "$archive_url" ]]; then
      warn "No CUDA pre-built found for arch=$arch CUDA=${CUDA_LIB_VERSION:-unknown}. Falling back to CPU."
      HAS_CUDA_GPU=false
    else
      log "CUDA pre-built selected (CUDA ${CUDA_LIB_VERSION:-unknown}, $arch)."
    fi
  fi

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

  local tmp_dir
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "$tmp_dir"' RETURN

  fetch -o "$tmp_dir/llama.tar.gz" "$archive_url" \
    || { die "Failed to download llama.cpp pre-built."; }

  mkdir -p "$LLAMACPP_DIR"
  tar -xzf "$tmp_dir/llama.tar.gz" -C "$tmp_dir"

  local extracted_dir
  extracted_dir=$(find "$tmp_dir" -maxdepth 1 -type d -name "llama-*" | head -n1 || true)
  if [[ -n "$extracted_dir" && -e "$extracted_dir/bin/llama-server" ]]; then
    cp -a "$extracted_dir/." "$LLAMACPP_DIR/"
  elif [[ -e "$tmp_dir/bin/llama-server" ]]; then
    cp -a "$tmp_dir/." "$LLAMACPP_DIR/"
  else
    die "Could not locate llama-server in the downloaded archive."
  fi

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
# Download a single model + mmproj
# ---------------------------------------------------------------------------
download_model() {
  local key="$1"
  local model_dir="$MODEL_BASE_DIR/$(model_name "$key")"
  local model_file="$(model_file "$key")"
  local mmproj_file="$(model_mmproj_file "$key")"
  local model_url="$(model_url "$key")"
  local mmproj_url="$(model_mmproj_url "$key")"

  mkdir -p "$model_dir"

  if [[ ! -s "$model_dir/$model_file" ]]; then
    log "Downloading $(model_name "$key") model…"
    fetch -C - -o "$model_dir/$model_file" "$model_url" \
      || { warn "Model download failed: $model_file"; return 1; }
  else
    log "Model already present: $model_file"
  fi

  if [[ ! -s "$model_dir/$mmproj_file" ]]; then
    log "Downloading $(model_name "$key") mmproj…"
    fetch -C - -o "$model_dir/$mmproj_file" "$mmproj_url" \
      || { warn "mmproj download failed: $mmproj_file"; return 1; }
  else
    log "mmproj already present: $mmproj_file"
  fi

  # MTP draft (only for models that ship one).
  local mtp_file="$(model_mtp_file "$key")"
  if [[ -n "$mtp_file" ]]; then
    if [[ ! -s "$model_dir/$mtp_file" ]]; then
      log "Downloading $(model_name "$key") MTP draft…"
      fetch -C - -o "$model_dir/$mtp_file" "$(model_mtp_url "$key")" \
        || warn "MTP draft download failed: $mtp_file — continuing without MTP."
    else
      log "MTP draft already present: $mtp_file"
    fi
  fi
}

# ---------------------------------------------------------------------------
# Start llama-server
# ---------------------------------------------------------------------------
start_server() {
  local key="$1"
  local model_dir="$MODEL_BASE_DIR/$(model_name "$key")"
  local model_file="$(model_file "$key")"
  local mmproj_file="$(model_mmproj_file "$key")"

  if [[ ! -s "$model_dir/$model_file" ]]; then
    die "Model file missing: $model_dir/$model_file"
  fi

  export PATH="$LLAMACPP_DIR/bin:$LLAMACPP_DIR:$PATH"
  if [[ -d "$LLAMACPP_DIR/lib" ]]; then
    export LD_LIBRARY_PATH="$LLAMACPP_DIR/lib:${LD_LIBRARY_PATH:-}"
  fi

  log "Starting llama-server ($(model_name "$key"))…"
  log "  Model: $model_dir/$model_file"
  log "  Port:  $(model_port "$key")"
  log "  Context: $(model_context "$key")"
  log "  Backend: $(backend_label)"

  local mmproj_args=()
  if [[ -s "$model_dir/$mmproj_file" ]]; then
    mmproj_args=(--mmproj "$model_dir/$mmproj_file")
  else
    log "  mmproj not found — running text-only."
  fi

  # MTP speculative decoding
  local mtp_file="$(model_mtp_file "$key")"
  local mtp_args=()
  if [[ "${MTP:-1}" != "0" && -n "$mtp_file" ]]; then
    if [[ -s "$model_dir/$mtp_file" ]]; then
      mtp_args=(--spec-type draft-mtp --spec-draft-model "$model_dir/$mtp_file")
      log "  MTP: on (draft-mtp, $mtp_file)"
    else
      warn "MTP draft not present ($mtp_file) — running without MTP."
    fi
  elif [[ "${MTP:-}" == "1" && -z "$mtp_file" ]]; then
    warn "MTP requested, but $(model_name "$key") ships no MTP draft — running without MTP."
  fi

  # GPU offload (only for CUDA builds)
  local gpu_args=()
  if [[ "$HAS_CUDA_GPU" == true ]]; then
    gpu_args=(--n-gpu-layers 999)
  fi

  exec llama-server \
    -m "$model_dir/$model_file" \
    "${mmproj_args[@]}" \
    "${mtp_args[@]}" \
    --alias "$key" \
    --jinja \
    --flash-attn on \
    -c "$(model_context "$key")" \
    -n "$(model_npredict "$key")" \
    --cache-type-k "$(model_cache_type_k "$key")" \
    --cache-type-v "$(model_cache_type_v "$key")" \
    --batch-size "$(model_batch_size "$key")" \
    --ubatch-size "$(model_ubatch_size "$key")" \
    --temp "$(model_temp "$key")" \
    --top-p "$(model_top_p "$key")" \
    --top-k "$(model_top_k "$key")" \
    --host 0.0.0.0 \
    --port "$(model_port "$key")" \
    "${gpu_args[@]}"
}

# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------
show_menu() {
  echo "" >&2
  echo "============================================" >&2
  echo "  AI-Builder — llama.cpp Server (Linux)" >&2
  echo "============================================" >&2
  echo "" >&2
  echo "  1) Ministral-3-14B       (port 8081, 256K ctx)" >&2
  echo "  2) Devstral-Small-2-24B  (port 8082, 384K ctx)" >&2
  echo "  3) Gemma-4-26B-A4B-it    (port 8083, 256K ctx, MTP)" >&2
  echo "  4) Gemma-4-E4B-it       (port 8084, 128K ctx)" >&2
  echo "  5) Qwen3.6-35B-A3B      (port 8085, 256K ctx, MTP)" >&2
  echo "  6) Download ALL models" >&2
  echo "  0) Exit" >&2
  echo "" >&2
  echo "  Or run: $0 <ministral|devstral|gemma4|gemma4_small|qwen36|all>" >&2
  echo "" >&2

  local choice
  while true; do
    read -rp "Select model [1-6, 0=exit]: " choice
    case "$choice" in
      1) echo "ministral"; return 0 ;;
      2) echo "devstral"; return 0 ;;
      3) echo "gemma4"; return 0 ;;
      4) echo "gemma4_small"; return 0 ;;
      5) echo "qwen36"; return 0 ;;
      6) echo "all"; return 0 ;;
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
    ministral|devstral|gemma4|gemma4_small|qwen36)
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
