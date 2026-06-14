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
Write-Host " Forest AI app launcher"
Write-Host "============================================"
Write-Host ""
Write-Host "Keep this black window open while using the app."
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
$port = 8501
$localIp = $null

try {
    $localIp = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Select-Object -ExpandProperty IPAddress -First 1
} catch {
    $localIp = $null
}

if (-not $localIp) {
    try {
        $ipText = ipconfig | Select-String -Pattern "IPv4"
        foreach ($line in $ipText) {
            if ($line -match "(\d{1,3}(\.\d{1,3}){3})") {
                $candidate = $Matches[1]
                if ($candidate -notlike "127.*" -and $candidate -notlike "169.254.*") {
                    $localIp = $candidate
                    break
                }
            }
        }
    } catch {
        $localIp = $null
    }
}

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

Write-Host "[1/4] Closing old app on port $port..."
try {
    $oldPids = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($oldPid in $oldPids) {
        if ($oldPid -and $oldPid -ne $PID) {
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
            Write-Host "Closed old app process: $oldPid"
        }
    }
    Start-Sleep -Seconds 1
} catch {
    Write-Host "Could not close old app automatically. If the page does not change, close old black windows and run again."
}

Write-Host "[2/4] Checking packages..."
Invoke-AppPython -Args @("-c", "import streamlit, geopandas, rasterio, sklearn; print('packages ok')") 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Required packages are missing. Installing them now..."
    Write-Host "This can take several minutes on the first run."
    Invoke-AppPython -Args @("-m", "pip", "install", "-r", "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[ERROR] Package installation failed."
        Write-Host "Check your internet connection, then run this file again."
        Write-Host ""
        Read-Host "Press Enter to close"
        exit 1
    }

    Invoke-AppPython -Args @("-c", "import streamlit, geopandas, rasterio, sklearn; print('packages ok')")
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[ERROR] Packages are still not available after installation."
        Write-Host "Install Python 3.12, then run this file again."
        Write-Host ""
        Read-Host "Press Enter to close"
        exit 1
    }
}

Write-Host "[3/4] Opening browser..."
Start-Process "http://localhost:$port"

Write-Host "[4/4] Starting Streamlit..."
Write-Host ""
Write-Host "PC browser URL: http://localhost:$port"
if ($localIp) {
    Write-Host "Phone URL on the same Wi-Fi: http://$localIp`:$port"
    Write-Host "If Windows Firewall asks, allow access for this app."
} else {
    Write-Host "Phone URL could not be detected automatically. Check your PC IPv4 address and use http://PC_IP:$port"
}
Write-Host "If the browser still shows an error, wait 10 seconds and refresh."
Write-Host ""

$app = Join-Path $root "app\streamlit_app.py"
Invoke-AppPython -Args @("-m", "streamlit", "run", $app, "--server.port", "$port", "--server.address", "0.0.0.0")

Write-Host ""
Write-Host "The app has stopped."
Read-Host "Press Enter to close"
