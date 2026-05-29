# Setup script for Property Advisory AI Agent
# Copies all .env.example files to .env (if .env doesn't already exist)

Write-Host "🚀 Setting up Property Advisory AI Agent..." -ForegroundColor Cyan
Write-Host ""

$envExamples = @(
    "KB-Pipeline\.env.example",
    "sg-property-agent\backend\.env.example",
    "sg-property-agent\frontend\.env.example",
    "sg-property-agent\mcp-server\.env.example"
)

$created = @()
$skipped = @()

foreach ($example in $envExamples) {
    $envFile = $example -replace "\.example$", ""

    if (Test-Path $example) {
        if (Test-Path $envFile) {
            $skipped += $envFile
            Write-Host "⏭️  Skipping $envFile (already exists)" -ForegroundColor Yellow
        } else {
            Copy-Item $example $envFile
            $created += $envFile
            Write-Host "✅ Created $envFile" -ForegroundColor Green
        }
    } else {
        Write-Host "⚠️  Not found: $example" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

if ($created.Count -gt 0) {
    Write-Host "📝 Next steps:" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "1. Edit the following files with your API keys:" -ForegroundColor White
    foreach ($file in $created) {
        Write-Host "   • $file" -ForegroundColor White
    }
    Write-Host ""
    Write-Host "2. At minimum, set one of these in sg-property-agent\backend\.env:" -ForegroundColor White
    Write-Host "   • OPENROUTER_API_KEY=sk-or-..." -ForegroundColor DarkGray
    Write-Host "   • OPENAI_API_KEY=sk-..." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "3. Start services:" -ForegroundColor White
    Write-Host "   docker compose up --build -d" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "4. Access the app:" -ForegroundColor White
    Write-Host "   • Frontend: http://localhost:3000" -ForegroundColor DarkGray
    Write-Host "   • Backend API: http://localhost:8001/docs" -ForegroundColor DarkGray
} else {
    Write-Host "✨ All .env files already exist!" -ForegroundColor Green
    Write-Host ""
    Write-Host "You can now run:" -ForegroundColor White
    Write-Host "   docker compose up --build -d" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "For more info, see README.md" -ForegroundColor Cyan
Write-Host ""
