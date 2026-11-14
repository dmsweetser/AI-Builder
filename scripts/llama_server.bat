@echo off
setlocal enabledelayedexpansion

REM ===========================================================================
REM AI-Builder — llama.cpp Server (Windows — CUDA or CPU)
REM ===========================================================================
REM Downloads pre-built llama.cpp release, downloads the requested model(s), and
REM starts llama-server in the foreground.
REM
REM GPU: CUDA (NVIDIA) — auto-detected via WMIC + CUDA toolkit check
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

cd /d "%~dp0.."
set "WORKDIR=%CD%"
set "LLAMACPP_DIR=%WORKDIR%\llama.cpp-bin"
set "MODEL_BASE_DIR=%WORKDIR%\models"

REM ---------------------------------------------------------------------------
REM Model definitions
REM ---------------------------------------------------------------------------
set "QWEN_NAME=Qwen3.6-35B-A3B"
set "QWEN_FILE=Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
set "QWEN_MMPROJ=mmproj-F32.gguf"
set "QWEN_URL=https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf?download=true"
set "QWEN_MMURL=https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "QWEN_CTX=262144"
set "QWEN_NS=131072"
set "QWEN_PORT=8080"

set "MIN_NAME=Ministral-3-14B"
set "MIN_FILE=Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"
set "MIN_MMPROJ=mmproj-F16.gguf"
set "MIN_URL=https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/Ministral-3-14B-Instruct-2512-Q4_K_M.gguf?download=true"
set "MIN_MMURL=https://huggingface.co/unsloth/Ministral-3-14B-Instruct-2512-GGUF/resolve/main/mmproj-F16.gguf?download=true"
set "MIN_CTX=131072"
set "MIN_NS=65536"
set "MIN_PORT=8081"

set "DEV_NAME=Devstral-Small-2-24B"
set "DEV_FILE=Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf"
set "DEV_MMPROJ=mmproj-F32.gguf"
set "DEV_URL=https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf?download=true"
set "DEV_MMURL=https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "DEV_CTX=131072"
set "DEV_NS=65536"
set "DEV_PORT=8082"

set "GEMMA_NAME=Gemma-4-26B-A4B"
set "GEMMA_FILE=gemma-4-26B-A4B-it-UD-Q4_K_M.gguf"
set "GEMMA_MMPROJ=mmproj-F32.gguf"
set "GEMMA_URL=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf?download=true"
set "GEMMA_MMURL=https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/mmproj-F32.gguf?download=true"
set "GEMMA_CTX=131072"
set "GEMMA_NS=65536"
set "GEMMA_PORT=8083"

REM ---------------------------------------------------------------------------
REM Helpers
REM ---------------------------------------------------------------------------
echo_log()    echo [llama_server] %~1
echo_warn()  echo [warn]    %~1
echo_err()   (echo [error]   %~1 & exit /b 1)

REM ---------------------------------------------------------------------------
REM GPU detection
REM ---------------------------------------------------------------------------
check_cuda_gpu() (
  set "GPU_FOUND="
  for /f "tokens=*" %%G in ('wmic path win32_videcontroller where "adapterram>0" get name 2^>nul') do (
    for %%H in (%%G) do (
      set "NAME=%%H"
      set "NAME=!NAME: =!"
      if not "!NAME!"=="" (
        echo !NAME! | findstr /i /c:"NVIDIA" /c:"RTX" /c:"GTX" >nul && set "GPU_FOUND=Y"
      )
    )
  )
  if defined GPU_FOUND (exit /b 0) else (exit /b 1)
)

REM Check for CUDA Toolkit (v12 or v13)
check_cuda_toolkit() (
  if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA" (
    dir /b "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13" 2>nul | findstr /i "v13" >nul && exit /b 0
    dir /b "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12" 2>nul | findstr /i "v12" >nul && exit /b 0
  )
  exit /b 1
)

REM Detect CUDA toolkit major version (12 or 13)
detect_cuda_version() (
  if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13" (
    echo 13
  ) else if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12" (
    echo 12
  ) else (
    echo 0
  )
)

