# AI社媒矩阵 一键 Docker 启动
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "已创建 .env" -ForegroundColor Yellow
}

docker context use desktop-linux 2>$null
if ($LASTEXITCODE -ne 0) { docker context use default 2>$null }

Write-Host "构建并启动服务（首次约 5-10 分钟）..." -ForegroundColor Cyan
docker compose up --build -d

Write-Host ""
Write-Host "管理后台: http://localhost" -ForegroundColor Green
Write-Host "API 文档: http://localhost/docs" -ForegroundColor Green
Write-Host "账号:     admin / admin123" -ForegroundColor Yellow
Write-Host ""
Write-Host "查看日志: docker compose logs -f backend" -ForegroundColor Gray
