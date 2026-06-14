$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
Set-Location $root

function Test-PythonCandidate {
    param(
        [string]$Exe,
        [string[]]$Args = @()
    )
    try {
        $version = & $Exe @Args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}') " 2>$null
        if ($LASTEXITCODE -eq 0 -and $version) {
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

function Select-Python {
    $candidates = @(
        @{ Exe = (Join-Path $root "python\python.exe"); Args = @() },
        @{ Exe = (Join-Path $root ".venv\Scripts\python.exe"); Args = @() },
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() },
        @{ Exe = "python3"; Args = @() },
        @{ Exe = (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"); Args = @() }
    )

    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -Exe $candidate.Exe -Args $candidate.Args) {
            return $candidate
        }
    }
    return $null
}

function Invoke-AppPython {
    param([string[]]$Args)
    & $script:pythonExe @script:pythonArgs @Args
}

Write-Host ""
Write-Host "============================================"
Write-Host " Forest AI API launcher"
Write-Host "============================================"
Write-Host ""

$python = Select-Python
if (-not $python) {
    Write-Host "[ERROR] Python was not found."
    Write-Host "Install Python 3.12 from https://www.python.org/downloads/ and check 'Add python.exe to PATH'."
    Write-Host "Then run this file again."
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

$script:pythonExe = $python.Exe
$script:pythonArgs = $python.Args
$sitePackages = Join-Path $root ".venv\Lib\site-packages"
$venvScripts = Join-Path $root ".venv\Scripts"

if (Test-Path $sitePackages) {
    if ($env:PYTHONPATH) {
        $env:PYTHONPATH = "$sitePackages;$env:PYTHONPATH"
    } else {
        $env:PYTHONPATH = $sitePackages
    }
}
if (Test-Path $venvScripts) {
    $env:PATH = "$venvScripts;$env:PATH"
}

Write-Host "[1/2] Checking packages..."
Invoke-AppPython -Args @("-c", "import fastapi, uvicorn; print('packages ok')") 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Required packages are missing. Installing them now..."
    Invoke-AppPython -Args @("-m", "pip", "install", "-r", "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[ERROR] Package installation failed."
        Write-Host "Check your internet connection, then run this file again."
        Write-Host ""
        Read-Host "Press Enter to close"
        exit 1
    }
}

Write-Host "[2/2] API starting: http://localhost:8000"
Write-Host "Docs: http://localhost:8000/docs"
Write-Host ""
Invoke-AppPython -Args @("-m", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000")

Write-Host ""
Write-Host "The API has stopped."
Read-Host "Press Enter to close"
