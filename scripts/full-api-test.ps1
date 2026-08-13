# AI社媒矩阵运营系统 - 全量 API 功能测试
$BaseUrl = "http://localhost:8080"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"

$passed = 0; $failed = 0; $results = @()

function Send-Json {
    param([string]$Method, [string]$Uri, [object]$Data, [hashtable]$Headers)
    $json = ($Data | ConvertTo-Json -Compress -Depth 5)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    Invoke-RestMethod -Uri $Uri -Method $Method -Body $bytes -ContentType "application/json; charset=utf-8" -Headers $Headers
}

function Test-API {
    param([string]$Name, [scriptblock]$Action)
    try {
        $r = & $Action
        $script:passed++
        $script:results += @{ name=$Name; status="OK"; detail="" }
        Write-Host "  OK  $Name" -ForegroundColor Green
        return $r
    } catch {
        $script:failed++
        $msg = $_.Exception.Message.Substring(0, [Math]::Min(120, $_.Exception.Message.Length))
        $script:results += @{ name=$Name; status="FAIL"; detail=$msg }
        Write-Host "  FAIL  $Name  $msg" -ForegroundColor Red
        return $null
    }
}

Write-Host "=== Full API Test ===" -ForegroundColor Yellow

# 1. Auth
Write-Host "`n--- Auth ---" -ForegroundColor Cyan
$loginRes = Test-API "Auth Login" { Send-Json Post "$BaseUrl/api/v1/auth/login" @{username="admin";password="admin123"} }
$token = $loginRes.data.access_token
$h = @{ Authorization = "Bearer $token" }

Test-API "Auth Me" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/auth/me" -Headers $h }

$refreshToken = $loginRes.data.refresh_token
if ($refreshToken) {
    Test-API "Auth Refresh" { Send-Json Post "$BaseUrl/api/v1/auth/refresh" @{refresh_token=$refreshToken} $h }
} else { Write-Host "  SKIP Auth Refresh (no refresh_token)" -ForegroundColor Yellow }

Test-API "Auth Change Password (will fail - wrong old pwd)" {
    try { Send-Json Put "$BaseUrl/api/v1/auth/me/password" @{old_password="wrong";new_password="test123"} $h; "should fail" } catch { if ($_.Exception.Message -match "400|401|old.password") { "expected fail OK" } else { throw } }
}

# 2. Accounts
Write-Host "`n--- Accounts ---" -ForegroundColor Cyan
$accRes = Test-API "Accounts List" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/accounts/" -Headers $h }
$accountId = if ($accRes.data.Count -gt 0) { $accRes.data[0].id } else { "" }
Write-Host "  accountId=$accountId"

if ($accountId) {
    Test-API "Account Stats" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/accounts/$accountId/stats" -Headers $h }
}

$newAcc = Test-API "Account Create" { Send-Json Post "$BaseUrl/api/v1/accounts/" @{platform="douyin";account_type="ip_persona";account_name="TestAccount";strategy_engine="ip"} $h }
if ($newAcc -and $newAcc.data.id) {
    Test-API "Account Update" { Send-Json Put "$BaseUrl/api/v1/accounts/$($newAcc.data.id)" @{account_name="TestAccountRenamed"} $h }
}

# 3. Content
Write-Host "`n--- Content ---" -ForegroundColor Cyan
Test-API "Script Generate" { Send-Json Post "$BaseUrl/api/v1/content/scripts/generate" @{account_id=$accountId;topic="test topic";strategy_type="ip";duration="30s";count=1} $h }
$scriptsRes = Test-API "Scripts List" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/content/scripts" -Headers $h }
$scriptId = if ($scriptsRes -and $scriptsRes.data.Count -gt 0) { $scriptsRes.data[0].id } else { "" }
Write-Host "  scriptId=$scriptId"

