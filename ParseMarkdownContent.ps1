<#
    ParseMarkdownContent.ps1 - https://github.com/dmsweetser/Toolkit
    This script extracts markdown content representing a file structure from an LLM response 
    (read from markdown.txt) and re-creates the corresponding files and folders in the current directory.
#>

# Set up the script directory as the base directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$baseDir = $scriptDir
$logFilePath = Join-Path -Path $scriptDir -ChildPath 'script.log'

# Function to log messages with a timestamp using ${} syntax for variable interpolation.
function Write-Log {
    param (
        [string]$message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] ${message}"
    $logMessage | Out-File -Append -FilePath $logFilePath
}

# Function to sanitize individual path components (filenames or folder names)
function Sanitize-PathComponent {
    param (
        [string]$pathComponent
    )
    # Replace illegal characters with underscores and remove control characters
    $sanitizedComponent = $pathComponent -replace '[<>:"/\\|?*]', '_'
    $sanitizedComponent = $sanitizedComponent -replace '\p{C}', ''
    $sanitizedComponent = $sanitizedComponent -replace '^(# `)', ''
    return $sanitizedComponent
}

# Helper function that takes a file path string (which might include forward/backslashes)
# and returns a hashtable with the resolved Directory (relative to $baseDir) and FileName.
function Resolve-FilePath {
    param (
        [string]$FilePathString
    )
    # Trim any wrapping backticks or quotes
    $trimmed = $FilePathString.Trim("``""")
    if ($trimmed -match '[\\/]+') {
        $parts = $trimmed -split '[\\/]'
        $fileName = Sanitize-PathComponent -pathComponent $parts[-1]
        $dir = $baseDir
        if ($parts.Length -gt 1) {
            for ($i = 0; $i -lt $parts.Length - 1; $i++) {
                $dir = Join-Path -Path $dir -ChildPath (Sanitize-PathComponent -pathComponent $parts[$i])
            }
        }
    }
    else {
        $fileName = Sanitize-PathComponent -pathComponent $trimmed
        $dir = $baseDir
    }
    return @{ Directory = $dir; FileName = $fileName }
}

