$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
Set-Location $root

Write-Host ""
Write-Host "============================================"
Write-Host " Forest AI app launcher"
Write-Host "============================================"
Write-Host ""
Write-Host "Keep this black window open while using the app."
Write-Host ""

$py = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$sitePackages = Join-Path $root ".venv\Lib\site-packages"
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

if (!(Test-Path $py)) {
    Write-Host "[ERROR] Python was not found:"
    Write-Host $py
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

if (Test-Path $sitePackages) {
    $env:PYTHONPATH = $sitePackages
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
& $py -c "import streamlit, geopandas, rasterio, sklearn; print('packages ok')"

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
& $py -m streamlit run $app --server.port $port --server.address 0.0.0.0

Write-Host ""
Write-Host "The app has stopped."
Read-Host "Press Enter to close"
