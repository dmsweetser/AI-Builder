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
REM   llama_server.bat all              :: download all models (don't start)
REM
REM   set MTP=0 before running to disable MTP speculative decoding
REM   (only Gemma 4 ships an MTP draft; it is on by default for it --
REM   see the GEMMA_MTP note in the model definitions below).
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

REM ---------------------------------------------------------------------------
REM Model definitions. Contexts are each model's proper maximum, from its
REM publisher's config (text_config.max_position_embeddings): Ministral 3
REM and Gemma 4 are 256K models; Devstral Small 2's config declares
REM 393216 (384K, YaRN factor 48 over an 8192 base) even though it is
REM marketed as 256K. Ports are unchanged from when there were four
REM models (Ministral has always been 8081, etc.) so existing client
REM configs keep working; 8080 is simply unused now.
REM ---------------------------------------------------------------------------
set "MIN_NAME=Ministral-3-14B"
set "MIN_FILE=Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"
set "MIN_MMPROJ=mmproj-F16.gguf"
set "MIN_URL=https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/Ministral-3-14B-Instruct-2512-Q4_K_M.gguf?download=true"
set "MIN_MMURL=https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/mmproj-F16.gguf?download=true"
set "MIN_CTX=262144"
set "MIN_NPREDICT=-1"
set "MIN_PORT=8081"

set "DEV_NAME=Devstral-Small-2-24B"
set "DEV_FILE=Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf"
set "DEV_MMPROJ=mmproj-F32.gguf"
set "DEV_URL=https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf?download=true"
set "DEV_MMURL=https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "DEV_CTX=393216"
set "DEV_NPREDICT=-1"
set "DEV_PORT=8082"

set "GEMMA_NAME=Gemma-4-26B-A4B"
set "GEMMA_FILE=gemma-4-26B-A4B-it-UD-Q4_K_M.gguf"
set "GEMMA_MMPROJ=mmproj-F32.gguf"
set "GEMMA_URL=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf?download=true"
set "GEMMA_MMURL=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "GEMMA_CTX=262144"
set "GEMMA_NPREDICT=-1"
set "GEMMA_PORT=8083"
REM MTP (multi-token prediction) draft for speculative decoding.
REM Conditional by construction: only Gemma 4 has these -- it is the one
REM model whose publisher ships an MTP draft (a separate small GGUF in
REM the same repo). The two Mistrals ship no MTP head, so they have no
REM MTP variables and never see the MTP flags.
set "GEMMA_MTP=mtp-gemma-4-26B-A4B-it.gguf"
set "GEMMA_MTPURL=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/mtp-gemma-4-26B-A4B-it.gguf?download=true"

set "GEMMA4S_NAME=Gemma-4-E4B-it"
set "GEMMA4S_FILE=gemma-4-E4B-it-Q4_K_M.gguf"
set "GEMMA4S_MMPROJ=mmproj-F16.gguf"
set "GEMMA4S_URL=https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf?download=true"
set "GEMMA4S_MMURL=https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/mmproj-F16.gguf?download=true"
set "GEMMA4S_CTX=131072"
set "GEMMA4S_NPREDICT=-1"
set "GEMMA4S_PORT=8084"

REM ---------------------------------------------------------------------------
REM TLS bypass: set INSECURE_TLS=1 before running to skip certificate
REM verification (e.g. behind a corporate SSL-inspecting proxy).
REM ---------------------------------------------------------------------------
set "CURL_TLS_ARGS="
if "%INSECURE_TLS%"=="1" (
  echo [warn]    INSECURE_TLS=1 - certificate verification is DISABLED.
  set "CURL_TLS_ARGS=-k"
)

REM ---------------------------------------------------------------------------
REM Jump to main -- without this, execution falls through every label below and
REM runs detection / install / download / start-server with empty arguments.
REM ---------------------------------------------------------------------------
goto :main

REM ---------------------------------------------------------------------------
REM GPU detection
REM ---------------------------------------------------------------------------
:check_cuda_gpu
  REM WMIC is removed on Windows 11 24H2+; fall back to PowerShell CIM.
  REM Written sequentially, no && / || blocks: a FOR /F command string
  REM containing bare | characters breaks cmd's parser when the FOR sits
  REM inside a parenthesised block (the parser splits the block at the
  REM pipes) -- that was the "- was unexpected at this time" failure in
  REM the previous version of this function. The PowerShell one-liner
  REM below is also pipe-free on purpose (NVIDIA covers RTX/GTX names).
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
REM Download a model + mmproj (+ the MTP draft, for models that ship one)
REM ---------------------------------------------------------------------------
:download_model
  REM Args: display_name, model_dir, model_file, mmproj_file, model_url,
  REM       mmproj_url, mtp_file (optional), mtp_url (optional)
  set "display_name=%~1"
  set "model_dir=%~2"
  set "model_file=%~3"
  set "mmproj_file=%~4"
  set "model_url=%~5"
  set "mmproj_url=%~6"
  set "mtp_file=%~7"
  set "mtp_url=%~8"

  if not exist "%model_dir%" mkdir "%model_dir%"

  set "DL_OK=1"
  if not exist "%model_dir%\%model_file%" (
    echo [llama_server] Downloading %display_name% model...
    curl -fSL -C - !CURL_TLS_ARGS! -o "%model_dir%\%model_file%" "%model_url%" || (
      echo [error]   Model download failed: %model_file%
      set "DL_OK=0"
    )
  ) else (
    echo [llama_server] Model already present: %model_file%
  )

  if not exist "%model_dir%\%mmproj_file%" (
    echo [llama_server] Downloading %display_name% mmproj...
    curl -fSL -C - !CURL_TLS_ARGS! -o "%model_dir%\%mmproj_file%" "%mmproj_url%" || (
      echo [error]   mmproj download failed: %mmproj_file%
      set "DL_OK=0"
    )
  ) else (
    echo [llama_server] mmproj already present: %mmproj_file%
  )

  REM MTP draft (only when this model ships one -- arg 7 non-empty).
  REM Unlike the model/mmproj, a failed MTP download is NOT fatal and
  REM does not touch DL_OK: MTP is a speed bonus, and start_server
  REM falls back to running without it.
  if not "%mtp_file%"=="" (
    if not exist "%model_dir%\%mtp_file%" (
      echo [llama_server] Downloading %display_name% MTP draft...
      curl -fSL -C - !CURL_TLS_ARGS! -o "%model_dir%\%mtp_file%" "%mtp_url%" || (
        echo [warn]    MTP draft download failed: %mtp_file% - continuing without MTP.
      )
    ) else (
      echo [llama_server] MTP draft already present: %mtp_file%
    )
  )

  if "!DL_OK!"=="0" exit /b 1
  exit /b 0

REM ---------------------------------------------------------------------------
REM Start llama-server
REM ---------------------------------------------------------------------------
:start_server
  REM Args: alias, model_dir, model_file, mmproj_file, ctx, n_predict, port,
  REM       has_cuda, mtp_file (optional; empty for models without one)
  REM
  REM Written block-free (goto-driven) on purpose: the previous version
  REM built MM_PROJ_ARG / MTP_ARG inside parenthesised blocks (the MTP
  REM path triple-nested), where the embedded-quote SET lines and the
  REM parenthesised echo text broke cmd's block parser -- that was the
  REM "- was unexpected at this time" failure on the Gemma path, right
  REM after the Context line. Parsed one statement at a time at the top
  REM level of the subroutine, the same lines are safe.
  set "alias=%~1"
  set "model_dir=%~2"
  set "model_file=%~3"
  set "mmproj_file=%~4"
  set "ctx=%~5"
  set "npredict=%~6"
  set "port=%~7"
  set "has_cuda=%~8"
  set "mtp_file=%~9"

  if exist "%model_dir%\%model_file%" goto :ss_have_model
  echo [error]   Model file missing: %model_dir%\%model_file%
  exit /b 1
:ss_have_model

  set "PATH=%LLAMACPP_DIR%;%PATH%"

  echo [llama_server] Starting llama-server (%alias%)...
  echo [llama_server]   Model: %model_dir%\%model_file%
  echo [llama_server]   Port: %port%
  echo [llama_server]   Context: %ctx%

  set "MM_PROJ_ARG="
  if not exist "%model_dir%\%mmproj_file%" goto :ss_no_mmproj
  set "MM_PROJ_ARG=--mmproj "%model_dir%\%mmproj_file%""
  goto :ss_mtp
:ss_no_mmproj
  echo [llama_server]   mmproj not found -- running text-only.

:ss_mtp
  REM MTP speculative decoding, conditional on the model shipping an MTP
  REM draft (arg 9 non-empty) and on MTP not being forced off with
  REM MTP=0. A model with no draft never sees the flags; a missing draft
  REM file (failed download) degrades to a warning, not an abort.
  set "MTP_ARG="
  if "%mtp_file%"=="" goto :ss_mtp_none
  if "%MTP%"=="0" goto :ss_mtp_done
  if not exist "%model_dir%\%mtp_file%" goto :ss_mtp_missing
  set "MTP_ARG=--spec-type draft-mtp --spec-draft-model "%model_dir%\%mtp_file%""
  echo [llama_server]   MTP: on (draft-mtp, %mtp_file%)
  goto :ss_mtp_done
:ss_mtp_missing
  echo [warn]    MTP draft not present (%mtp_file%) - running without MTP.
  goto :ss_mtp_done
:ss_mtp_none
  if not "%MTP%"=="1" goto :ss_mtp_done
  echo [warn]    MTP requested, but this model ships no MTP draft - running without MTP.
:ss_mtp_done

  set "GPU_ARG="
  if "!has_cuda!"=="1" set "GPU_ARG=--n-gpu-layers 999"

  REM -n is n_predict; -1 means unlimited (bounded by context size).
  llama-server ^
    -m "%model_dir%\%model_file%" ^
    !MM_PROJ_ARG! ^
    !MTP_ARG! ^
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
REM Interactive menu -- sets SELECTED directly. (Capturing the menu's output via
REM `for /f` broke because `set /p` cannot read user input inside a for-f
REM child cmd.)
REM ---------------------------------------------------------------------------
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
  echo   5) Download ALL models
  echo   0) Exit
  echo.
  set "selected="
  set /p "choice=Select model [1-4, 0=exit]: "
  if "!choice!"=="1" set "selected=ministral"
  if "!choice!"=="2" set "selected=devstral"
  if "!choice!"=="3" set "selected=gemma4"
  if "!choice!"=="4" set "selected=gemma4_small"
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
  REM Args: name, model_file, mmproj_file, model_url, mmproj_url, ctx,
  REM       n_predict, port, key
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

  REM Only Gemma 4 ships an MTP draft (see GEMMA_MTP above).
  set "mtpfile="
  set "mtpurl="
  if "%key%"=="gemma4" (
    set "mtpfile=%GEMMA_MTP%"
    set "mtpurl=%GEMMA_MTPURL%"
  ) else if "%key%"=="gemma4_small" (
    set "mtpfile="
    set "mtpurl="
  )

  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  call :download_model "%name%" "%model_dir%" "%mfile%" "%mmpfile%" "%murl%" "%mmurl%" "!mtpfile!" "!mtpurl!" || exit /b 1
  call :start_server "%key%" "%model_dir%" "%mfile%" "%mmpfile%" "%ctx%" "%npredict%" "%port%" "!HAS_CUDA!" "!mtpfile!"
