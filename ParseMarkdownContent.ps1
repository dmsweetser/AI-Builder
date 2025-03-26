# Function to log messages with timestamp
function Write-Log {
    param (
        [string]$message
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $message"
    $logMessage | Out-File -Append -FilePath $logFilePath
}

# Function to sanitize file names and individual path components
function Sanitize-PathComponent {
    param (
        [string]$pathComponent
    )
    # Replace illegal characters with underscores
    $sanitizedComponent = $pathComponent -replace '[<>:"/\\|?*]', '_'
    # Remove hidden control characters
    $sanitizedComponent = $sanitizedComponent -replace '\p{C}', ''
    return $sanitizedComponent
}

# Function to parse the directory structure and file contents
function Parse-MarkdownContent {
    param (
        [string]$markdownContent
    )

    $lines = $markdownContent -split "`n"
    Write-Log "Initial markdown content: $markdownContent"

    $currentDir = $baseDir
    $fileContent = $null
    $insideCodeBlock = $false

    Write-Log "Starting parsing of markdown content."

    foreach ($line in $lines) {
        Write-Log "Processing line: $line"
        Write-Log "Current state - insideCodeBlock: $insideCodeBlock, currentDir: $currentDir"

        if ($line -match '^```') {
            $insideCodeBlock = -not $insideCodeBlock
            Write-Log "Toggled code block state: $insideCodeBlock"
            if (-not $insideCodeBlock -and $fileContent) {
                # Ensure directory exists before writing
                if (-not (Test-Path -Path $currentDir)) {
                    Write-Log "Creating directory: $currentDir"
                    try {
                        New-Item -ItemType Directory -Path $currentDir -Force | Out-Null
                        Write-Log "Successfully created directory: $currentDir"
                    } catch {
                        Write-Log "Error creating directory: $currentDir - Exception: $_"
                    }
                }

                # Construct sanitized file path
                $filePath = Join-Path -Path $currentDir -ChildPath $fileName
                Write-Log "Final sanitized file path: $filePath"
                Write-Log "File content to write: $fileContent"

                if ($filePath -and $fileContent) {
                    try {
                        $fileContent | Out-File -FilePath $filePath -Encoding utf8
                        if (Test-Path -Path $filePath) {
                            Write-Log "File confirmed as created: $filePath"
                        } else {
                            Write-Log "Error: File creation failed: $filePath"
                        }
                    } catch {
                        Write-Log "Error writing file: $filePath - Exception: $_"
                    }
                } else {
                    Write-Log "Error: Invalid file path or empty content for file: $fileName"
                }
                $fileContent = $null
            }
            continue
        }

        # Adjusted parsing logic to handle filenames with or without backticks
        if (-not $insideCodeBlock) {
            if ($line -match '^###\s*`?(.+?)`?$') {
                $filePathComponents = $matches[1].Split("/")
                $fileName = Sanitize-PathComponent -pathComponent $filePathComponents[-1]
                $fileName = $fileName.Trim('`') # Ensure no trailing or leading backticks
                $relativeDir = if ($filePathComponents.Length -gt 1) {
                    $relativeDir = $baseDir
                    foreach ($component in $filePathComponents[0..($filePathComponents.Length - 2)]) {
                        $relativeDir = Join-Path -Path $relativeDir -ChildPath (Sanitize-PathComponent -pathComponent $component)
                    }
                    $relativeDir
                } else {
                    $baseDir
                }
                $currentDir = $relativeDir
                Write-Log "Detected sanitized file name: $fileName"
                Write-Log "Detected sanitized relative directory: $relativeDir"
                Write-Log "Updated current directory: $currentDir"
                continue
            }
        }

        if ($insideCodeBlock -and $fileName) {
            Write-Log "Appending content to file: $fileName"
            Write-Log "Line being appended: $line"
            $fileContent += $line + "`n"
        }
    }

    if ($fileContent) {
        if (-not (Test-Path -Path $currentDir)) {
            Write-Log "Creating directory for remaining file: $currentDir"
            try {
                New-Item -ItemType Directory -Path $currentDir -Force | Out-Null
                Write-Log "Successfully created directory: $currentDir"
            } catch {
                Write-Log "Error creating directory: $currentDir - Exception: $_"
            }
        }

        $filePath = Join-Path -Path $currentDir -ChildPath $fileName
        Write-Log "Final sanitized file path: $filePath"
        Write-Log "File content to write (remaining): $fileContent"

        if (-not [string]::IsNullOrWhiteSpace($fileContent)) {
            try {
                $fileContent | Out-File -FilePath $filePath -Encoding utf8
                if (Test-Path -Path $filePath) {
                    Write-Log "File confirmed as created: $filePath"
                } else {
                    Write-Log "Error: File creation failed: $filePath"
                }
            } catch {
                Write-Log "Error writing remaining file: $filePath - Exception: $_"
            }
        } else {
            Write-Log "Error: Content is empty or invalid for remaining file: $fileName"
        }
    }

    Write-Log "Parsing completed."
}

# Set up log file
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$baseDir = $scriptDir
$logFilePath = Join-Path -Path $scriptDir -ChildPath 'script.log'

Write-Log "Script started."

# Read the content from markdown.txt
$markdownFilePath = Join-Path -Path $scriptDir -ChildPath 'markdown.txt'

Write-Log "Markdown file path: $markdownFilePath"
if (Test-Path -Path $markdownFilePath) {
    Write-Log "Found markdown file: $markdownFilePath"
    $markdownContent = Get-Content -Path $markdownFilePath -Raw
    Write-Log "Read markdown content: $markdownContent"
    # Call the function with the content of markdown.txt
    Parse-MarkdownContent -markdownContent $markdownContent
} else {
    Write-Log "Error: File 'markdown.txt' not found in the script directory."
    Write-Output "Error: File 'markdown.txt' not found in the script directory."
}

Write-Log "Script finished."
