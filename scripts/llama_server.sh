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

# ---------------------------------------------------------------------------
# Platform check
# ---------------------------------------------------------------------------
[[ "$(uname -s)" == "Darwin" ]] || die "This script targets macOS (Darwin)."
[[ "$(uname -m)" == "arm64" ]] || die "Apple Silicon (arm64) required."

check_prereqs() {
  command -v curl >/dev/null 2>&1 || die "curl is required (part of macOS by default)."
  command -v tar  >/dev/null 2>&1 || die "tar is required (part of macOS by default)."
}

# Warn if unified memory looks too small for the chosen model/context.
check_memory() {
  local key="$1"
  local ram_gb
  ram_gb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 ))
  local min_gb
  case "$key" in
    qwen35b)  min_gb=32 ;;
    devstral) min_gb=24 ;;
    *)        min_gb=16 ;;
  esac
  if [[ "$ram_gb" -gt 0 ]] && [[ "$ram_gb" -lt "$min_gb" ]]; then
    warn "This Mac reports ${ram_gb} GB unified memory; ${MODEL_NAMES[$key]} at Q4_K_M with a ${MODEL_CONTEXTS[$key]}-token context typically wants >= ${min_gb} GB. Consider a smaller context or quant."
  fi
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

  local archive_url="https://github.com/ggml-org/llama.cpp/releases/download/$tag/llama-${tag}-bin-macos-arm64.tar.gz"
  local tmp_dir
  tmp_dir=$(mktemp -d)

  # Always clean up the temp dir, even on early failure.
  trap 'rm -rf "$tmp_dir"' EXIT

  curl -fSL -o "$tmp_dir/llama.tar.gz" "$archive_url" \
    || die "Failed to download llama.cpp pre-built (macOS arm64)."

  mkdir -p "$LLAMACPP_DIR"
  tar -xzf "$tmp_dir/llama.tar.gz" -C "$tmp_dir"

  # Find the extracted payload. Handles both layouts: an archive that extracts
  # into a "llama-<tag>-bin-macos-arm64/" subdirectory, and one that extracts
  # bin/ etc. directly into the tar root.
  local extracted_dir
  extracted_dir=$(find "$tmp_dir" -maxdepth 1 -type d -name "llama-*" | head -n1 || true)
  if [[ -n "$extracted_dir" && -e "$extracted_dir/bin/llama-server" ]]; then
    cp -a "$extracted_dir/." "$LLAMACPP_DIR/"
  elif [[ -e "$tmp_dir/bin/llama-server" ]]; then
    cp -a "$tmp_dir/." "$LLAMACPP_DIR/"
  else
    die "Could not locate llama-server in the downloaded archive."
  fi

  # Defensive: strip the quarantine attribute if present, so Gatekeeper does
  # not block the downloaded binaries ("cannot be opened because the developer
  # cannot be verified").
  xattr -dr com.apple.quarantine "$LLAMACPP_DIR" 2>/dev/null || true

  rm -rf "$tmp_dir"
  trap - EXIT

  if [[ ! -x "$LLAMACPP_DIR/bin/llama-server" ]] && [[ ! -x "$LLAMACPP_DIR/llama-server" ]]; then
    die "llama-server binary not found after extraction."
  fi

  log "llama-server installed (tag: $tag)."
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
    curl -fSL -C - -o "$model_dir/$model_file" "$model_url" \
      || { warn "Model download failed: $model_file"; return 1; }
  else
    log "Model already present: $model_file"
  fi

  if [[ ! -s "$model_dir/$mmproj_file" ]]; then
    log "Downloading ${MODEL_NAMES[$key]} mmproj…"
    curl -fSL -C - -o "$model_dir/$mmproj_file" "$mmproj_url" \
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

  log "Starting llama-server (${MODEL_NAMES[$key]})…"
  log "  Model: $model_dir/$model_file"
  log "  Port:  ${MODEL_PORTS[$key]}"
  log "  Context: ${MODEL_CONTEXTS[$key]}"
  log "  Backend: Metal"

  local mmproj_args=()
  if [[ -s "$model_dir/$mmproj_file" ]]; then
    mmproj_args=(--mmproj "$model_dir/$mmproj_file")
  else
    log "  mmproj not found — running text-only."
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
    --n-gpu-layers 999
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

  check_prereqs

  if [[ -z "$selected" ]]; then
    selected="$(show_menu)"
  fi

  case "$selected" in
    qwen35b|ministral|devstral|gemma4)
      install_llamacpp
      download_model "$selected" || die "Model download failed — aborting."
      check_memory "$selected"
      start_server "$selected"
      ;;
    all)
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