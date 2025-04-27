<#
    ParseMarkdownContent.ps1 - Enhanced version with BOM removal and junk character protections
    This script extracts markdown content representing a file structure from an LLM response 
    (read from markdown.txt) and re-creates the corresponding files and folders in the current directory,
    while eliminating unwanted junk characters and ensuring that files are saved without a BOM.
#>

# Set up the script directory as the base directory.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$baseDir = $scriptDir
$logFilePath = Join-Path -Path $scriptDir -ChildPath 'script.log'

# Function to log messages with a timestamp.
function Write-Log {
    param (
        [string]$message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $message"
    $logMessage | Out-File -Append -FilePath $logFilePath
}

# Function to sanitize individual path components (filenames or folder names).
function Sanitize-PathComponent {
    param (
        [string]$pathComponent
    )
    # Replace illegal filename characters with an underscore.
    $sanitizedComponent = $pathComponent -replace '[<>:"/\\|?*]', '_'
    # Remove control characters (these include non-printable characters).
    $sanitizedComponent = $sanitizedComponent -replace '\p{C}', ''
    # Trim leading and trailing whitespace.
    $sanitizedComponent = $sanitizedComponent.Trim()
    return $sanitizedComponent
}

# Function to sanitize file content and input strings.
function Sanitize-FileContent {
    param (
        [string]$content
    )
    # Remove a BOM if present. The BOM (Byte Order Mark) in UTF-8 is represented as 0xFEFF.
    if ($content.StartsWith([char]0xFEFF)) {
        $content = $content.Substring(1)
    }
    # Remove problematic control characters (while keeping newline and carriage return intact).
    $sanitizedContent = $content -replace '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', ''
    # Trim extra spaces and trailing newlines.
    $sanitizedContent = $sanitizedContent.TrimEnd()
    return $sanitizedContent
}

# Helper function that takes a file path string and returns a hashtable with resolved Directory and FileName.
function Resolve-FilePath {
    param (
        [string]$FilePathString
    )
    # Remove any wrapping backticks or quotes and sanitize the string.
    $trimmed = $FilePathString.Trim("``""")
    $trimmed = Sanitize-FileContent -content $trimmed
    if ($trimmed -match '[\\/]+') {
        $parts = $trimmed -split '[\\/]'
        $fileName = Sanitize-PathComponent -pathComponent $parts[-1]
        $dir = $baseDir
        if ($parts.Length -gt 1) {
            for ($i = 0; $i -lt $parts.Length - 1; $i++) {
                $child = Sanitize-PathComponent -pathComponent $parts[$i]
                $dir = Join-Path -Path $dir -ChildPath $child
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

    # Sanitize the overall markdown content.
    $markdownContent = Sanitize-FileContent -content $markdownContent
    Write-Log "Initial markdown content sanitized."
    $lines = $markdownContent -split "`n"

    # Initialize state variables.
    $insideCodeBlock = $false
    $fileContent = ""
    $fileName = $null
    $currentDir = $baseDir

    Write-Log "Starting parsing of markdown content."

    # Use an index-based loop to allow lookahead.
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = Sanitize-FileContent -content $lines[$i]
        Write-Log "Processing line: ${line}"
        Write-Log "State: insideCodeBlock=${insideCodeBlock}, currentDir=${currentDir}, fileName=${fileName}"

        # Detect code fences (triple backticks) which may optionally specify the filename.
        if ($line -match '^```\s*(\S*)\s*$') {
            if (-not $insideCodeBlock) {
                # Start of a code block.
                $insideCodeBlock = $true
                if ($matches[1]) {
                    # Only treat the identifier as a filename if it contains a period.
                    if ($matches[1] -match '\.') {
                        $resolved = Resolve-FilePath -FilePathString $matches[1]
                        $fileName = $resolved.FileName
                        $currentDir = $resolved.Directory
                        Write-Log "Detected filename on opening code block: ${fileName}, directory set to: ${currentDir}"
                    }
                    else {
                        Write-Log "Ignoring identifier after backticks (likely language specifier): $($matches[1])"
                    }
                }
                else {
                    # Look ahead: if the next line exists and contains a period, treat it as the filename.
                    if ($i + 1 -lt $lines.Length) {
                        $nextLine = Sanitize-FileContent -content $lines[$i + 1]
                        if ($nextLine -and ($nextLine -match '\.')) {
                            $resolved = Resolve-FilePath -FilePathString $nextLine
                            $fileName = $resolved.FileName
                            $currentDir = $resolved.Directory
                            Write-Log "Detected filename on next line after opening backticks: ${fileName}, directory set to: ${currentDir}"
                            $i++  # Skip the line used for the filename.
                        }
                        else {
                            Write-Log "Skipping next line as filename because it does not appear valid."
                        }
                    }
                }
            }
            else {
                # End of the code block.
                $insideCodeBlock = $false
                if ($fileName -and $fileContent -ne "") {
                    # Ensure the target directory exists.
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
                    $fileContent = Sanitize-FileContent -content $fileContent
                    Write-Log "Writing file: ${filePath}"
                    Write-Log "Sanitized file content: ${fileContent}"
                    try {
                        # Write without BOM using .NET's WriteAllText with UTF8Encoding with BOM disabled.
                        [System.IO.File]::WriteAllText($filePath, $fileContent, (New-Object System.Text.UTF8Encoding -ArgumentList $False))
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

        # If inside a code block, accumulate the sanitized content.
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
        $fileContent = Sanitize-FileContent -content $fileContent
        Write-Log "Writing unclosed file: ${filePath}"
        try {
            [System.IO.File]::WriteAllText($filePath, $fileContent, (New-Object System.Text.UTF8Encoding -ArgumentList $False))
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
    try {
        # Read the markdown file with explicit UTF-8 encoding and sanitize its content.
        $markdownContent = Get-Content -Path $markdownFilePath -Raw -Encoding utf8
        $markdownContent = Sanitize-FileContent -content $markdownContent
        Write-Log "Read and sanitized markdown content."
        Parse-MarkdownContent -markdownContent $markdownContent
    }
    catch {
        Write-Log "Error reading markdown file: ${markdownFilePath} - Exception: ${_}"
    }
}
else {
    Write-Log "Error: File 'markdown.txt' not found in the script directory."
    Write-Output "Error: File 'markdown.txt' not found in the script directory."
}

Write-Log "Script finished."
