@echo off
setlocal enabledelayedexpansion

REM ===========================================================================
REM AI-Builder — llama.cpp Server (Windows — CUDA or CPU)
REM ===========================================================================
REM Downloads pre-built llama.cpp release, downloads the requested model(s), and
REM starts llama-server in the foreground.
REM
REM GPU: CUDA (NVIDIA) — auto-detected via CIM/WMI + CUDA toolkit check
REM CPU: native x86_64 / ARM64 fallback
REM
REM Usage:
REM   llama_server.bat                  :: interactive menu
REM   llama_server.bat qwen35b          :: start Qwen3.6-35B-A3B
REM   llama_server.bat ministral        :: start Ministral-3-14B
REM   llama_server.bat devstral         :: start Devstral-Small-2-24B
REM   llama_server.bat gemma4           :: start Gemma-4-26B-A4B-it
REM   llama_server.bat all              :: download all models (don't start)
REM ===========================================================================

cd /d "%~dp0.." || (
  echo [error]   Could not cd to script parent directory.
  exit /b 1
)
set "WORKDIR=%CD%"
set "LLAMACPP_DIR=%WORKDIR%\llama.cpp-bin"
set "MODEL_BASE_DIR=%WORKDIR%\models"

REM Pinned llama.cpp release (binaries live on the bNNNNN pre-releases, NOT on
REM /releases/latest, which is a source-only "v1.0.0" release). Bump this to
REM upgrade; asset names verified against b12387.
set "TAG=b12387"

REM ---------------------------------------------------------------------------
REM Model definitions
REM ---------------------------------------------------------------------------
set "QWEN_NAME=Qwen3.6-35B-A3B"
set "QWEN_FILE=Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
set "QWEN_MMPROJ=mmproj-F32.gguf"
set "QWEN_URL=https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf?download=true"
set "QWEN_MMURL=https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "QWEN_CTX=262144"
set "QWEN_NPREDICT=-1"
set "QWEN_PORT=8080"

set "MIN_NAME=Ministral-3-14B"
set "MIN_FILE=Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"
set "MIN_MMPROJ=mmproj-F16.gguf"
set "MIN_URL=https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/Ministral-3-14B-Instruct-2512-Q4_K_M.gguf?download=true"
set "MIN_MMURL=https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/mmproj-F16.gguf?download=true"
set "MIN_CTX=131072"
set "MIN_NPREDICT=-1"
set "MIN_PORT=8081"

set "DEV_NAME=Devstral-Small-2-24B"
set "DEV_FILE=Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf"
set "DEV_MMPROJ=mmproj-F32.gguf"
set "DEV_URL=https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf?download=true"
set "DEV_MMURL=https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "DEV_CTX=131072"
set "DEV_NPREDICT=-1"
set "DEV_PORT=8082"

set "GEMMA_NAME=Gemma-4-26B-A4B"
set "GEMMA_FILE=gemma-4-26B-A4B-it-UD-Q4_K_M.gguf"
set "GEMMA_MMPROJ=mmproj-F32.gguf"
set "GEMMA_URL=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf?download=true"
set "GEMMA_MMURL=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "GEMMA_CTX=131072"
set "GEMMA_NPREDICT=-1"
set "GEMMA_PORT=8083"

REM ---------------------------------------------------------------------------
REM Jump to main — without this, execution falls through every label below and
REM runs detection / install / download / start-server with empty arguments.
REM ---------------------------------------------------------------------------
goto :main

REM ---------------------------------------------------------------------------
REM GPU detection
REM ---------------------------------------------------------------------------
:check_cuda_gpu
  REM WMIC is removed on Windows 11 24H2+; fall back to PowerShell CIM.
  set "GPU_FOUND="
  where wmic >nul 2>&1 && (
    for /f "tokens=*" %%G in ('wmic path win32_VideoController where "adapterram>0" get name 2^>nul ^| findstr /i /c:"NVIDIA" /c:"RTX" /c:"GTX"') do set "GPU_FOUND=Y"
  ) || (
    for /f "usebackq delims=" %%G in (`powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA|RTX|GTX' }).Name" 2^>nul`) do (
      if not "%%G"=="" set "GPU_FOUND=Y"
    )
  )
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

REM ---------------------------------------------------------------------------
REM Prerequisites
REM ---------------------------------------------------------------------------
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

REM ---------------------------------------------------------------------------
REM Download + extract pre-built llama.cpp
REM ---------------------------------------------------------------------------
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
      REM No CUDA 12 arm64 build is published - aarch64 only ships CUDA 13.5,
      REM which requires a driver new enough for CUDA 13.
      set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-13.5-arm64.zip"
      set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-13.5-arm64.zip"
    ) else if "!CUDA_VER!"=="13" (
      set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-13.5-x64.zip"
      set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-13.5-x64.zip"
    ) else (
      REM CUDA 12 or undetectable toolkit on x64 - try CUDA 12.
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
  curl -fSL -o "%TMPDIR%\llama.zip" "%ARCHIVE_URL%" || (
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

  REM Copy binaries to install directory. Handles both layouts: an archive that
  REM extracts into a "llama-<tag>-bin-..." subdirectory, and one that extracts
  REM files directly into the temp directory.
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

  REM Download CUDA runtime DLLs if needed. The cudart archive extracts DLLs at
  REM its root, so also handle the no-subdirectory case.
  if defined CUDART_URL if not "!CUDART_URL!"=="" (
    echo [llama_server] Downloading CUDA runtime libraries...
    curl -fSL -o "%TMPDIR%\cudart.zip" "!CUDART_URL!" 2>nul
    if exist "%TMPDIR%\cudart.zip" (
      call :extract_zip "%TMPDIR%\cudart.zip" "%TMPDIR%" >nul 2>&1
      for /d %%D in ("%TMPDIR%\cudart-*") do (
        xcopy "%%D\*.dll" "%LLAMACPP_DIR%\" /Y >nul 2>&1
      )
      if exist "%TMPDIR%\*.dll" xcopy "%TMPDIR%\*.dll" "%LLAMACPP_DIR%\" /Y >nul 2>&1
      echo [llama_server] CUDA runtime libraries installed.
    ) else (
      echo [warn]    CUDA runtime download failed — server may fail to start.
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
  REM Args: zip_path, dest_dir. Tries tar (Windows 10+), then pwsh, then 7-Zip.
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

REM ---------------------------------------------------------------------------
REM Download a model + mmproj
REM ---------------------------------------------------------------------------
:download_model
  REM Args: display_name, model_dir, model_file, mmproj_file, model_url, mmproj_url
  set "display_name=%~1"
  set "model_dir=%~2"
  set "model_file=%~3"
  set "mmproj_file=%~4"
  set "model_url=%~5"
  set "mmproj_url=%~6"

  if not exist "%model_dir%" mkdir "%model_dir%"

  set "DL_OK=1"
  if not exist "%model_dir%\%model_file%" (
    echo [llama_server] Downloading %display_name% model...
    curl -fSL -C - -o "%model_dir%\%model_file%" "%model_url%" || (
      echo [error]   Model download failed: %model_file%
      set "DL_OK=0"
    )
  ) else (
    echo [llama_server] Model already present: %model_file%
  )

  if not exist "%model_dir%\%mmproj_file%" (
    echo [llama_server] Downloading %display_name% mmproj...
    curl -fSL -C - -o "%model_dir%\%mmproj_file%" "%mmproj_url%" || (
      echo [error]   mmproj download failed: %mmproj_file%
      set "DL_OK=0"
    )
  ) else (
    echo [llama_server] mmproj already present: %mmproj_file%
  )

  if "!DL_OK!"=="0" exit /b 1
  exit /b 0

REM ---------------------------------------------------------------------------
REM Start llama-server
REM ---------------------------------------------------------------------------
:start_server
  REM Args: alias, model_dir, model_file, mmproj_file, ctx, n_predict, port, has_cuda
  set "alias=%~1"
  set "model_dir=%~2"
  set "model_file=%~3"
  set "mmproj_file=%~4"
  set "ctx=%~5"
  set "npredict=%~6"
  set "port=%~7"
  set "has_cuda=%~8"

  if not exist "%model_dir%\%model_file%" (
    echo [error]   Model file missing: %model_dir%\%model_file%
    exit /b 1
  )

  set "PATH=%LLAMACPP_DIR%;%PATH%"

  echo [llama_server] Starting llama-server (%alias%)...
  echo [llama_server]   Model: %model_dir%\%model_file%
  echo [llama_server]   Port: %port%

  set "MM_PROJ_ARG="
  if exist "%model_dir%\%mmproj_file%" (
    set "MM_PROJ_ARG=--mmproj "%model_dir%\%mmproj_file%""
  ) else (
    echo [llama_server]   mmproj not found — running text-only.
  )

  set "GPU_ARG="
  if "!has_cuda!"=="1" set "GPU_ARG=--n-gpu-layers 999"

  REM -n is n_predict; -1 means unlimited (bounded by context size).
  llama-server ^
    -m "%model_dir%\%model_file%" ^
    !MM_PROJ_ARG! ^
    --alias %alias% ^
    --jinja ^
    --flash-attn on ^
    -c %ctx% ^
    -n %npredict% ^
    --cache-type-k q8_0 ^
    --cache-type-v q8_0 ^
    --batch-size 512 ^
    --ubatch-size 512 ^
    --temp 0.7 ^
    --top-p 0.8 ^
    --top-k 20 ^
    --host 0.0.0.0 ^
    --port %port% ^
    !GPU_ARG!
  exit /b

REM ---------------------------------------------------------------------------
REM Interactive menu — sets SELECTED directly. (Capturing the menu's output via
REM `for /f` broke because `set /p` cannot read user input inside a for-f
REM child cmd.)
REM ---------------------------------------------------------------------------
:show_menu
  echo.
  echo ============================================
  echo   AI-Builder -- llama.cpp Server (Windows)
  echo ============================================
  echo.
  echo   1) Qwen3.6-35B-A3B       (port 8080, 256K ctx)
  echo   2) Ministral-3-14B       (port 8081, 128K ctx)
  echo   3) Devstral-Small-2-24B  (port 8082, 128K ctx)
  echo   4) Gemma-4-26B-A4B-it    (port 8083, 128K ctx)
  echo   5) Download ALL models
  echo   0) Exit
  echo.
  set "selected="
  set /p "choice=Select model [1-5, 0=exit]: "
  if "!choice!"=="1" set "selected=qwen35b"
  if "!choice!"=="2" set "selected=ministral"
  if "!choice!"=="3" set "selected=devstral"
  if "!choice!"=="4" set "selected=gemma4"
  if "!choice!"=="5" set "selected=all"
  if "!choice!"=="0" exit /b 0
  if not defined selected (
    echo [llama_server] Invalid choice.
    goto :show_menu
  )
  exit /b 0