REM ---------------------------------------------------------------------------
REM Prerequisites (git + curl only — no compiler for pre-built)
REM ---------------------------------------------------------------------------
install_prereqs() (
  echo_log Checking prerequisites...

  where git >nul 2>&1 || (
    echo_warn git not found. Install from https://git-scm.com/download/win
    echo_err Aborting.
  )

  where curl >nul 2>&1 || (
    echo_warn curl not found. Install from https://curl.se/windows/
    echo_err Aborting.
  )

  where tar >nul 2>&1 || (
    echo_warn tar not found. Install 7-Zip or Git Bash for tar support.
    echo_err Aborting.
  )

  echo_log Prerequisites ready.
)

REM ---------------------------------------------------------------------------
REM Download + extract pre-built llama.cpp
REM ---------------------------------------------------------------------------
install_llamacpp() (
  if exist "%LLAMACPP_DIR%\llama-server.exe" (
    echo_log llama-server already installed.
    exit /b 0
  )

  REM Fetch latest tag from GitHub API
  set "TMPFILE=%TEMP%\llama_tag.txt"
  curl -fsSL https://api.github.com/repos/ggml-org/llama.cpp/releases/latest -o "%TMPFILE%" 2>nul
  for /f "delims=" %%T in ('findstr /i "tag_name" "%TMPFILE%" ^| findstr /i "b[0-9]"') do (
    set "LINE=%%T"
  )
  del /q "%TMPFILE%" >nul 2>&1

  REM Extract tag from JSON: "tag_name": "b12377"
  set "TAG="
  for /f "tokens=2 delims=:," %%T in ('echo !LINE!') do (
    set "TAG=%%T"
  )
  set "TAG=!TAG:"=!"
  set "TAG=!TAG: =!"

  if "!TAG!"=="" (
    echo_err Could not fetch latest release tag from GitHub.
  )

  REM Detect GPU and CUDA version
  set "HAS_CUDA=0"
  set "CUDA_VER=0"
  call check_cuda_gpu >nul 2>&1 && (
    set "HAS_CUDA=1"
    call :detect_cuda_version > "%TEMP%\cuda_ver.txt"
    set /p "CUDA_VER=<%TEMP%\cuda_ver.txt"
    del /q "%TEMP%\cuda_ver.txt" >nul 2>&1
  )

  REM Choose download URL based on GPU + architecture
  set "ARCH="
  for /f "tokens=*" %%A in ('wmic cpu get architecture 2^>nul ^| findstr /v "Architecture"') do (
    set "ARCH=%%A"
    set "ARCH=!ARCH: =!"
  )

  REM Architecture mapping: 0=x86, 9=AMD64/Intel64, 12=ARM64
  set "BIN_ARCH=x64"
  if "!ARCH!"=="12" set "BIN_ARCH=arm64"

  set "ARCHIVE_URL="
  set "CUDART_URL="

  if "!HAS_CUDA!"=="1" (
    if "!CUDA_VER!"=="13" (
      if "!BIN_ARCH!"=="x64" (
        set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-13.5-%BIN_ARCH%.zip"
        set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-13.5-%BIN_ARCH%.zip"
      ) else (
        set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-13.5-%BIN_ARCH%.zip"
        set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-13.5-%BIN_ARCH%.zip"
      )
    ) else (
      REM CUDA 12 or unknown — try CUDA 12
      set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-12.4-%BIN_ARCH%.zip"
      set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-12.4-%BIN_ARCH%.zip"
    )
    echo_log CUDA pre-built selected.
  ) else (
    set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cpu-%BIN_ARCH%.zip"
    echo_log CPU pre-built selected.
  )

  set "TMPDIR=%TEMP%\llama_download"
  mkdir "%TMPDIR%" >nul 2>&1

  echo_log Downloading llama.cpp pre-built release (tag: %TAG%)...
  curl -fSL -o "%TMPDIR%\llama.zip" "%ARCHIVE_URL%" || (
    echo_err Failed to download llama.cpp pre-built.
    rmdir /s /q "%TMPDIR%" >nul 2>&1
    exit /b 1
  )

  REM Create install directory
  if not exist "%LLAMACPP_DIR%" mkdir "%LLAMACPP_DIR%"

  REM Extract — try PowerShell first, fall back to tar
  if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" (
    "%ProgramFiles%\PowerShell\7\pwsh.exe" -c "Expand-Archive -Path '%TMPDIR%\llama.zip' -DestinationPath '%TMPDIR%' -Force"
  ) else if exist "%ProgramFiles%\PowerShell\PowerShell\7\pwsh.exe" (
    "%ProgramFiles%\PowerShell\PowerShell\7\pwsh.exe" -c "Expand-Archive -Path '%TMPDIR%\llama.zip' -DestinationPath '%TMPDIR%' -Force"
  ) else if exist "%ProgramFiles%\PowerShell\6\pwsh.exe" (
    "%ProgramFiles%\PowerShell\6\pwsh.exe" -c "Expand-Archive -Path '%TMPDIR%\llama.zip' -DestinationPath '%TMPDIR%' -Force"
  ) else (
    REM Fall back to 7-Zip or tar
    if exist "%ProgramFiles%\7-Zip\7z.exe" (
      "%ProgramFiles%\7-Zip\7z.exe" x "%TMPDIR%\llama.zip" -o"%TMPDIR%" -y >nul 2>&1
    ) else (
      tar -xzf "%TMPDIR%\llama.zip" -C "%TMPDIR%" 2>nul || (
        echo_err Failed to extract llama.cpp. Install 7-Zip or PowerShell 7.
        rmdir /s /q "%TMPDIR%" >nul 2>&1
        exit /b 1
      )
    )
  )

  REM Copy binaries to install directory
  REM The zip extracts a directory like "llama-b12377-bin-win-cpu-x64/"
  for /d %%D in ("%TMPDIR%\llama-*") do (
    if exist "%%D\llama-server.exe" (
      xcopy "%%D\*" "%LLAMACPP_DIR%\" /E /I /Y >nul 2>&1
    )
  )

  REM Download CUDA runtime DLLs if needed
  if defined CUDART_URL if not "!CUDART_URL!"=="" (
    echo_log Downloading CUDA runtime libraries...
    curl -fSL -o "%TMPDIR%\cudart.zip" "%CUDART_URL%" 2>nul
    if exist "%TMPDIR%\cudart.zip" (
      if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" (
        "%ProgramFiles%\PowerShell\7\pwsh.exe" -c "Expand-Archive -Path '%TMPDIR%\cudart.zip' -DestinationPath '%TMPDIR%' -Force"
      ) else if exist "%ProgramFiles%\7-Zip\7z.exe" (
        "%ProgramFiles%\7-Zip\7z.exe" x "%TMPDIR%\cudart.zip" -o"%TMPDIR%" -y >nul 2>&1
      )
      for /d %%D in ("%TMPDIR%\cudart-*") do (
        if exist "%%D\*.dll" (
          xcopy "%%D\*.dll" "%LLAMACPP_DIR%\" /Y >nul 2>&1
        )
      )
      echo_log CUDA runtime libraries installed.
    )
  )

  REM Cleanup
  rmdir /s /q "%TMPDIR%" >nul 2>&1

  if not exist "%LLAMACPP_DIR%\llama-server.exe" (
    echo_err llama-server.exe not found after extraction.
    exit /b 1
  )

  echo_log llama-server installed (tag: %TAG%, backend: !HAS_CUDA!).
)

