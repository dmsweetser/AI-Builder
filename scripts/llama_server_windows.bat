@echo off
setlocal enabledelayedexpansion

REM ===========================================================================
REM AI-Builder -- llama.cpp Server (Windows -- CUDA or CPU)
REM ===========================================================================
REM Downloads pre-built llama.cpp release, downloads the requested model(s), and
REM starts llama-server in the foreground.
REM
REM GPU: CUDA (NVIDIA) -- auto-detected via CIM/WMI + CUDA toolkit check
REM CPU: native x86_64 / ARM64 fallback
REM
REM Usage:
REM   llama_server.bat                  :: interactive menu
REM   llama_server.bat ministral        :: start Ministral-3-14B
REM   llama_server.bat devstral         :: start Devstral-Small-2-24B
REM   llama_server.bat gemma4           :: start Gemma-4-26B-A4B-it
REM   llama_server.bat gemma4_small     :: start Gemma-4-E4B-it
REM   llama_server.bat qwen36           :: start Qwen3.6-35B-A3B
REM   llama_server.bat all              :: download all models (don't start)
REM
REM   set MTP=0 before running to disable MTP speculative decoding
REM   (only Gemma 4 and Qwen3.6 ship an MTP draft -- it is on by default for them)
REM ===========================================================================

cd /d "%~dp0" || (
  echo [error]   Could not cd to script directory.
  exit /b 1
)
set "WORKDIR=%CD%"
set "LLAMACPP_DIR=%WORKDIR%\llama.cpp-bin"
set "MODEL_BASE_DIR=%WORKDIR%\models"

REM Pinned llama.cpp release (binaries live on the bNNNNN pre-releases, NOT on
REM /releases/latest, which is a source-only "v1.0.0" release). Bump this to
REM upgrade; asset names verified against b12387.
set "TAG=b12387"

REM Unified port: all models use the same port so client configs need no
REM per-model tweaking. Configurable via LLAMA_SERVER_PORT env var.
set "UNIFIED_PORT=%LLAMA_SERVER_PORT:=%"
if "%UNIFIED_PORT%"=="" set "UNIFIED_PORT=8080"

REM ===========================================================================
REM Model definitions — single variable per attribute, keyed by model name.
REM Access via !VAR!<key> (e.g. !MODEL_FILE!<key>).
REM Keys: ministral, devstral, gemma4, gemma4_small, qwen36
REM ===========================================================================
set "MODEL_KEYS=ministral devstral gemma4 gemma4_small qwen36"

REM --- Model name (display) ---
set "MODEL_NAME<ministral>=Ministral-3-14B"
set "MODEL_NAME<devstral>=Devstral-Small-2-24B"
set "MODEL_NAME<gemma4>=Gemma-4-26B-A4B"
set "MODEL_NAME<gemma4_small>=Gemma-4-E4B-it"
set "MODEL_NAME<qwen36>=Qwen3.6-35B-A3B"

REM --- Model file ---
set "MODEL_FILE<ministral>=Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"
set "MODEL_FILE<devstral>=Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf"
set "MODEL_FILE<gemma4>=gemma-4-26B-A4B-it-UD-Q4_K_M.gguf"
set "MODEL_FILE<gemma4_small>=gemma-4-E4B-it-Q4_K_M.gguf"
set "MODEL_FILE<qwen36>=Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"

REM --- mmproj file ---
set "MODEL_MMFILE<ministral>=mmproj-F16.gguf"
set "MODEL_MMFILE<devstral>=mmproj-F32.gguf"
set "MODEL_MMFILE<gemma4>=mmproj-F32.gguf"
set "MODEL_MMFILE<gemma4_small>=mmproj-F16.gguf"
set "MODEL_MMFILE<qwen36>=mmproj-F32.gguf"

REM --- Model download URL ---
set "MODEL_URL<ministral>=https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/Ministral-3-14B-Instruct-2512-Q4_K_M.gguf?download=true"
set "MODEL_URL<devstral>=https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf?download=true"
set "MODEL_URL<gemma4>=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf?download=true"
set "MODEL_URL<gemma4_small>=https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf?download=true"
set "MODEL_URL<qwen36>=https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf?download=true"

REM --- mmproj download URL ---
set "MODEL_MMURL<ministral>=https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/mmproj-F16.gguf?download=true"
set "MODEL_MMURL<devstral>=https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "MODEL_MMURL<gemma4>=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "MODEL_MMURL<gemma4_small>=https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/mmproj-F16.gguf?download=true"
set "MODEL_MMURL<qwen36>=https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/mmproj-F32.gguf?download=true"

REM --- MTP draft (only gemma4 and qwen36 have one; empty for others) ---
set "MODEL_MTP<ministral>="
set "MODEL_MTP<devstral>="
set "MODEL_MTP<gemma4>=mtp-gemma-4-26B-A4B-it.gguf"
set "MODEL_MTP<gemma4_small>="
set "MODEL_MTP<qwen36>=Qwen3.6-35B-A3B-MTP-draft.gguf"

set "MODEL_MTPURL<ministral>="
set "MODEL_MTPURL<devstral>="
set "MODEL_MTPURL<gemma4>=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/mtp-gemma-4-26B-A4B-it.gguf?download=true"
set "MODEL_MTPURL<gemma4_small>="
set "MODEL_MTPURL<qwen36>=https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/Qwen3.6-35B-A3B-MTP-draft.gguf?download=true"

REM --- Context window ---
set "MODEL_CTX<ministral>=262144"
set "MODEL_CTX<devstral>=262144"
set "MODEL_CTX<gemma4>=262144"
set "MODEL_CTX<gemma4_small>=131072"
set "MODEL_CTX<qwen36>=262144"

REM --- n_predict (-1 = unlimited) ---
set "MODEL_NPREDICT<ministral>=-1"
set "MODEL_NPREDICT<devstral>=-1"
set "MODEL_NPREDICT<gemma4>=-1"
set "MODEL_NPREDICT<gemma4_small>=-1"
set "MODEL_NPREDICT<qwen36>=-1"

REM --- Cache type K ---
set "MODEL_CACHE_K<ministral>=q8_0"
set "MODEL_CACHE_K<devstral>=q8_0"
set "MODEL_CACHE_K<gemma4>=q8_0"
set "MODEL_CACHE_K<gemma4_small>=q4_0"
set "MODEL_CACHE_K<qwen36>=q8_0"

REM --- Cache type V ---
set "MODEL_CACHE_V<ministral>=q8_0"
set "MODEL_CACHE_V<devstral>=q8_0"
set "MODEL_CACHE_V<gemma4>=q8_0"
set "MODEL_CACHE_V<gemma4_small>=q4_0"
set "MODEL_CACHE_V<qwen36>=q8_0"

REM --- Batch size ---
set "MODEL_BATCH<ministral>=512"
set "MODEL_BATCH<devstral>=1024"
set "MODEL_BATCH<gemma4>=1024"
set "MODEL_BATCH<gemma4_small>=256"
set "MODEL_BATCH<qwen36>=512"

REM --- Ubatch size ---
set "MODEL_UBATCH<ministral>=512"
set "MODEL_UBATCH<devstral>=1024"
set "MODEL_UBATCH<gemma4>=1024"
set "MODEL_UBATCH<gemma4_small>=256"
set "MODEL_UBATCH<qwen36>=512"

REM --- Temperature ---
set "MODEL_TEMP<ministral>=0.7"
set "MODEL_TEMP<devstral>=0.7"
set "MODEL_TEMP<gemma4>=0.7"
set "MODEL_TEMP<gemma4_small>=0.7"
set "MODEL_TEMP<qwen36>=0.7"

REM --- Top P ---
set "MODEL_TOP_P<ministral>=0.8"
set "MODEL_TOP_P<devstral>=0.85"
set "MODEL_TOP_P<gemma4>=0.9"
set "MODEL_TOP_P<gemma4_small>=0.8"
set "MODEL_TOP_P<qwen36>=0.9"

REM --- Top K ---
set "MODEL_TOP_K<ministral>=30"
set "MODEL_TOP_K<devstral>=40"
set "MODEL_TOP_K<gemma4>=50"
set "MODEL_TOP_K<gemma4_small>=25"
set "MODEL_TOP_K<qwen36>=50"

REM ===========================================================================
REM Helpers
REM ===========================================================================
REM Lookup helper: get a model attribute by key.
REM Usage: call :get_model_attr <key> <attr> <result_var>
REM   e.g. call :get_model_attr gemma4 MODEL_FILE result  -> sets %result%
REM ===========================================================================
:get_model_attr
  set "_attr=%~2"
  set "_val=%%MODEL_%_attr%%<%~1%%"
  goto :eof

REM TLS bypass: set INSECURE_TLS=1 before running to skip certificate
REM verification (e.g. behind a corporate SSL-inspecting proxy).
set "CURL_TLS_ARGS="
if "%INSECURE_TLS%"=="1" (
  echo [warn]    INSECURE_TLS=1 - certificate verification is DISABLED.
  set "CURL_TLS_ARGS=-k"
)

REM Jump to main
goto :main

REM ===========================================================================
REM GPU detection
REM ===========================================================================
:check_cuda_gpu
  set "GPU_FOUND="
  where wmic >nul 2>&1
  if errorlevel 1 goto :check_gpu_ps
  for /f "tokens=*" %%G in ('wmic path win32_VideoController where "adapterram>0" get name 2^>nul ^| findstr /i /c:"NVIDIA" /c:"RTX" /c:"GTX"') do set "GPU_FOUND=Y"
  goto :check_gpu_done
:check_gpu_ps
  for /f "usebackq delims=" %%G in (`powershell -NoProfile -Command "if ((Get-CimInstance Win32_VideoController).Name -match 'NVIDIA') { 'Y' }" 2^>nul`) do set "GPU_FOUND=Y"
:check_gpu_done
  if defined GPU_FOUND (exit /b 0) else (exit /b 1)

:check_cuda_toolkit
  if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA" (
    dir /b "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA" 2>nul | findstr /i /r "^v1[23]" >nul && exit /b 0
  )
  exit /b 1