REM ---------------------------------------------------------------------------
REM Per-model driver: install, download, start
REM ---------------------------------------------------------------------------
:do_model
  REM Args: name, model_file, mmproj_file, model_url, mmproj_url, ctx, n_predict, port, key
  set "name=%~1"
  set "mfile=%~2"
  set "mmpfile=%~3"
  set "murl=%~4"
  set "mmurl=%~5"
  set "ctx=%~6"
  set "npredict=%~7"
  set "port=%~8"
  set "key=%~9"
  set "model_dir=%MODEL_BASE_DIR%\%name%"

  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  call :download_model "%name%" "%model_dir%" "%mfile%" "%mmpfile%" "%murl%" "%mmurl%" || exit /b 1
  call :start_server "%key%" "%model_dir%" "%mfile%" "%mmpfile%" "%ctx%" "%npredict%" "%port%" "!HAS_CUDA!"
exit /b

:do_all
  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  call :download_model "%QWEN_NAME%" "%MODEL_BASE_DIR%\%QWEN_NAME%" "%QWEN_FILE%" "%QWEN_MMPROJ%" "%QWEN_URL%" "%QWEN_MMURL%" || exit /b 1
  call :download_model "%MIN_NAME%" "%MODEL_BASE_DIR%\%MIN_NAME%" "%MIN_FILE%" "%MIN_MMPROJ%" "%MIN_URL%" "%MIN_MMURL%" || exit /b 1
  call :download_model "%DEV_NAME%" "%MODEL_BASE_DIR%\%DEV_NAME%" "%DEV_FILE%" "%DEV_MMPROJ%" "%DEV_URL%" "%DEV_MMURL%" || exit /b 1
  call :download_model "%GEMMA_NAME%" "%MODEL_BASE_DIR%\%GEMMA_NAME%" "%GEMMA_FILE%" "%GEMMA_MMPROJ%" "%GEMMA_URL%" "%GEMMA_MMURL%" || exit /b 1
  echo [llama_server] All models downloaded. Use llama_server.bat ^<model^> to start a server.