REM ---------------------------------------------------------------------------
REM Download a model + mmproj
REM ---------------------------------------------------------------------------
download_model() (
  set "display_name=%~1"
  set "model_dir=%~2"
  set "model_file=%~3"
  set "mmproj_file=%~4"
  set "model_url=%~5"
  set "mmproj_url=%~6"

  if not exist "%model_dir%" mkdir "%model_dir%"

  if not exist "%model_dir%\%model_file%" (
    echo_log Downloading %display_name% model...
    curl -fSL -C - -o "%model_dir%\%model_file%" "%model_url%" || (
      echo_err Model download failed: %model_file%
    )
  ) else (
    echo_log Model already present: %model_file%
  )

  if not exist "%model_dir%\%mmproj_file%" (
    echo_log Downloading %display_name% mmproj...
    curl -fSL -C - -o "%model_dir%\%mmproj_file%" "%mmproj_url%" || (
      echo_err mmproj download failed: %mmproj_file%
    )
  ) else (
    echo_log mmproj already present: %mmproj_file%
  )
)

REM ---------------------------------------------------------------------------
REM Start llama-server
REM ---------------------------------------------------------------------------
start_server() (
  set "alias=%~1"
  set "model_dir=%~2"
  set "model_file=%~3"
  set "mmproj_file=%~4"
  set "ctx=%~5"
  set "ns=%~6"
  set "port=%~7"

  set "PATH=%LLAMACPP_DIR%;%PATH%"

  echo_log Starting llama-server (%alias%)...
  echo_log   Model: %model_dir%\%model_file%
  echo_log   mmproj: %model_dir%\%mmproj_file%
  echo_log   Port: %port%

  llama-server ^
    -m "%model_dir%\%model_file%" ^
    --mmproj "%model_dir%\%mmproj_file%" ^
    --alias %alias% ^
    --flash-attn on ^
    -c %ctx% ^
    -n %ns% ^
    --cache-type-k q8_0 ^
    --cache-type-v q8_0 ^
    --batch-size 512 ^
    --ubatch-size 512 ^
    --temp 0.7 ^
    --top-p 0.8 ^
    --top-k 20 ^
    --host 0.0.0.0 ^
    --port %port% ^
    --n-gpu-layers 999
)