:detect_cuda_version
  if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13" (
    echo 13
  ) else if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12" (
    echo 12
  ) else (
    echo 0
  )
  exit /b 0

REM ===========================================================================
REM Prerequisites
REM ===========================================================================
:install_prereqs
  echo [llama_server] Checking prerequisites...
  where git >nul 2>&1 || (
    echo [warn]    git not found. Install from https://git-scm.com/download/win
    echo [error]   Aborting.
    exit /b 1
  )
  where curl >nul 2>&1 || (
    echo [warn]    curl not found. Install from https://curl.se/windows/
    echo [error]   Aborting.
    exit /b 1
  )
  where tar >nul 2>&1 || (
    echo [warn]    tar not found. Zip extraction will need 7-Zip or PowerShell.
  )
  echo [llama_server] Prerequisites ready.
  exit /b 0

REM ===========================================================================
REM Download + extract pre-built llama.cpp
REM ===========================================================================
:install_llamacpp
  if exist "%LLAMACPP_DIR%\llama-server.exe" (
    echo [llama_server] llama-server already installed.
    exit /b 0
  )

  REM Detect GPU and CUDA version.
  set "HAS_CUDA=0"
  set "CUDA_VER=0"
  call :check_cuda_gpu
  if not errorlevel 1 (
    set "HAS_CUDA=1"
    call :check_cuda_toolkit
    if not errorlevel 1 (
      for /f "delims=" %%V in ('call :detect_cuda_version') do set "CUDA_VER=%%V"
    )
  )

  REM Detect architecture.
  set "BIN_ARCH=x64"
  if defined PROCESSOR_ARCHITEW6432 (
    if /i "!PROCESSOR_ARCHITEW6432!"=="ARM64" set "BIN_ARCH=arm64"
  ) else if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "BIN_ARCH=arm64"
  )

  set "ARCHIVE_URL="
  set "CUDART_URL="

  if "!HAS_CUDA!"=="1" (
    if "!BIN_ARCH!"=="arm64" (
      set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-13.5-arm64.zip"
      set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-13.5-arm64.zip"
    ) else if "!CUDA_VER!"=="13" (
      set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-13.5-x64.zip"
      set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-13.5-x64.zip"
    ) else (
      set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-12.4-x64.zip"
      set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-12.4-x64.zip"
    )
    echo [llama_server] CUDA pre-built selected ^(CUDA !CUDA_VER!, !BIN_ARCH!^).
  ) else (
    set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cpu-%BIN_ARCH%.zip"
    echo [llama_server] CPU pre-built selected ^(!BIN_ARCH!^).
  )

  set "TMPDIR=%TEMP%\llama_download"
  rmdir /s /q "%TMPDIR%" >nul 2>&1
  mkdir "%TMPDIR%" >nul 2>&1

  echo [llama_server] Downloading llama.cpp pre-built release (tag: %TAG%)...
  curl -fSL !CURL_TLS_ARGS! -o "%TMPDIR%\llama.zip" "%ARCHIVE_URL%" || (
    echo [error]   Failed to download llama.cpp pre-built.
    rmdir /s /q "%TMPDIR%" >nul 2>&1
    exit /b 1
  )

  if not exist "%LLAMACPP_DIR%" mkdir "%LLAMACPP_DIR%"

  call :extract_zip "%TMPDIR%\llama.zip" "%TMPDIR%" || (
    echo [error]   Failed to extract llama.cpp. Install 7-Zip or use Windows 10+ tar.
    rmdir /s /q "%TMPDIR%" >nul 2>&1
    exit /b 1
  )

  REM Copy binaries to install directory.
  set "COPIED=0"
  for /d %%D in ("%TMPDIR%\llama-*") do (
    if exist "%%D\llama-server.exe" (
      xcopy "%%D\*" "%LLAMACPP_DIR%\" /E /I /Y >nul 2>&1
      set "COPIED=1"
    )
  )
  if "!COPIED!"=="0" if exist "%TMPDIR%\llama-server.exe" (
    xcopy "%TMPDIR%\*" "%LLAMACPP_DIR%\" /E /I /Y >nul 2>&1
    set "COPIED=1"
  )

  REM Download CUDA runtime DLLs if needed.
  if defined CUDART_URL if not "!CUDART_URL!"=="" (
    echo [llama_server] Downloading CUDA runtime libraries...
    curl -fSL !CURL_TLS_ARGS! -o "%TMPDIR%\cudart.zip" "!CUDART_URL!" 2>nul
    if exist "%TMPDIR%\cudart.zip" (
      call :extract_zip "%TMPDIR%\cudart.zip" "%TMPDIR%" >nul 2>&1
      for /d %%D in ("%TMPDIR%\cudart-*") do (
        xcopy "%%D\*.dll" "%LLAMACPP_DIR%\" /Y >nul 2>&1
      )
      if exist "%TMPDIR%\*.dll" xcopy "%TMPDIR%\*.dll" "%LLAMACPP_DIR%\" /Y >nul 2>&1
      echo [llama_server] CUDA runtime libraries installed.
    ) else (
      echo [warn]    CUDA runtime download failed -- server may fail to start.
    )
  )

  rmdir /s /q "%TMPDIR%" >nul 2>&1

  if not exist "%LLAMACPP_DIR%\llama-server.exe" (
    echo [error]   llama-server.exe not found after extraction.
    exit /b 1
  )

  echo [llama_server] llama-server installed (tag: %TAG%, backend: !HAS_CUDA!).
  exit /b 0

:extract_zip
  set "ZIP_PATH=%~1"
  set "ZIP_DEST=%~2"
  where tar >nul 2>&1 && (
    tar -xf "%ZIP_PATH%" -C "%ZIP_DEST%" 2>nul && exit /b 0
  )
  for %%P in ("%ProgramFiles%\PowerShell\7\pwsh.exe" "%ProgramFiles%\PowerShell\PowerShell\7\pwsh.exe" "%ProgramFiles%\PowerShell\6\pwsh.exe") do (
    if exist "%%~P" (
      "%%~P" -NoProfile -Command "Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%ZIP_DEST%' -Force" && exit /b 0
    )
  )
  if exist "%ProgramFiles%\7-Zip\7z.exe" (
    "%ProgramFiles%\7-Zip\7z.exe" x "%ZIP_PATH%" -o"%ZIP_DEST%" -y >nul 2>&1 && exit /b 0
  )
  exit /b 1

REM ===========================================================================
REM Download a model + mmproj (+ the MTP draft, for models that ship one)
REM ===========================================================================
:download_model
  REM Args: model_key, model_dir
  set "_key=%~1"
  set "_mdir=%~2"

  REM Look up all attributes by key using the model tables
  call :get_model_attr !_key! NAME        _name
  call :get_model_attr !_key! FILE        _file
  call :get_model_attr !_key! MMFILE      _mmfile
  call :get_model_attr !_key! URL         _url
  call :get_model_attr !_key! MMURL       _mmurl
  call :get_model_attr !_key! MTP         _mtp
  call :get_model_attr !_key! MTPURL      _mtpurl

  if not exist "%_mdir%" mkdir "%_mdir%"

  set "DL_OK=1"
  if not exist "%_mdir%\%_file%" (
    echo [llama_server] Downloading !_name! model...
    curl -fSL -C - !CURL_TLS_ARGS! -o "%_mdir%\%_file%" "%_url%" || (
      echo [error]   Model download failed: %_file%
      set "DL_OK=0"
    )
  ) else (
    echo [llama_server] Model already present: %_file%
  )

  if not exist "%_mdir%\%_mmfile%" (
    echo [llama_server] Downloading !_name! mmproj...
    curl -fSL -C - !CURL_TLS_ARGS! -o "%_mdir%\%_mmfile%" "%_mmurl%" || (
      echo [error]   mmproj download failed: %_mmfile%
      set "DL_OK=0"
    )
  ) else (
    echo [llama_server] mmproj already present: %_mmfile%
  )

  REM MTP draft (only when this model ships one -- _mtp non-empty).
  if not "%_mtp%"=="" (
    if not exist "%_mdir%\%_mtp%" (
      echo [llama_server] Downloading !_name! MTP draft...
      curl -fSL -C - !CURL_TLS_ARGS! -o "%_mdir%\%_mtp%" "%_mtpurl%" || (
        echo [warn]    MTP draft download failed: %_mtp% - continuing without MTP.
      )
    ) else (
      echo [llama_server] MTP draft already present: %_mtp%
    )
  )

  if "!DL_OK!"=="0" exit /b 1
  exit /b 0