exit /b

REM ---------------------------------------------------------------------------
REM Main
REM ---------------------------------------------------------------------------
:main
set "selected=%~1"

if "%selected%"=="" (
  call :show_menu
)

if "!selected!"=="qwen35b" (
  call :do_model "%QWEN_NAME%" "%QWEN_FILE%" "%QWEN_MMPROJ%" "%QWEN_URL%" "%QWEN_MMURL%" "%QWEN_CTX%" "%QWEN_NPREDICT%" "%QWEN_PORT%" qwen35b
) else if "!selected!"=="ministral" (
  call :do_model "%MIN_NAME%" "%MIN_FILE%" "%MIN_MMPROJ%" "%MIN_URL%" "%MIN_MMURL%" "%MIN_CTX%" "%MIN_NPREDICT%" "%MIN_PORT%" ministral
) else if "!selected!"=="devstral" (
  call :do_model "%DEV_NAME%" "%DEV_FILE%" "%DEV_MMPROJ%" "%DEV_URL%" "%DEV_MMURL%" "%DEV_CTX%" "%DEV_NPREDICT%" "%DEV_PORT%" devstral
) else if "!selected!"=="gemma4" (
  call :do_model "%GEMMA_NAME%" "%GEMMA_FILE%" "%GEMMA_MMPROJ%" "%GEMMA_URL%" "%GEMMA_MMURL%" "%GEMMA_CTX%" "%GEMMA_NPREDICT%" "%GEMMA_PORT%" gemma4
) else if "!selected!"=="all" (
  call :do_all
) else (
  echo [llama_server] Goodbye.
)

exit /b