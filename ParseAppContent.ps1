<#
    ParseAppContent.ps1 - https://github.com/dmsweetser/Toolkit
    This script extracts all the app content in a directory (using the current working directory as the root)
    except for files in a specified exclusion list and those matching any .gitignore rules.
#>

# Define the output file
$outputFile = "output.txt"

# List of specific filenames to exclude
$excludedFiles = @("package-lock.json", "ParseAppContent.ps1", "ParseMarkdownContent.ps1", "output.txt", "markdown.txt")

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

# Function to decide if a file should be excluded (by matching .gitignore rules or explicit exclusions)
function IsExcluded {
    param (
        [string]$path,
        [array]$rules,
        [array]$excludedFiles
    )

    $fileName = Split-Path $path -Leaf

    # Check against .gitignore patterns
    foreach ($rule in $rules) {
        # If the rule contains a slash, treat it as a directory or nested pattern
        if ($rule -like '*/*') {
            $escapedRule = $rule.Replace('/', [IO.Path]::DirectorySeparatorChar)
            if ($path -like "*$escapedRule*") {
                return $true
            }
        }
        elseif ($path -like "*$rule*") {
            return $true
        }
    }

    # Check if the filename is in the explicit exclusion list
    if ($excludedFiles -contains $fileName) {
        return $true
    }

    return $false
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
        # Compute relative path based on the current working directory
        $relativePath = $_.FullName.Substring((Get-Location).Path.Length + 1)
        if (-not (IsExcluded -path $relativePath -rules $allRules -excludedFiles $excludedFiles)) {
            try {
                $content = Get-Content $_.FullName -ErrorAction Stop
                # Write file content to the output file with a markdown code fence header
                Add-Content -Path $outputFile -Value "`n```````$(${relativePath})`n"
                Add-Content -Path $outputFile -Value $content
                Add-Content -Path $outputFile -Value "``````"
            }
            catch {
                Write-Host "Skipped unreadable file: ${relativePath}"
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

Write-Host "Processing completed. Check the output in ${outputFile}."
