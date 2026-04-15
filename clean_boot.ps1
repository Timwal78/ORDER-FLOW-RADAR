# Order Flow Radar — Institutional Clean Boot
# ScriptMasterLabs — Integrity Enforcement

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  ORDER FLOW RADAR: INSTITUTIONAL CLEAN BOOT  " -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# 1. Kill stale processes
$procNames = @("python", "uvicorn", "node")
Write-Host "Audit: Terminating stale financial processes..." -ForegroundColor Yellow
foreach ($name in $procNames) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($procs) {
        Write-Host "  Killing $($procs.Count) instances of $name..."
        Stop-Process -Name $name -Force -ErrorAction SilentlyContinue
    }
}

# 2. Port Audit
$ports = @(8000, 8001, 8183, 8080)
Write-Host "Audit: Verifying port availability..." -ForegroundColor Yellow
foreach ($port in $ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        Write-Host "  Conflict found on port $port. Forcing closure of PID $($conn.OwningProcess)..."
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

# 3. Socket Cooling Period (Alpaca Rule)
$cooldown = 20
Write-Host "Stabilization: Initiating $cooldown-second Socket Cooling Period..." -ForegroundColor Cyan
Write-Host "  (Allowing Alpaca/Polygon to acknowledge session closure)"
for ($i = $cooldown; $i -gt 0; $i--) {
    Write-Host -NoNewline "`r  Time remaining: $i seconds... "
    Start-Sleep -Seconds 1
}
Write-Host "`n"

# 4. Launch
Write-Host "Operational: Launching Institutional Orchestrator..." -ForegroundColor Green
# Using absolute path to python Scripts if needed, but 'python' should work in user environment
Start-Process -FilePath "python.exe" -ArgumentList "main.py" -WorkingDirectory (Get-Location)

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  BOOT COMPLETE: MONITORS ACTIVE             " -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