REM ===========================================================================
REM Start llama-server
REM ===========================================================================
:start_server
  REM Args: model_key, model_dir, has_cuda
  set "_key=%~1"
  set "_mdir=%~2"
  set "_has_cuda=%~3"

  REM Look up all attributes by key using the model tables
  call :get_model_attr !_key! NAME        _name
  call :get_model_attr !_key! FILE        _file
  call :get_model_attr !_key! MMFILE      _mmfile
  call :get_model_attr !_key! MTP         _mtp
  call :get_model_attr !_key! MTPURL      _mtpurl
  call :get_model_attr !_key! CTX         _ctx
  call :get_model_attr !_key! NPREDICT    _npredict
  call :get_model_attr !_key! CACHE_K     _cache_k
  call :get_model_attr !_key! CACHE_V     _cache_v
  call :get_model_attr !_key! BATCH       _batch
  call :get_model_attr !_key! UBATCH      _ubatch
  call :get_model_attr !_key! TEMP        _temp
  call :get_model_attr !_key! TOP_P       _top_p
  call :get_model_attr !_key! TOP_K       _top_k

  if exist "%_mdir%\%_file%" goto :ss_have_model
  echo [error]   Model file missing: %_mdir%\%_file%
  exit /b 1
:ss_have_model

  set "PATH=%LLAMACPP_DIR%;%PATH%"

  echo [llama_server] Starting llama-server (!_name!)...
  echo [llama_server]   Model: %_mdir%\%_file%
  echo [llama_server]   Port: %UNIFIED_PORT%
  echo [llama_server]   Context: %_ctx%
  echo [llama_server]   Backend: !HAS_CUDA!

  REM mmproj argument
  set "MM_PROJ_ARG="
  if exist "%_mdir%\%_mmfile%" (
    set "MM_PROJ_ARG=--mmproj "%_mdir%\%_mmfile%""
  ) else (
    echo [llama_server]   mmproj not found -- running text-only.
  )

  REM MTP speculative decoding
  set "MTP_ARG="
  if not "%_mtp%"=="" (
    if "%MTP%" neq "0" (
      if exist "%_mdir%\%_mtp%" (
        set "MTP_ARG=--spec-type draft-mtp --spec-draft-model "%_mdir%\%_mtp%""
        echo [llama_server]   MTP: on (draft-mtp, %_mtp%)
      ) else (
        echo [warn]    MTP draft not present (%_mtp%) - running without MTP.
      )
    ) else (
      echo [llama_server]   MTP: disabled (MTP=0)
    )
  ) else if "%MTP%"=="1" (
    echo [warn]    MTP requested, but this model ships no MTP draft - running without MTP.
  )

  REM GPU offload
  set "GPU_ARG="
  if "!_has_cuda!"=="1" set "GPU_ARG=--n-gpu-layers 999"

  REM -n is n_predict; -1 means unlimited (bounded by context size).
  llama-server ^
    -m "%_mdir%\%_file%" ^
    !MM_PROJ_ARG! ^
    !MTP_ARG! ^
    --alias !_key! ^
    --jinja ^
    --flash-attn on ^
    -c %_ctx% ^
    -n %_npredict% ^
    --cache-type-k %_cache_k% ^
    --cache-type-v %_cache_v% ^
    --batch-size %_batch% ^
    --ubatch-size %_ubatch% ^
    --temp %_temp% ^
    --top-p %_top_p% ^
    --top-k %_top_k% ^
    --host 0.0.0.0 ^
    --port %UNIFIED_PORT% ^
    !GPU_ARG!
  exit /b