REM ---------------------------------------------------------------------------
REM Interactive menu
REM ---------------------------------------------------------------------------
show_menu() (
  echo.
  echo ============================================
  echo   AI-Builder -- llama.cpp Server (Windows)
  echo ============================================
  echo.
  echo   1) Qwen3.6-35B-A3B       (port 8080, 256K ctx)
  echo   2) Ministral-3-14B        (port 8081, 128K ctx)
  echo   3) Devstral-Small-2-24B   (port 8082, 128K ctx)
  echo   4) Gemma-4-26B-A4B-it     (port 8083, 128K ctx)
  echo   5) Download ALL models
  echo   0) Exit
  echo.
  echo   Or run: llama_server.bat ^<qwen35b^|ministral^|devstral^|gemma4^|all^>
  echo.
  set /p "choice=Select model [1-5, 0=exit]: "
  if "!choice!"=="1" echo qwen35b
  if "!choice!"=="2" echo ministral
  if "!choice!"=="3" echo devstral
  if "!choice!"=="4" echo gemma4
  if "!choice!"=="5" echo all
  if "!choice!"=="0" exit /b 0
)

REM ---------------------------------------------------------------------------
REM Main
REM ---------------------------------------------------------------------------
set "selected=%~1"

if "%selected%"=="" (
  for /f "delims=" %%L in ('show_menu') do set "selected=%%L"
)

if "%selected%"=="qwen35b" (
  call :do_model "%QWEN_NAME%" "%QWEN_FILE%" "%QWEN_MMPROJ%" "%QWEN_URL%" "%QWEN_MMURL%" "%QWEN_CTX%" "%QWEN_NS%" "%QWEN_PORT%" qwen35b
) else if "%selected%"=="ministral" (
  call :do_model "%MIN_NAME%" "%MIN_FILE%" "%MIN_MMPROJ%" "%MIN_URL%" "%MIN_MMURL%" "%MIN_CTX%" "%MIN_NS%" "%MIN_PORT%" ministral
) else if "%selected%"=="devstral" (
  call :do_model "%DEV_NAME%" "%DEV_FILE%" "%DEV_MMPROJ%" "%DEV_URL%" "%DEV_MMURL%" "%DEV_CTX%" "%DEV_NS%" "%DEV_PORT%" devstral
) else if "%selected%"=="gemma4" (
  call :do_model "%GEMMA_NAME%" "%GEMMA_FILE%" "%GEMMA_MMPROJ%" "%GEMMA_URL%" "%GEMMA_MMURL%" "%GEMMA_CTX%" "%GEMMA_NS%" "%GEMMA_PORT%" gemma4
) else if "%selected%"=="all" (
  call :do_all
) else (
  echo_log Goodbye.
  exit /b 0
)

exit /b

:do_model
REM Args: name, model_file, mmproj_file, model_url, mmproj_url, ctx, ns, port, key
  set "name=%~1"
  set "mfile=%~2"
  set "mmpfile=%~3"
  set "murl=%~4"
  set "mmurl=%~5"
  set "ctx=%~6"
  set "ns=%~7"
  set "port=%~8"
  set "key=%~9"
  set "model_dir=%MODEL_BASE_DIR%\%name%"

  call :install_prereqs_inner
  call :install_llamacpp_inner
  call :download_model_inner "%name%" "%model_dir%" "%mfile%" "%mmpfile%" "%murl%" "%mmurl%"
  call :start_server_inner "%key%" "%model_dir%" "%mfile%" "%mmpfile%" "%ctx%" "%ns%" "%port%"
exit /b

