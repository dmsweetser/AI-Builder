<#
    DEPRECATED - use ai_builder.py instead, which has built-in utility functions for this purpose
    
    ParseAppContent.ps1 - Modified version
    This script extracts all the app content in a directory (using the current working directory as the root)
    with options to either exclude or include specified patterns.
#>

# Define the output file
$outputFile = "output.txt"

# List of specific filenames to exclude or include
$patterns = @(
    "package-lock.json",
    "ParseAppContent.ps1",
    "ParseMarkdownContent.ps1",
    "output.txt",
    "markdown.txt"
)

# Mode: "exclude" or "include"
$mode = "exclude" # Change this to "include" if you want to switch modes

# Remove the output file if it exists
if (Test-Path $outputFile) {
    Remove-Item $outputFile -Force
}

# Function to parse .gitignore rules from a directory
function Parse-GitIgnore {
    param (
        [string]$directory
    )
    $gitignorePath = Join-Path $directory ".gitignore"
    if (Test-Path $gitignorePath) {
        Get-Content $gitignorePath |
            Where-Object { $_ -and $_ -notmatch '^\s*#' } |
            ForEach-Object { $_.Trim() }
    }
    else {
        @()
    }
}

# Function to decide if a file should be excluded or included based on the mode
function ShouldProcessFile {
    param (
        [string]$path,
        [array]$rules,
        [array]$patterns,
        [string]$mode
    )
    $fileName = Split-Path $path -Leaf

    # Check against .gitignore patterns
    foreach ($rule in $rules) {
        if ($rule -like '*/*') {
            $escapedRule = $rule.Replace('/', [IO.Path]::DirectorySeparatorChar)
            if ($path -like "*$escapedRule*") {
                return ($mode -eq "exclude")
            }
        }
        elseif ($path -like "*$rule*") {
            return ($mode -eq "exclude")
        }
    }

    # Check if the filename is in the patterns list
    if ($patterns -contains $fileName) {
        return ($mode -eq "include")
    }

    # Check if any of the patterns are part of the filename
    foreach ($pattern in $patterns) {
        if ($fileName -like "*$pattern*") {
            return ($mode -eq "include")
        }
    }

    return ($mode -ne "include")
}

# Recursive function to process directories and files
function Process-Directory {
    param (
        [string]$directory,
        [array]$parentRules
    )
    # Combine parent's .gitignore rules with the current directory's rules
    $currentRules = Parse-GitIgnore -directory $directory
    $allRules = $parentRules + $currentRules

    # Process files in the current directory
    Get-ChildItem -Path $directory -File | ForEach-Object {
        $relativePath = $_.FullName.Substring((Get-Location).Path.Length + 1)
        if (ShouldProcessFile -path $relativePath -rules $allRules -patterns $patterns -mode $mode) {
            try {
                $content = Get-Content $_.FullName -ErrorAction Stop
                # Write file name as a header with markdown formatting
                Add-Content -Path $outputFile -Value "`n### $relativePath`n"
                Add-Content -Path $outputFile -Value "``````"
                # Write file content to the output file
                Add-Content -Path $outputFile -Value $content
                Add-Content -Path $outputFile -Value "``````"
            }
            catch {
                Write-Host "Skipped unreadable file: $relativePath"
            }
        }
    }

    # Process subdirectories recursively
    Get-ChildItem -Path $directory -Directory | ForEach-Object {
        Process-Directory -directory $_.FullName -parentRules $allRules
    }
}

# Start processing in the current directory
Process-Directory -directory (Get-Location).Path -parentRules @()
Write-Host "Processing completed. Check the output in $outputFile."