REM ===========================================================================
REM Interactive menu
REM ===========================================================================
:show_menu
  echo.
  echo ============================================
  echo   AI-Builder -- llama.cpp Server (Windows)
  echo ============================================
  echo.
  echo   1) Ministral-3-14B       (port 8081, 256K ctx)
  echo   2) Devstral-Small-2-24B  (port 8082, 384K ctx)
  echo   3) Gemma-4-26B-A4B-it    (port 8083, 256K ctx, MTP)
  echo   4) Gemma-4-E4B-it       (port 8084, 128K ctx)
  echo   5) Qwen3.6-35B-A3B      (port 8085, 256K ctx, MTP)
  echo   6) Download ALL models
  echo   0) Exit
  echo.
  set "choice="
  set /p "choice=Select model [1-6, 0=exit]: "
  if "!choice!"=="1" set "selected=ministral"
  if "!choice!"=="2" set "selected=devstral"
  if "!choice!"=="3" set "selected=gemma4"
  if "!choice!"=="4" set "selected=gemma4_small"
  if "!choice!"=="5" set "selected=qwen36"
  if "!choice!"=="6" set "selected=all"
  if "!choice!"=="0" exit /b 0
  if not defined selected (
    echo [llama_server] Invalid choice.
    goto :show_menu
  )
  exit /b 0

