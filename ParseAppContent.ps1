# Define the output file
$outputFile = "output.txt"

# List of specific filenames to exclude
$excludedFiles = @("package-lock.json")

# Remove the output file if it exists
if (Test-Path $outputFile) {
    Remove-Item $outputFile
}

# Function to parse .gitignore rules
function Parse-GitIgnore {
    param ([string]$directory)

    $gitignorePath = Join-Path $directory ".gitignore"
    if (Test-Path $gitignorePath) {
        Get-Content $gitignorePath | Where-Object { $_ -ne '' -and $_ -notmatch '^#' } | ForEach-Object {
            $_.Trim()
        }
    } else {
        @()
    }
}

# Function to check if a path matches `.gitignore` rules or excluded filenames
function IsExcluded {
    param (
        [string]$path,
        [array]$rules,
        [array]$excludedFiles
    )

    $fileName = Split-Path $path -Leaf

    # Check against `.gitignore` rules
    foreach ($rule in $rules) {
        if ($rule -like '*/*') {
            # Handle patterns like `**/node_modules`
            $escapedRule = $rule.Replace('/', '\\')
            if ($path -like "*$escapedRule*") {
                return $true
            }
        } elseif ($path -like "*$rule*") {
            return $true
        }
    }

    # Check if the filename is in the excluded files list
    if ($excludedFiles -contains $fileName) {
        return $true
    }

    return $false
}

# Recursive function to process files in directories
function Process-Directory {
    param (
        [string]$directory,
        [array]$parentRules
    )

    # Parse .gitignore rules for the current directory
    $currentRules = Parse-GitIgnore -directory $directory
    $allRules = $parentRules + $currentRules

    # Process files in the current directory
    Get-ChildItem -Path $directory -File | ForEach-Object {
        $relativePath = $_.FullName.Substring((Get-Location).Path.Length + 1)

        if (-not (IsExcluded -path $relativePath -rules $allRules -excludedFiles $excludedFiles)) {
            try {
                $content = Get-Content $_.FullName -ErrorAction Stop
                Add-Content -Path $outputFile -Value ("`n" + '```' + "[$relativePath]")
                Add-Content -Path $outputFile -Value $content
                Add-Content -Path $outputFile -Value '```'
            } catch {
                Write-Host "Skipped unreadable file: $relativePath"
            }
        }
    }

    # Process subdirectories recursively
    Get-ChildItem -Path $directory -Directory | ForEach-Object {
        Process-Directory -directory $_.FullName -parentRules $allRules
    }
}

# Start processing from the current directory
Process-Directory -directory (Get-Location).Path -parentRules @()

Write-Host "Processing completed. Check the output in $outputFile."