if ($scriptId) {
    Test-API "Script Risk Check" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/content/scripts/$scriptId/risk-check" -Method Post -Headers $h -ContentType "application/json" -Body '{}' }
    Test-API "Script Update Status" { Send-Json Put "$BaseUrl/api/v1/content/scripts/$scriptId" @{status="human_reviewed"} $h }
}

Test-API "Copywriting Generate" { Send-Json Post "$BaseUrl/api/v1/content/copywriting/generate" @{account_id=$accountId;topic="test copy";strategy_type="ip";platform="douyin";count=1} $h }
$copyRes = Test-API "Copywriting List" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/content/copywriting" -Headers $h }
$copyId = if ($copyRes -and $copyRes.data.Count -gt 0) { $copyRes.data[0].id } else { "" }
Write-Host "  copyId=$copyId"

if ($copyId) {
    Test-API "Copywriting Detail" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/content/copywriting/$copyId" -Headers $h }
    Test-API "Copywriting Risk Check" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/content/copywriting/$copyId/risk-check" -Method Post -Headers $h -ContentType "application/json" -Body '{}' }
}

Test-API "Localize" { Send-Json Post "$BaseUrl/api/v1/content/copywriting/localize" @{content="test content for localization";cities=@("Guangzhou");account_id=$accountId;strategy_type="ip"} $h }
Test-API "Trending" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/content/trending" -Headers $h }

# 4. Risk
Write-Host "`n--- Risk ---" -ForegroundColor Cyan
Test-API "Risk Check" { Send-Json Post "$BaseUrl/api/v1/risk/check" @{content="we are the best brand"} $h }
Test-API "Risk Words List" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/risk/words" -Headers $h }
$wordRes = Test-API "Risk Word Create" { Send-Json Post "$BaseUrl/api/v1/risk/words" @{word="testword";category="test";severity="medium";suggestion="remove"} $h }
$wordId = if ($wordRes -and $wordRes.data.id) { $wordRes.data.id } else { "" }
if ($wordId) {
    Test-API "Risk Word Update" { Send-Json Put "$BaseUrl/api/v1/risk/words/$wordId" @{severity="high"} $h }
    Test-API "Risk Word Delete" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/risk/words/$wordId" -Method Delete -Headers $h }
}
Test-API "Risk Batch Check" { Send-Json Post "$BaseUrl/api/v1/risk/check/batch" @{contents=@("best product","number one")} $h }
Test-API "Risk History" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/risk/history" -Headers $h }

# 5. Leads
Write-Host "`n--- Leads ---" -ForegroundColor Cyan
$leadRes = Test-API "Lead Create" { Send-Json Post "$BaseUrl/api/v1/leads/" @{pool_type="consumer";customer_name="TestCust";customer_phone="13800138001";requirement="test"} $h }
$leadId = if ($leadRes -and $leadRes.data.id) { $leadRes.data.id } else { "" }
Write-Host "  leadId=$leadId"

Test-API "Leads List" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/leads/" -Headers $h }
Test-API "Leads Stats" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/leads/stats" -Headers $h }
Test-API "Leads Funnel" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/leads/stats/funnel" -Headers $h }
Test-API "Leads Cities" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/leads/cities" -Headers $h }

if ($leadId) {
    Test-API "Lead Detail" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/leads/$leadId" -Headers $h }
    Test-API "Lead Auto Assign" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/leads/$leadId/auto-assign" -Method Post -Headers $h -ContentType "application/json" -Body '{}' }
    Test-API "Lead Followups" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/leads/$leadId/followups" -Headers $h }
    Test-API "Lead Add Followup" { Send-Json Post "$BaseUrl/api/v1/leads/$leadId/followups" @{action="contacted";note="test followup"} $h }
}

# 6. Dealers
Write-Host "`n--- Dealers ---" -ForegroundColor Cyan
$dealerRes = Test-API "Dealers List" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/dealers/" -Headers $h }
$dealerId = if ($dealerRes -and $dealerRes.data.Count -gt 0) { $dealerRes.data[0].id } else { "" }
Write-Host "  dealerId=$dealerId"