REM ===========================================================================
REM Main
REM ===========================================================================
:main
set "selected=%~1"

if "%selected%"=="" (
  call :show_menu
)

REM Resolve selected key and start server
if "!selected!"=="ministral" (
  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  call :download_model "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<ministral>%" || exit /b 1
  call :start_server "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<ministral>%" "!HAS_CUDA!"
) else if "!selected!"=="devstral" (
  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  call :download_model "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<devstral>%" || exit /b 1
  call :start_server "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<devstral>%" "!HAS_CUDA!"
) else if "!selected!"=="gemma4" (
  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  call :download_model "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<gemma4>%" || exit /b 1
  call :start_server "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<gemma4>%" "!HAS_CUDA!"
) else if "!selected!"=="gemma4_small" (
  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  call :download_model "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<gemma4_small>%" || exit /b 1
  call :start_server "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<gemma4_small>%" "!HAS_CUDA!"
) else if "!selected!"=="qwen36" (
  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  call :download_model "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<qwen36>%" || exit /b 1
  call :start_server "!selected!" "%MODEL_BASE_DIR%\%MODEL_NAME<qwen36>%" "!HAS_CUDA!"
) else if "!selected!"=="all" (
  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  for %%K in (%MODEL_KEYS%) do (
    call :download_model "%%K" "%MODEL_BASE_DIR%\%%MODEL_NAME<%%K%%>" || echo [warn] Download failed for %%K
  )
  echo [llama_server] All models downloaded. Use llama_server.bat ^<model^> to start a server.
) else (
  echo [llama_server] Goodbye.
)

exit /b
