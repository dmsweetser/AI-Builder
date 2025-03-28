<#
    ParseMarkdownContent.ps1 - 
    This script extracts all the markdown content (that represents file structure and file content)
    from an exported LLM response (markdown.txt) and re-creates the files and folders
    in the current directory.
#>

# Set up the script directory and base directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$baseDir = $scriptDir
$logFilePath = Join-Path -Path $scriptDir -ChildPath 'script.log'

# Function to log messages with a timestamp
function Write-Log {
    param (
        [string]$message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $message"
    $logMessage | Out-File -Append -FilePath $logFilePath
}

# Function to sanitize a single path component (e.g. a filename or folder name)
function Sanitize-PathComponent {
    param (
        [string]$pathComponent
    )
    # Replace illegal characters with underscores and remove control characters
    $sanitizedComponent = $pathComponent -replace '[<>:"/\\|?*]', '_'
    $sanitizedComponent = $sanitizedComponent -replace '\p{C}', ''
    return $sanitizedComponent
}

# Function to parse the markdown content and create files/folders accordingly
function Parse-MarkdownContent {
    param (
        [string]$markdownContent
    )

    Write-Log "Initial markdown content: $markdownContent"
    $lines = $markdownContent -split "`n"

    # Initialize parser state
    $insideCodeBlock = $false
    $fileContent = ""
    $fileName = $null
    $currentDir = $baseDir

    Write-Log "Starting parsing of markdown content."

    # Use an index-based loop to enable lookahead when needed
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i].TrimEnd()
        Write-Log "Processing line: $line"
        Write-Log "State: insideCodeBlock=$insideCodeBlock, currentDir=$currentDir, fileName=$fileName"

        # Detect triple-backticks (which may include a filename)
        if ($line -match '^```\s*(\S*)\s*$') {
            if (-not $insideCodeBlock) {
                # Beginning of a code block
                $insideCodeBlock = $true
                if ($matches[1]) {
                    # Filename provided on the same line as the opening backticks
                    $fileName = Sanitize-PathComponent -pathComponent $matches[1]
                    Write-Log "Detected filename on opening code block: $fileName"
                }
                else {
                    # Look ahead: if the next line exists and it isn’t another triple backticks
                    if ($i + 1 -lt $lines.Length) {
                        $nextLine = $lines[$i+1].Trim()
                        if ($nextLine -and -not ($nextLine -match '^```')) {
                            $fileName = Sanitize-PathComponent -pathComponent $nextLine
                            Write-Log "Detected filename on next line after opening backticks: $fileName"
                            $i++  # Skip the line containing the filename
                        }
                    }
                }
            }
            else {
                # End of the code block
                $insideCodeBlock = $false
                if ($fileName -and $fileContent -ne "") {
                    # Ensure the target directory exists
                    if (-not (Test-Path -Path $currentDir)) {
                        Write-Log "Creating directory: $currentDir"
                        try {
                            New-Item -ItemType Directory -Path $currentDir -Force | Out-Null
                            Write-Log "Successfully created directory: $currentDir"
                        }
                        catch {
                            Write-Log "Error creating directory: $currentDir - Exception: $_"
                        }
                    }
                    $filePath = Join-Path -Path $currentDir -ChildPath $fileName
                    Write-Log "Writing file: $filePath"
                    Write-Log "File content: $fileContent"
                    try {
                        $fileContent | Out-File -FilePath $filePath -Encoding utf8
                        if (Test-Path -Path $filePath) {
                            Write-Log "File created: $filePath"
                        }
                    }
                    catch {
                        Write-Log "Error writing file: $filePath - Exception: $_"
                    }
                }
                else {
                    Write-Log "Code block ended without filename or content."
                }
                # Reset variables for next file block
                $fileContent = ""
                $fileName = $null
            }
            continue
        }

        # If not inside a code block, check if the line is a header that specifies the file path
        if (-not $insideCodeBlock) {
            if ($line -match '^###\s*`?(.+?)`?\s*$') {
                $fileFullPath = $matches[1].Trim()
                $filePathComponents = $fileFullPath.Split("/")
                $fileName = Sanitize-PathComponent -pathComponent $filePathComponents[-1]
                if ($filePathComponents.Length -gt 1) {
                    # Build full directory path by combining the base directory with given components
                    $relativeDir = $baseDir
                    foreach ($component in $filePathComponents[0..($filePathComponents.Length - 2)]) {
                        $relativeDir = Join-Path -Path $relativeDir -ChildPath (Sanitize-PathComponent -pathComponent $component)
                    }
                    $currentDir = $relativeDir
                }
                else {
                    $currentDir = $baseDir
                }
                Write-Log "Detected header filename: $fileName, setting directory: $currentDir"
                continue
            }
        }

        # When inside a code block and a filename is already established, accumulate the file content.
        if ($insideCodeBlock -and $fileName) {
            Write-Log "Appending to file content for $fileName: $line"
            $fileContent += $line + "`n"
        }
    }

    # If the markdown ended while a code block was still open, write the pending file
    if ($insideCodeBlock -and $fileName -and $fileContent -ne "") {
        Write-Log "Finalizing unclosed code block for file: $fileName"
        if (-not (Test-Path -Path $currentDir)) {
            Write-Log "Creating directory for unclosed block: $currentDir"
            try {
                New-Item -ItemType Directory -Path $currentDir -Force | Out-Null
                Write-Log "Created directory: $currentDir"
            }
            catch {
                Write-Log "Error creating directory: $currentDir - Exception: $_"
            }
        }
        $filePath = Join-Path -Path $currentDir -ChildPath $fileName
        Write-Log "Writing unclosed file: $filePath"
        try {
            $fileContent | Out-File -FilePath $filePath -Encoding utf8
            if (Test-Path -Path $filePath) {
                Write-Log "File created: $filePath"
            }
        }
        catch {
            Write-Log "Error writing file: $filePath - Exception: $_"
        }
    }

    Write-Log "Parsing completed."
}

# Log that the script is starting
Write-Log "Script started."

# Locate the markdown file (markdown.txt) in the script directory
$markdownFilePath = Join-Path -Path $scriptDir -ChildPath 'markdown.txt'
Write-Log "Markdown file path: $markdownFilePath"

if (Test-Path -Path $markdownFilePath) {
    Write-Log "Found markdown file: $markdownFilePath"
    $markdownContent = Get-Content -Path $markdownFilePath -Raw
    Write-Log "Read markdown content."
    Parse-MarkdownContent -markdownContent $markdownContent
}
else {
    Write-Log "Error: File 'markdown.txt' not found in the script directory."
    Write-Output "Error: File 'markdown.txt' not found in the script directory."
}

Write-Log "Script finished."
