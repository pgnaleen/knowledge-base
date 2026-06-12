# stop_eval_stack.ps1
# Stops the eval service stack started by start_eval_stack.ps1.
#
# Usage:
#   .\testing\evaluation\stop_eval_stack.ps1

Set-StrictMode -Version Latest
$PID_FILE = "$PSScriptRoot\eval_stack.pids"

Write-Host ""
Write-Host "Stopping eval stack..." -ForegroundColor Cyan

$stopped = 0
$notFound = 0

# ── Method 1: kill by saved PIDs ──────────────────────────────────────────────
if (Test-Path $PID_FILE) {
    $pids = (Get-Content $PID_FILE).Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^\d+$' }
    foreach ($pid in $pids) {
        try {
            $proc = Get-Process -Id $pid -ErrorAction Stop
            Stop-Process -Id $pid -Force
            Write-Host "  Stopped PID $pid ($($proc.ProcessName))" -ForegroundColor Gray
            $stopped++
        } catch {
            Write-Host "  PID $pid not found (already stopped)" -ForegroundColor Gray
            $notFound++
        }
    }
    Remove-Item $PID_FILE -Force
    Write-Host ""
} else {
    Write-Host "  No PID file found — falling back to port-based cleanup" -ForegroundColor Yellow
}

# ── Method 2: kill by port (fallback / extra cleanup) ─────────────────────────
$evalPorts = @(8001, 8003, 8004)
foreach ($port in $evalPorts) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            try {
                $proc = Get-Process -Id $conn.OwningProcess -ErrorAction Stop
                Stop-Process -Id $conn.OwningProcess -Force
                Write-Host "  Stopped :$port  PID $($conn.OwningProcess) ($($proc.ProcessName))" -ForegroundColor Gray
                $stopped++
            } catch {}
        }
    } catch {}
}

if ($stopped -gt 0) {
    Write-Host "Eval stack stopped ($stopped process(es) terminated)." -ForegroundColor Green
} else {
    Write-Host "No running eval processes found." -ForegroundColor Yellow
}
Write-Host ""