exit /b

:do_all
  call :install_prereqs || exit /b 1
  call :install_llamacpp || exit /b 1
  call :download_model "%MIN_NAME%" "%MODEL_BASE_DIR%\%MIN_NAME%" "%MIN_FILE%" "%MIN_MMPROJ%" "%MIN_URL%" "%MIN_MMURL%" "" "" || exit /b 1
  call :download_model "%DEV_NAME%" "%MODEL_BASE_DIR%\%DEV_NAME%" "%DEV_FILE%" "%DEV_MMPROJ%" "%DEV_URL%" "%DEV_MMURL%" "" "" || exit /b 1
  call :download_model "%GEMMA_NAME%" "%MODEL_BASE_DIR%\%GEMMA_NAME%" "%GEMMA_FILE%" "%GEMMA_MMPROJ%" "%GEMMA_URL%" "%GEMMA_MMURL%" "%GEMMA_MTP%" "%GEMMA_MTPURL%" || exit /b 1
  call :download_model "%GEMMA4S_NAME%" "%MODEL_BASE_DIR%\%GEMMA4S_NAME%" "%GEMMA4S_FILE%" "%GEMMA4S_MMPROJ%" "%GEMMA4S_URL%" "%GEMMA4S_MMURL%" "" "" || exit /b 1
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