:do_all
  call :install_prereqs_inner
  call :install_llamacpp_inner
  call :download_model_inner "%QWEN_NAME%" "%MODEL_BASE_DIR%\%QWEN_NAME%" "%QWEN_FILE%" "%QWEN_MMPROJ%" "%QWEN_URL%" "%QWEN_MMURL%"
  call :download_model_inner "%MIN_NAME%" "%MODEL_BASE_DIR%\%MIN_NAME%" "%MIN_FILE%" "%MIN_MMPROJ%" "%MIN_URL%" "%MIN_MMURL%"
  call :download_model_inner "%DEV_NAME%" "%MODEL_BASE_DIR%\%DEV_NAME%" "%DEV_FILE%" "%DEV_MMPROJ%" "%DEV_URL%" "%DEV_MMURL%"
  call :download_model_inner "%GEMMA_NAME%" "%MODEL_BASE_DIR%\%GEMMA_NAME%" "%GEMMA_FILE%" "%GEMMA_MMPROJ%" "%GEMMA_URL%" "%GEMMA_MMURL%"
  echo_log All models downloaded. Use llama_server.bat ^<model^> to start a server.
exit /b

:install_prereqs_inner
  echo_log Checking prerequisites...
  where git >nul 2>&1 || (echo_err git not found. Install from https://git-scm.com/download/win)
  where curl >nul 2>&1 || (echo_err curl not found. Install from https://curl.se/windows/)
  where tar >nul 2>&1 || (echo_err tar not found. Install 7-Zip or Git Bash.)
  echo_log Prerequisites ready.
exit /b

:install_llamacpp_inner
  if exist "%LLAMACPP_DIR%\llama-server.exe" (
    echo_log llama-server already installed.
    exit /b 0
  )

  REM Fetch latest tag
  set "TMPFILE=%TEMP%\llama_tag.txt"
  curl -fsSL https://api.github.com/repos/ggml-org/llama.cpp/releases/latest -o "%TMPFILE%" 2>nul
  set "LINE="
  for /f "delims=" %%T in ('findstr /i "tag_name" "%TMPFILE%" ^| findstr /i "b[0-9]"') do set "LINE=%%T"
  del /q "%TMPFILE%" >nul 2>&1

  set "TAG="
  for /f "tokens=2 delims=:," %%T in ('echo !LINE!') do set "TAG=%%T"
  set "TAG=!TAG:"=!"
  set "TAG=!TAG: =!"

  if "!TAG!"=="" (
    echo_err Could not fetch latest release tag.
    exit /b 1
  )

  REM Detect GPU + CUDA version
  set "HAS_CUDA=0"
  set "CUDA_VER=0"
  call check_cuda_gpu >nul 2>&1 && (
    set "HAS_CUDA=1"
    for /f %%V in ('call :detect_cuda_version') do set "CUDA_VER=%%V"
  )

  REM Architecture
  set "BIN_ARCH=x64"
  for /f "tokens=*" %%A in ('wmic cpu get architecture 2^>nul ^| findstr /v "Architecture"') do (
    set "ARCH=%%A"
    set "ARCH=!ARCH: =!"
  )
  if "!ARCH!"=="12" set "BIN_ARCH=arm64"

  set "ARCHIVE_URL="
  set "CUDART_URL="

  if "!HAS_CUDA!"=="1" (
    if "!CUDA_VER!"=="13" (
      set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-13.5-%BIN_ARCH%.zip"
      set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-13.5-%BIN_ARCH%.zip"
    ) else (
      set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cuda-12.4-%BIN_ARCH%.zip"
      set "CUDART_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/cudart-llama-bin-win-cuda-12.4-%BIN_ARCH%.zip"
    )
    echo_log CUDA pre-built selected.
  ) else (
    set "ARCHIVE_URL=https://github.com/ggml-org/llama.cpp/releases/download/%TAG%/llama-%TAG%-bin-win-cpu-%BIN_ARCH%.zip"
    echo_log CPU pre-built selected.
  )

  set "TMPDIR=%TEMP%\llama_download"
  mkdir "%TMPDIR%" >nul 2>&1

  echo_log Downloading llama.cpp pre-built release (tag: %TAG%)...
  curl -fSL -o "%TMPDIR%\llama.zip" "%ARCHIVE_URL%" || (
    echo_err Failed to download llama.cpp pre-built.
    rmdir /s /q "%TMPDIR%" >nul 2>&1
    exit /b 1
  )

  if not exist "%LLAMACPP_DIR%" mkdir "%LLAMACPP_DIR%"

  REM Extract
  if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" (
    "%ProgramFiles%\PowerShell\7\pwsh.exe" -c "Expand-Archive -Path '%TMPDIR%\llama.zip' -DestinationPath '%TMPDIR%' -Force"
  ) else if exist "%ProgramFiles%\7-Zip\7z.exe" (
    "%ProgramFiles%\7-Zip\7z.exe" x "%TMPDIR%\llama.zip" -o"%TMPDIR%" -y >nul 2>&1
  ) else (
    echo_err No extraction tool found. Install 7-Zip or PowerShell 7.
    rmdir /s /q "%TMPDIR%" >nul 2>&1
    exit /b 1
  )

  for /d %%D in ("%TMPDIR%\llama-*") do (
    if exist "%%D\llama-server.exe" (
      xcopy "%%D\*" "%LLAMACPP_DIR%\" /E /I /Y >nul 2>&1
    )
  )

  REM CUDA DLLs
  if defined CUDART_URL if not "!CUDART_URL!"=="" (
    echo_log Downloading CUDA runtime libraries...
    curl -fSL -o "%TMPDIR%\cudart.zip" "%CUDART_URL%" 2>nul
    if exist "%TMPDIR%\cudart.zip" (
      if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" (
        "%ProgramFiles%\PowerShell\7\pwsh.exe" -c "Expand-Archive -Path '%TMPDIR%\cudart.zip' -DestinationPath '%TMPDIR%' -Force"
      ) else if exist "%ProgramFiles%\7-Zip\7z.exe" (
        "%ProgramFiles%\7-Zip\7z.exe" x "%TMPDIR%\cudart.zip" -o"%TMPDIR%" -y >nul 2>&1
      )
      for /d %%D in ("%TMPDIR%\cudart-*") do (
        if exist "%%D\*.dll" xcopy "%%D\*.dll" "%LLAMACPP_DIR%\" /Y >nul 2>&1
      )
      echo_log CUDA runtime libraries installed.
    )
  )

  rmdir /s /q "%TMPDIR%" >nul 2>&1

  if not exist "%LLAMACPP_DIR%\llama-server.exe" (
    echo_err llama-server.exe not found after extraction.
    exit /b 1
  )

  echo_log llama-server installed (tag: %TAG%, backend: !HAS_CUDA!).