# Function to parse the markdown content and create files/folders accordingly.
function Parse-MarkdownContent {
    param (
        [string]$markdownContent
    )

    Write-Log "Initial markdown content: ${markdownContent}"
    $lines = $markdownContent -split "`n"

    # Initialize state variables
    $insideCodeBlock = $false
    $fileContent = ""
    $fileName = $null
    $currentDir = $baseDir

    Write-Log "Starting parsing of markdown content."

    # Use an index-based loop for lookahead capability.
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i].TrimEnd()
        Write-Log "Processing line: ${line}"
        Write-Log "State: insideCodeBlock=${insideCodeBlock}, currentDir=${currentDir}, fileName=${fileName}"

        # Detect code fences (triple backticks) which may specify the filename.
        if ($line -match '^```\s*(\S*)\s*$') {
            if (-not $insideCodeBlock) {
                # Start of a code block.
                $insideCodeBlock = $true
                if ($matches[1]) {
                    # Only treat the matched string as a filename if it contains a period.
                    if ($matches[1] -match '\.') {
                        $resolved = Resolve-FilePath -FilePathString $matches[1]
                        $fileName = $resolved.FileName
                        $currentDir = $resolved.Directory
                        Write-Log "Detected filename on opening code block: ${fileName}, directory set to: ${currentDir}"
                    }
                    else {
                        Write-Log "Ignoring identifier after backticks (likely a language specifier): $($matches[1])"
                    }
                }
                else {
                    # Look ahead: if the next line exists and isn’t a closing code fence, treat it as the filename if it contains a period.
                    if ($i + 1 -lt $lines.Length) {
                        $nextLine = $lines[$i + 1].Trim()
                        if ($nextLine -and ($nextLine -match '\.')) {
                            $resolved = Resolve-FilePath -FilePathString $nextLine
                            $fileName = $resolved.FileName
                            $currentDir = $resolved.Directory
                            Write-Log "Detected filename on next line after opening backticks: ${fileName}, directory set to: ${currentDir}"
                            $i++  # Skip the line used for the filename.
                        }
                        else {
                            Write-Log "Skipping line after opening backticks as filename because it does not contain a period."
                        }
                    }
                }
            }
            else {
                # End of the code block.
                $insideCodeBlock = $false
                if ($fileName -and $fileContent -ne "") {
                    # Ensure the target directory exists before writing the file.
                    if (-not (Test-Path -Path $currentDir)) {
                        Write-Log "Creating directory: ${currentDir}"
                        try {
                            New-Item -ItemType Directory -Path $currentDir -Force | Out-Null
                            Write-Log "Successfully created directory: ${currentDir}"
                        }
                        catch {
                            Write-Log "Error creating directory: ${currentDir} - Exception: ${_}"
                        }
                    }
                    $filePath = Join-Path -Path $currentDir -ChildPath $fileName
                    Write-Log "Writing file: ${filePath}"
                    Write-Log "File content: ${fileContent}"
                    try {
                        # Use .NET file writing to avoid BOM issues.
                        $utf8NoBOM = New-Object System.Text.UTF8Encoding($false)
                        [System.IO.File]::WriteAllText($filePath, $fileContent, $utf8NoBOM)
                        if (Test-Path -Path $filePath) {
                            Write-Log "File created: ${filePath}"
                        }
                    }
                    catch {
                        Write-Log "Error writing file: ${filePath} - Exception: ${_}"
                    }
                }
                else {
                    Write-Log "Code block ended without filename or content."
                }
                # Reset variables for the next file block.
                $fileContent = ""
                $fileName = $null
            }
            continue
        }

        # Outside any code block, check if the line is a header specifying the file path.
        if (-not $insideCodeBlock) {
            if ($line -match '^###\s*`?(.+?)`?\s*$') {
                $resolved = Resolve-FilePath -FilePathString ($matches[1].Trim())
                $fileName = $resolved.FileName
                $currentDir = $resolved.Directory
                Write-Log "Detected header filename: ${fileName}, setting directory: ${currentDir}"
                continue
            }
        }

        # If inside a code block, accumulate the content (even if the line is empty).
        if ($insideCodeBlock -and $fileName) {
            Write-Log "Appending to file content for ${fileName}: ${line}"
            $fileContent += $line + "`n"
        }
    }

    # If the markdown ended while still inside a code block, write the pending file content.
    if ($insideCodeBlock -and $fileName -and $fileContent -ne "") {
        Write-Log "Finalizing unclosed code block for file: ${fileName}"
        if (-not (Test-Path -Path $currentDir)) {
            Write-Log "Creating directory for unclosed block: ${currentDir}"
            try {
                New-Item -ItemType Directory -Path $currentDir -Force | Out-Null
                Write-Log "Created directory: ${currentDir}"
            }
            catch {
                Write-Log "Error creating directory: ${currentDir} - Exception: ${_}"
            }
        }
        $filePath = Join-Path -Path $currentDir -ChildPath $fileName
        Write-Log "Writing unclosed file: ${filePath}"
        try {
            # Use .NET file writing to avoid BOM issues.
            $utf8NoBOM = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($filePath, $fileContent, $utf8NoBOM)
            if (Test-Path -Path $filePath) {
                Write-Log "File created: ${filePath}"
            }
        }
        catch {
            Write-Log "Error writing file: ${filePath} - Exception: ${_}"
        }
    }

    Write-Log "Parsing completed."
}

# Log the script start.
Write-Log "Script started."

# Locate the markdown file (markdown.txt) in the script directory.
$markdownFilePath = Join-Path -Path $scriptDir -ChildPath 'markdown.txt'
Write-Log "Markdown file path: ${markdownFilePath}"

if (Test-Path -Path $markdownFilePath) {
    Write-Log "Found markdown file: ${markdownFilePath}"
    $markdownContent = Get-Content -Path $markdownFilePath -Raw
    Write-Log "Read markdown content."
    Parse-MarkdownContent -markdownContent $markdownContent
}
else {
    Write-Log "Error: File 'markdown.txt' not found in the script directory."
    Write-Output "Error: File 'markdown.txt' not found in the script directory."
}

Write-Log "Script finished."