if "!selected!"=="ministral" (
  call :do_model "%MIN_NAME%" "%MIN_FILE%" "%MIN_MMPROJ%" "%MIN_URL%" "%MIN_MMURL%" "%MIN_CTX%" "%MIN_NPREDICT%" "%MIN_PORT%" ministral
) else if "!selected!"=="devstral" (
  call :do_model "%DEV_NAME%" "%DEV_FILE%" "%DEV_MMPROJ%" "%DEV_URL%" "%DEV_MMURL%" "%DEV_CTX%" "%DEV_NPREDICT%" "%DEV_PORT%" devstral
) else if "!selected!"=="gemma4" (
  call :do_model "%GEMMA_NAME%" "%GEMMA_FILE%" "%GEMMA_MMPROJ%" "%GEMMA_URL%" "%GEMMA_MMURL%" "%GEMMA_CTX%" "%GEMMA_NPREDICT%" "%GEMMA_PORT%" gemma4
) else if "!selected!"=="gemma4_small" (
  call :do_model "%GEMMA4S_NAME%" "%GEMMA4S_FILE%" "%GEMMA4S_MMPROJ%" "%GEMMA4S_URL%" "%GEMMA4S_MMURL%" "%GEMMA4S_CTX%" "%GEMMA4S_NPREDICT%" "%GEMMA4S_PORT%" gemma4_small
) else if "!selected!"=="all" (
  call :do_all
) else (
  echo [llama_server] Goodbye.
)

exit /b
