# Order Flow Radar - Institutional Clean Boot V2.1
# ScriptMasterLabs - Integrity Enforcement
# Build: Inst-v2.1 | Stabilization Hardened

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  ORDER FLOW RADAR: INSTITUTIONAL CLEAN BOOT   " -ForegroundColor Cyan
Write-Host "  Build: Inst-v2.1                              " -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host ""

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "Boot initiated: $timestamp" -ForegroundColor Gray

# --- Phase 1: Kill Stale Processes ---
$procNames = @("python", "uvicorn", "node")
Write-Host "[Phase 1] Terminating stale financial processes..." -ForegroundColor Yellow
foreach ($name in $procNames) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($procs) {
        Write-Host "  > Killing $($procs.Count) instances of ${name}..."
        Stop-Process -Name $name -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "  > ${name} - CLEAR" -ForegroundColor DarkGray
    }
}
Write-Host "  Phase 1 complete." -ForegroundColor Green

# --- Phase 2: Port Audit ---
$ports = @(8000, 8001, 8080, 8183)
Write-Host "[Phase 2] Verifying port availability..." -ForegroundColor Yellow
foreach ($port in $ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        Write-Host "  > CONFLICT on port ${port} (PID $($conn.OwningProcess)). Forcing closure..."
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "  > Port ${port} - CLEAR" -ForegroundColor DarkGray
    }
}
Write-Host "  Phase 2 complete." -ForegroundColor Green

# --- Phase 3: Stale Data Purge (V2.1 NEW) ---
Write-Host "[Phase 3] Purging stale pre-market contamination data..." -ForegroundColor Yellow
$purgeTargets = @(
    "scanner.log",
    "final_launch.log"
)
foreach ($file in $purgeTargets) {
    $path = Join-Path (Get-Location) $file
    if (Test-Path $path) {
        $size = (Get-Item $path).Length
        Remove-Item $path -Force
        $sizeKB = [math]::Round($size/1024, 1)
        Write-Host "  > PURGED ${file} (${sizeKB} KB)"
    } else {
        Write-Host "  > ${file} - NOT FOUND (clean)" -ForegroundColor DarkGray
    }
}
# Clear __pycache__ for fresh module compilation
$cacheDirs = @("__pycache__", "modules\__pycache__")
foreach ($dir in $cacheDirs) {
    $path = Join-Path (Get-Location) $dir
    if (Test-Path $path) {
        Remove-Item $path -Recurse -Force
        Write-Host "  > PURGED ${dir} (bytecode cache)"
    }
}
Write-Host "  Phase 3 complete." -ForegroundColor Green

# --- Phase 4: Socket Cooling Period ---
$cooldown = 20
Write-Host "[Phase 4] Socket Cooling Period - ${cooldown} seconds..." -ForegroundColor Cyan
Write-Host "  (Allowing Alpaca/Polygon to acknowledge session closure)"
for ($i = $cooldown; $i -gt 0; $i--) {
    Write-Host -NoNewline "`r  Countdown: $i seconds remaining...   "
    Start-Sleep -Seconds 1
}
Write-Host ""
Write-Host "  Phase 4 complete." -ForegroundColor Green

# --- Phase 5: Version Stamp + Launch ---
Write-Host "[Phase 5] Launching Institutional Orchestrator..." -ForegroundColor Green
Write-Host "  Version: Inst-v2.1"
Write-Host "  Feed: IEX (Standard)"
Write-Host "  IEX Normalizer: 1.5x"
Write-Host "  Discord Queue: Sequential (1.5s metering)"
Write-Host "  AI Auditor: Feed-Aware"

Start-Process -FilePath "python.exe" -ArgumentList "main.py" -WorkingDirectory (Get-Location)

$launchTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host ""
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  BOOT COMPLETE: ALL MONITORS ACTIVE" -ForegroundColor Green
Write-Host "  Build: Inst-v2.1 | Time: ${launchTime}" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan
