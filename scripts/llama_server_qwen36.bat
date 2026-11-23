@echo off
REM ===========================================================================
REM AI-Builder -- llama.cpp Server (Windows) -- Qwen3.6-35B-A3B
REM No model variables, no functions. Everything literal. TLS ignored (-k).
REM ===========================================================================

cd /d "%~dp0" || ( echo [error] Could not cd. & exit /b 1 )

set "HAS_CUDA=0"
where wmic >nul 2>&1
if errorlevel 1 goto :check_gpu_ps
for /f "tokens=*" %%G in ('wmic path win32_VideoController where "adapterram>0" get name 2^>nul ^| findstr /i /c:"NVIDIA" /c:"RTX" /c:"GTX"') do set "HAS_CUDA=1"
goto :check_gpu_done
:check_gpu_ps
for /f "usebackq delims=" %%G in (`powershell -NoProfile -Command "if ((Get-CimInstance Win32_VideoController).Name -match 'NVIDIA') { echo Y }" 2^>nul`) do set "HAS_CUDA=1"
:check_gpu_done

where git >nul 2>&1 || ( echo [warn] git not found & exit /b 1 )
where curl >nul 2>&1 || ( echo [warn] curl not found & exit /b 1 )
where tar >nul 2>&1 || ( echo [warn] tar not found. Need 7-Zip or PowerShell. )

set "LLAMA_DIR=%~dp0llama.cpp-bin"
set "MODEL_DIR=%~dp0models\Qwen3.6-35B-A3B-UD-IQ4_XS"

if exist "%LLAMA_DIR%\llama-server.exe" goto :download_model

if "%HAS_CUDA%"=="1" (
  if exist "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13" (
    curl -fSL -k -o "%TEMP%\llama.zip" "https://github.com/ggml-org/llama.cpp/releases/download/b12387/llama-b12387-bin-win-cuda-13.5-x64.zip"
    curl -fSL -k -o "%TEMP%\cudart.zip" "https://github.com/ggml-org/llama.cpp/releases/download/b12387/cudart-llama-bin-win-cuda-13.5-x64.zip"
  ) else (
    curl -fSL -k -o "%TEMP%\llama.zip" "https://github.com/ggml-org/llama.cpp/releases/download/b12387/llama-b12387-bin-win-cuda-12.4-x64.zip"
    curl -fSL -k -o "%TEMP%\cudart.zip" "https://github.com/ggml-org/llama.cpp/releases/download/b12387/cudart-llama-bin-win-cuda-12.4-x64.zip"
  )
) else (
  curl -fSL -k -o "%TEMP%\llama.zip" "https://github.com/ggml-org/llama.cpp/releases/download/b12387/llama-b12387-bin-win-cpu-x64.zip"
) || ( echo [error] Download failed. & exit /b 1 )

if not exist "%LLAMA_DIR%" mkdir "%LLAMA_DIR%"
tar -xf "%TEMP%\llama.zip" -C "%TEMP%" 2>nul
if errorlevel 1 (
  for %%P in ("%ProgramFiles%\PowerShell\7\pwsh.exe" "%ProgramFiles%\PowerShell\PowerShell\7\pwsh.exe" "%ProgramFiles%\PowerShell\6\pwsh.exe") do (
    if exist "%%~P" ( "%%~P" -NoProfile -Command "Expand-Archive -LiteralPath '%TEMP%\llama.zip' -DestinationPath '%TEMP%' -Force" && goto :llama_copied )
  )
  if exist "%ProgramFiles%\7-Zip\7z.exe" ( "%ProgramFiles%\7-Zip\7z.exe" x "%TEMP%\llama.zip" -o"%TEMP%" -y >nul 2>&1 && goto :llama_copied )
  echo [error] Extract failed. & exit /b 1
)
:llama_copied
for /d %%D in ("%TEMP%\llama-*") do ( if exist "%%D\llama-server.exe" xcopy "%%D\*" "%LLAMA_DIR%\" /E /I /Y >nul 2>&1 )
if not exist "%LLAMA_DIR%\llama-server.exe" if exist "%TEMP%\llama-server.exe" xcopy "%TEMP%\*" "%LLAMA_DIR%\" /E /I /Y >nul 2>&1

if "%HAS_CUDA%"=="1" if exist "%TEMP%\cudart.zip" (
  tar -xf "%TEMP%\cudart.zip" -C "%TEMP%" 2>nul
  for /d %%D in ("%TEMP%\cudart-*") do xcopy "%%D\*.dll" "%LLAMA_DIR%\" /Y >nul 2>&1
  if exist "%TEMP%\*.dll" xcopy "%TEMP%\*.dll" "%LLAMA_DIR%\" /Y >nul 2>&1
  echo [llama_server] CUDA runtime libraries installed.
)
del /q "%TEMP%\llama.zip" "%TEMP%\cudart.zip" >nul 2>&1
if not exist "%LLAMA_DIR%\llama-server.exe" ( echo [error] llama-server.exe not found. & exit /b 1 )
echo [llama_server] llama-server installed.

:download_model
if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"
if not exist "%MODEL_DIR%\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf" (
  echo [llama_server] Downloading Qwen3.6-35B-A3B model...
  curl -fSL -k -C - -o "%MODEL_DIR%\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf" "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf?download=true" || ( echo [error] Model download failed. & exit /b 1 )
) else ( echo [llama_server] Model already present. )
if not exist "%MODEL_DIR%\mmproj-F32.gguf" (
  echo [llama_server] Downloading Qwen3.6 mmproj...
  curl -fSL -k -C - -o "%MODEL_DIR%\mmproj-F32.gguf" "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/mmproj-F32.gguf?download=true" || ( echo [warn] mmproj failed -- text-only. )
) else ( echo [llama_server] mmproj already present. )
if not exist "%MODEL_DIR%\Qwen3.6-35B-A3B-MTP-draft.gguf" (
  echo [llama_server] Downloading Qwen3.6 MTP draft...
  curl -fSL -k -C - -o "%MODEL_DIR%\Qwen3.6-35B-A3B-MTP-draft.gguf" "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF/resolve/main/Qwen3.6-35B-A3B-MTP-draft.gguf?download=true" || ( echo [warn] MTP draft failed. )
) else ( echo [llama_server] MTP draft already present. )

set "PATH=%LLAMA_DIR%;%PATH%"
set "MM="
if exist "%MODEL_DIR%\mmproj-F32.gguf" set "MM=--mmproj "%MODEL_DIR%\mmproj-F32.gguf""
set "MTP="
if exist "%MODEL_DIR%\Qwen3.6-35B-A3B-MTP-draft.gguf" set "MTP=--spec-type draft-mtp --spec-draft-model "%MODEL_DIR%\Qwen3.6-35B-A3B-MTP-draft.gguf""
set "GPU="
if "%HAS_CUDA%"=="1" set "GPU=--n-gpu-layers 999"

echo [llama_server] Starting llama-server (Qwen3.6-35B-A3B)...
llama-server -m "%MODEL_DIR%\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf" !MM! !MTP! --alias qwen36 --jinja --flash-attn on -c 262144 -n -1 --cache-type-k q8_0 --cache-type-v q8_0 --batch-size 512 --ubatch-size 512 --temp 0.7 --top-p 0.9 --top-k 50 --host 0.0.0.0 --port 8080 !GPU!
exit /b
