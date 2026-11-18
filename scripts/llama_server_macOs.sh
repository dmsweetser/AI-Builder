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
#   ./scripts/llama_server.sh ministral    # start Ministral-3-14B
#   ./scripts/llama_server.sh devstral     # start Devstral-Small-2-24B
#   ./scripts/llama_server.sh gemma4       # start Gemma-4-26B-A4B-it
#   ./scripts/llama_server.sh gemma4_small # start Gemma-4-E4B-it
#   ./scripts/llama_server.sh qwen36       # start Qwen3.6-35B-A3B
#   ./scripts/llama_server.sh all          # download all models (don't start)
#
#   MTP=0 ./scripts/llama_server.sh gemma4 # start with MTP speculative
#                                          # decoding disabled
#
# NOTE: this revision runs on the stock macOS /bin/bash 3.2 — no Homebrew
# bash required. bash 3.2 has no associative arrays, so the model tables
# below are `case` lookups instead of `declare -A` maps; behaviour is
# otherwise identical to the bash >= 4 version.
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
MODEL_KEYS="ministral devstral gemma4 gemma4_small qwen36"

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

# TLS bypass: run with INSECURE_TLS=1 to skip certificate verification
CURL_EXTRA=()
if [[ "${INSECURE_TLS:-0}" == "1" ]]; then
  warn "INSECURE_TLS=1 — certificate verification is DISABLED."
  CURL_EXTRA+=(-k)
fi
fetch() { curl -fSL ${CURL_EXTRA[@]+"${CURL_EXTRA[@]}"} "$@"; }

# Resolve a user-supplied model key to a canonical key.
resolve_key() {
  local raw="$1"
  local k
  for k in $MODEL_KEYS; do
    if [[ "$k" == "$raw" ]]; then
      printf '%s' "$k"
      return 0
    fi
  done
  return 1
}

# ---------------------------------------------------------------------------
# Platform check
# ---------------------------------------------------------------------------
[[ "$(uname -s)" == "Darwin" ]] || die "This script targets macOS (Darwin)."
[[ "$(uname -m)" == "arm64" ]] || die "Apple Silicon (arm64) required."

check_prereqs() {
  command -v curl >/dev/null 2>&1 || die "curl is required (part of macOS by default)."
  command -v tar  >/dev/null 2>&1 || die "tar is required (part of macOS by default)."
}

check_memory() {
  local key="$1"
  local ram_gb
  ram_gb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 ))
  local min_gb
  case "$key" in
    ministral) min_gb=32 ;;
    devstral)  min_gb=32 ;;
    gemma4)    min_gb=24 ;;
    gemma4_small) min_gb=24 ;;
    qwen36)    min_gb=32 ;;
    *)         min_gb=16 ;;
  esac
  if [[ "$ram_gb" -gt 0 ]] && [[ "$ram_gb" -lt "$min_gb" ]]; then
    warn "This Mac reports ${ram_gb} GB unified memory; $(model_name "$key") at Q4_K_M with a $(model_context "$key")-token context typically wants >= ${min_gb} GB. Consider a smaller context or quant."
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

  trap 'rm -rf "$tmp_dir"' EXIT

  fetch -o "$tmp_dir/llama.tar.gz" "$archive_url" \
    || { die "Failed to download llama.cpp pre-built (macOS arm64)."; }

  mkdir -p "$LLAMACPP_DIR"
  tar -xzf "$tmp_dir/llama.tar.gz" -C "$tmp_dir"

  local server_path
  server_path=$(find "$tmp_dir" -type f -name "llama-server" | head -n1 || true)
  if [[ -z "$server_path" ]]; then
    die "Could not locate llama-server in the downloaded archive."
  fi
  local payload_dir
  payload_dir="$(dirname "$server_path")"
  if [[ "$(basename "$payload_dir")" == "bin" ]]; then
    payload_dir="$(dirname "$payload_dir")"
  fi
  cp -a "$payload_dir/." "$LLAMACPP_DIR/"

  xattr -dr com.apple.quarantine "$LLAMACPP_DIR" 2>/dev/null || true

  rm -rf "$tmp_dir"
  trap - EXIT

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

  log "Starting llama-server ($(model_name "$key"))…"
  log "  Model: $model_dir/$model_file"
  log "  Port:  $(model_port "$key")"
  log "  Context: $(model_context "$key")"
  log "  Backend: Metal"

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

  exec llama-server \
    -m "$model_dir/$model_file" \
    ${mmproj_args[@]+"${mmproj_args[@]}"} \
    ${mtp_args[@]+"${mtp_args[@]}"} \
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
    --n-gpu-layers 999
}

# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------
show_menu() {
  echo "" >&2
  echo "============================================" >&2
  echo "  AI-Builder — llama.cpp Server (macOS)" >&2
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

  check_prereqs

  if [[ -z "$selected" ]]; then
    selected="$(show_menu)"
  fi

  case "$selected" in
    all)
      install_llamacpp
      local failed=0 key
      for key in $MODEL_KEYS; do
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
      local key
      if key=$(resolve_key "$selected"); then
        install_llamacpp
        download_model "$key" || die "Model download failed — aborting."
        check_memory "$key"
        start_server "$key"
      else
        warn "Unknown model: $selected"
        log "Valid choices: $MODEL_KEYS all"
        exit 1
      fi
      ;;
  esac
}

main "$@"
