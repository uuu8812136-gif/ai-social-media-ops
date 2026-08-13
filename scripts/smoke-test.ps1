param(
    [string]$BaseUrl = "http://localhost:8080",
    [string]$Username = "admin",
    [string]$Password = "admin123"
)

$ErrorActionPreference = "Stop"
$passed = 0
$failed = 0

function Test-Step([string]$Name, [scriptblock]$Action) {
    try {
        & $Action
        $script:passed++
        Write-Host "[PASS] $Name" -ForegroundColor Green
    } catch {
        $script:failed++
        Write-Host "[FAIL] $Name - $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Get-Api([string]$Path, [hashtable]$Headers = @{}) {
    Invoke-RestMethod -Uri "$BaseUrl$Path" -Method Get -Headers $Headers -TimeoutSec 30
}

Test-Step "Liveness" {
    $r = Get-Api "/health/live"
    if ($r.status -ne "ok") { throw "unexpected status: $($r.status)" }
}

Test-Step "Readiness" {
    $r = Get-Api "/health/ready"
    if ($r.status -ne "ready") { throw "dependencies are not ready" }
}

$login = Invoke-RestMethod -Uri "$BaseUrl/api/v1/auth/login" -Method Post -ContentType "application/json; charset=utf-8" -Body (@{
    username = $Username
    password = $Password
} | ConvertTo-Json) -TimeoutSec 30
$token = $login.data.access_token
if (-not $token) { throw "login did not return access_token" }
$headers = @{ Authorization = "Bearer $token" }

Test-Step "Current user" {
    $r = Get-Api "/api/v1/auth/me" $headers
    if (-not $r.data.username) { throw "missing username" }
}

Test-Step "Dashboard overview" {
    $r = Get-Api "/api/v1/dashboard/overview" $headers
    if ($null -eq $r.data.accounts) { throw "missing accounts" }
}

Test-Step "Real social metrics" {
    $r = Get-Api "/api/v1/dashboard/social/stats?days=30" $headers
    if ($null -eq $r.data.total_stats) { throw "missing total_stats" }
}

Test-Step "Social accounts" {
    $r = Get-Api "/api/v1/social/accounts/?page_size=100&status=active" $headers
    if ($null -eq $r.data) { throw "missing account list" }
}

Test-Step "Publish tasks" {
    $r = Get-Api "/api/v1/social/publish/tasks?page_size=100" $headers
    if ($null -eq $r.data) { throw "missing task list" }
}

Test-Step "Crawler jobs" {
    $r = Get-Api "/api/v1/crawler/jobs?page_size=100" $headers
    if ($null -eq $r.data) { throw "missing crawler list" }
}

Test-Step "Assets" {
    $r = Get-Api "/api/v1/assets/?page_size=100" $headers
    if ($null -eq $r.data) { throw "missing asset list" }
}

Write-Host "Smoke result: $passed passed, $failed failed"
if ($failed -gt 0) { exit 1 }
