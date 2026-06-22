<#
  一键启动 PixelComparison(前端 + 后端,均监听 0.0.0.0)。
  用法:  右键“用 PowerShell 运行”,或在仓库目录执行   .\run.ps1
  各自会开一个独立窗口显示日志;关掉窗口即停止对应服务。

  前置条件(只需首次):
    后端依赖   backend\.venv      (没有可执行:  python -m venv backend\.venv ; backend\.venv\Scripts\pip install -r backend\requirements.txt)
    前端依赖   frontend\node_modules  (没有可执行:  cd frontend ; npm install)
#>
param(
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPy   = Join-Path $backend ".venv\Scripts\python.exe"

# 依赖检查
if (-not (Test-Path $venvPy)) {
  Write-Host "[!] 找不到后端虚拟环境: $venvPy" -ForegroundColor Yellow
  Write-Host "    请先执行: python -m venv backend\.venv ; backend\.venv\Scripts\pip install -r backend\requirements.txt"
  exit 1
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
  Write-Host "[!] 找不到前端依赖 frontend\node_modules" -ForegroundColor Yellow
  Write-Host "    请先执行: cd frontend ; npm install"
  exit 1
}

# 后端:uvicorn 绑 0.0.0.0
Start-Process -FilePath "powershell" -WorkingDirectory $backend -ArgumentList @(
  "-NoExit","-Command",
  "& '$venvPy' -m uvicorn app.main:app --host 0.0.0.0 --port $BackendPort"
)

# 前端:vite(host 已写进 vite.config.js)
Start-Process -FilePath "powershell" -WorkingDirectory $frontend -ArgumentList @(
  "-NoExit","-Command",
  "npm run dev"
)

# 取局域网 IPv4(排除回环 / APIPA / 虚拟网卡)
$ip = (Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object {
    $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and
    $_.InterfaceAlias -notlike '*VMware*' -and $_.InterfaceAlias -notlike '*VirtualBox*' -and
    $_.InterfaceAlias -notlike '*Loopback*'
  } | Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "PixelComparison 启动中(两个新窗口分别是前端/后端日志)" -ForegroundColor Green
Write-Host "  本机访问 : http://localhost:$FrontendPort"
if ($ip) { Write-Host "  局域网访问: http://${ip}:$FrontendPort" -ForegroundColor Cyan }
Write-Host "  (前端通过代理转发 /api、/images 到后端,只需开放 $FrontendPort 端口)"