if ($dealerId) {
    Test-API "Dealer Stats" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/dealers/$dealerId/stats" -Headers $h }
    Test-API "Dealer Leads" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/dealers/$dealerId/leads" -Headers $h }
    Test-API "Dealer Update Level" { Send-Json Put "$BaseUrl/api/v1/dealers/$dealerId/level" @{level="B"} $h }
}

# 7. Dashboard
Write-Host "`n--- Dashboard ---" -ForegroundColor Cyan
Test-API "Dashboard Overview" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/dashboard/overview" -Headers $h }
Test-API "Dashboard Content Stats" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/dashboard/content/stats" -Headers $h }
Test-API "Dashboard Lead Stats" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/dashboard/lead/stats" -Headers $h }
Test-API "Dashboard Trend" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/dashboard/trend" -Headers $h }
Test-API "Dashboard Dealer Stats" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/dashboard/dealer/stats" -Headers $h }

# 8. Calendar
Write-Host "`n--- Calendar ---" -ForegroundColor Cyan
$calRes = Test-API "Calendar List" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/calendar/" -Headers $h }
$calId = if ($calRes -and $calRes.data.Count -gt 0) { $calRes.data[0].id } else { "" }

$today = Get-Date -Format "yyyy-MM-dd"
$newCal = Test-API "Calendar Create" { Send-Json Post "$BaseUrl/api/v1/calendar/" @{account_id=$accountId;scheduled_date=$today;scheduled_time="10:00"} $h }
if ($newCal -and $newCal.data.id) {
    $newCalId = $newCal.data.id
    Test-API "Calendar Update Status" { Send-Json Put "$BaseUrl/api/v1/calendar/$newCalId/status" @{publish_status="published"} $h }
    Test-API "Calendar Remind" { Send-Json Post "$BaseUrl/api/v1/calendar/remind" @{calendar_id=$newCalId;user_id="operator";content_title="test";scheduled_time="10:00"} $h }
    Test-API "Calendar Delete" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/calendar/$newCalId" -Method Delete -Headers $h }
}

# 9. Assets
Write-Host "`n--- Assets ---" -ForegroundColor Cyan
Test-API "Assets List" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/assets/" -Headers $h }
Test-API "Assets Tags" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/assets/tags" -Headers $h }

# 10. WeChat (mock)
Write-Host "`n--- WeChat (mock) ---" -ForegroundColor Cyan
Test-API "WeChat Callback" { Send-Json Post "$BaseUrl/api/v1/wecom/callback" @{sender_id="test_user";sender_name="TestDealer";content="test message"} $h }
Test-API "WeChat Send Lead" { Send-Json Post "$BaseUrl/api/v1/wecom/send/lead" @{dealer_id=$dealerId;lead_id=$leadId} $h }
Test-API "WeChat Send Remind" { Send-Json Post "$BaseUrl/api/v1/wecom/send/remind" @{user_id="operator";content_title="test";scheduled_time="10:00"} $h }
Test-API "WeChat Send Report" { Send-Json Post "$BaseUrl/api/v1/wecom/send/report" @{user_id="operator";report_type="weekly"} $h }
Test-API "WeChat Contacts" { Invoke-RestMethod -Uri "$BaseUrl/api/v1/wecom/contacts" -Headers $h }

# Summary
Write-Host "`n========================================" -ForegroundColor Yellow
Write-Host "Total: $($passed + $failed) | Passed: $passed | Failed: $failed" -ForegroundColor $(if ($failed -eq 0) {"Green"} else {"Red"})
Write-Host "========================================" -ForegroundColor Yellow

if ($failed -gt 0) {
    Write-Host "`nFailed tests:" -ForegroundColor Red
    $results | Where-Object { $_.status -eq "FAIL" } | ForEach-Object { Write-Host "  $($_.name): $($_.detail)" -ForegroundColor Red }
}
