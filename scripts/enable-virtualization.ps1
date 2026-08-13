# 以管理员身份运行，修复 Docker Desktop 虚拟化问题
# 右键 PowerShell -> 以管理员身份运行

Write-Host "=== 启用 Windows 虚拟化组件 ===" -ForegroundColor Cyan
bcdedit /set hypervisorlaunchtype auto
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:HypervisorPlatform /all /norestart
Write-Host "请重启电脑后打开 Docker Desktop" -ForegroundColor Yellow
Read-Host "按 Enter 退出"
