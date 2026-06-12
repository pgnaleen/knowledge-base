# start_eval_stack.ps1
# Starts three background services wired to the eval Pinecone index (kb-pipeline-eval):
#   :8003  eval KB-Pipeline  (PINECONE_INDEX=kb-pipeline-eval)
#   :8004  eval MCP server   (KB_PIPELINE_URL=http://localhost:8003)
#   :8001  backend           (MCP_SERVER_URL=http://localhost:8004/mcp)
#
# Usage:
#   .\testing\evaluation\start_eval_stack.ps1
#
# Then run:
#   python testing/evaluation/run_rag_eval.py
#
# When done:
#   .\testing\evaluation\stop_eval_stack.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT    = (Resolve-Path "$PSScriptRoot\..\..\..").Path   # project root
$LOG_DIR = "$PSScriptRoot\logs"
$PID_FILE = "$PSScriptRoot\eval_stack.pids"

# ── Parse .env.eval ───────────────────────────────────────────────────────────
$ENV_FILE = "$PSScriptRoot\.env.eval"
if (-not (Test-Path $ENV_FILE)) {
    Write-Error "Missing $ENV_FILE — cannot start eval stack."
    exit 1
}

$evalEnv = @{}
Get-Content $ENV_FILE | Where-Object { $_ -match '^\s*[^#\s]' -and $_ -match '=' } | ForEach-Object {
    $parts = $_ -split '=', 2
    if ($parts.Count -eq 2) { $evalEnv[$parts[0].Trim()] = $parts[1].Trim() }
}

# ── Set environment variables (inherited by all child processes below) ─────────
$env:PINECONE_INDEX       = $evalEnv["PINECONE_INDEX"]
$env:PINECONE_API_KEY     = $evalEnv["PINECONE_API_KEY"]
$env:PINECONE_ENVIRONMENT = if ($evalEnv.ContainsKey("PINECONE_ENVIRONMENT")) { $evalEnv["PINECONE_ENVIRONMENT"] } else { "us-east-1" }
$env:DATABASE_URL         = if ($evalEnv.ContainsKey("DATABASE_URL"))   { $evalEnv["DATABASE_URL"]   } else { "" }
$env:OPENAI_API_KEY       = if ($evalEnv.ContainsKey("OPENAI_API_KEY")) { $evalEnv["OPENAI_API_KEY"] } else { "" }
$env:KB_PIPELINE_URL      = "http://localhost:8003"   # MCP server points here
$env:MCP_PORT             = "8004"                    # eval MCP server port
$env:MCP_SERVER_URL       = "http://localhost:8004/mcp"  # backend points here

# ── Create log directory ───────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  SG Property AI — Eval Stack Startup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Pinecone index : $($env:PINECONE_INDEX)" -ForegroundColor Yellow
Write-Host "  KB-Pipeline    : http://localhost:8003"
Write-Host "  MCP server     : http://localhost:8004"
Write-Host "  Backend        : http://localhost:8001"
Write-Host "  Logs           : $LOG_DIR"
Write-Host ""

# ── Helper: start a process and return it ─────────────────────────────────────
function Start-Service {
    param([string]$Label, [string]$Exe, [string]$Args, [string]$WorkDir, [string]$LogBase)
    Write-Host "[$Label] Starting..." -NoNewline
    $p = Start-Process -FilePath $Exe `
        -ArgumentList $Args `
        -WorkingDirectory $WorkDir `
        -NoNewWindow `
        -RedirectStandardOutput "$LOG_DIR\${LogBase}.log" `
        -RedirectStandardError  "$LOG_DIR\${LogBase}_err.log" `
        -PassThru
    Write-Host " PID $($p.Id)" -ForegroundColor Gray
    return $p
}

# ── 1. Eval KB-Pipeline on :8003 ──────────────────────────────────────────────
$kbProc = Start-Service `
    -Label "1/3 KB-Pipeline :8003" `
    -Exe "python" `
    -Args "-m uvicorn api.app:app --host 0.0.0.0 --port 8003" `
    -WorkDir "$ROOT\KB-Pipeline" `
    -LogBase "kb_eval"

# ── 2. Eval MCP server on :8004 ───────────────────────────────────────────────
$mcpProc = Start-Service `
    -Label "2/3 MCP server  :8004" `
    -Exe "python" `
    -Args "server.py" `
    -WorkDir "$ROOT\sg-property-agent\mcp-server" `
    -LogBase "mcp_eval"

# ── 3. Backend on :8001 ───────────────────────────────────────────────────────
$backendProc = Start-Service `
    -Label "3/3 Backend      :8001" `
    -Exe "python" `
    -Args "-m uvicorn server:app --host 0.0.0.0 --port 8001" `
    -WorkDir "$ROOT\sg-property-agent\backend" `
    -LogBase "backend_eval"

# ── Save PIDs ─────────────────────────────────────────────────────────────────
"$($kbProc.Id),$($mcpProc.Id),$($backendProc.Id)" | Set-Content -Path $PID_FILE -Encoding UTF8
Write-Host ""

# ── Wait for health ───────────────────────────────────────────────────────────
function Wait-ForHealth {
    param([string]$Url, [string]$Label, [int]$MaxSeconds = 90)
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    Write-Host "  Waiting for $Label" -NoNewline
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 2 -ErrorAction Stop
            if ($r.status -eq "ok") {
                Write-Host " OK" -ForegroundColor Green
                return $true
            }
        } catch {}
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
    }
    Write-Host " TIMEOUT" -ForegroundColor Red
    return $false
}

$kbOk      = Wait-ForHealth "http://localhost:8003/health" "KB-Pipeline (:8003)"
$backendOk = Wait-ForHealth "http://localhost:8001/health" "Backend     (:8001)"

Write-Host ""
if ($kbOk -and $backendOk) {
    # Verify the active Pinecone index
    try {
        $cfg = Invoke-RestMethod -Uri "http://localhost:8003/config" -Method Get -TimeoutSec 5
        Write-Host "  Active Pinecone index: $($cfg.pinecone_index)" -ForegroundColor $(if ($cfg.pinecone_index -eq $env:PINECONE_INDEX) { "Green" } else { "Red" })
        if ($cfg.pinecone_index -ne $env:PINECONE_INDEX) {
            Write-Host "  WARNING: Expected '$($env:PINECONE_INDEX)' but got '$($cfg.pinecone_index)'" -ForegroundColor Red
        }
    } catch {
        Write-Host "  Could not verify Pinecone index from /config endpoint" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Eval stack is ready!" -ForegroundColor Green
    Write-Host "  Run:   python testing/evaluation/run_rag_eval.py"
    Write-Host "  Stop:  .\testing\evaluation\stop_eval_stack.ps1"
} else {
    Write-Host "Some services failed to start. Check logs:" -ForegroundColor Red
    Write-Host "  $LOG_DIR"
    exit 1
}