exit /b

:download_model_inner
  set "display_name=%~1"
  set "model_dir=%~2"
  set "model_file=%~3"
  set "mmproj_file=%~4"
  set "model_url=%~5"
  set "mmproj_url=%~6"

  if not exist "%model_dir%" mkdir "%model_dir%"

  if not exist "%model_dir%\%model_file%" (
    echo_log Downloading %display_name% model...
    curl -fSL -C - -o "%model_dir%\%model_file%" "%model_url%" || (echo_err Model download failed: %model_file%)
  ) else (
    echo_log Model already present: %model_file%
  )

  if not exist "%model_dir%\%mmproj_file%" (
    echo_log Downloading %display_name% mmproj...
    curl -fSL -C - -o "%model_dir%\%mmproj_file%" "%mmproj_url%" || (echo_err mmproj download failed: %mmproj_file%)
  ) else (
    echo_log mmproj already present: %mmproj_file%
  )
exit /b

:start_server_inner
  set "alias=%~1"
  set "model_dir=%~2"
  set "model_file=%~3"
  set "mmproj_file=%~4"
  set "ctx=%~5"
  set "ns=%~6"
  set "port=%~7"

  set "PATH=%LLAMACPP_DIR%;%PATH%"

  echo_log Starting llama-server (%alias%)...
  echo_log   Model: %model_dir%\%model_file%
  echo_log   mmproj: %model_dir%\%mmproj_file%
  echo_log   Port: %port%

  llama-server ^
    -m "%model_dir%\%model_file%" ^
    --mmproj "%model_dir%\%mmproj_file%" ^
    --alias %alias% ^
    --flash-attn on ^
    -c %ctx% ^
    -n %ns% ^
    --cache-type-k q8_0 ^
    --cache-type-v q8_0 ^
    --batch-size 512 ^
    --ubatch-size 512 ^
    --temp 0.7 ^
    --top-p 0.8 ^
    --top-k 20 ^
    --host 0.0.0.0 ^
    --port %port% ^
    --n-gpu-layers 999
exit /b
