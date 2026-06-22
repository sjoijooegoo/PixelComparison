<#
  生产启动 PixelComparison(单端口同源部署)。
  与开发用的 run.ps1 不同:
    - 前端先 vite build 成静态文件,由后端直接伺服(不再跑 vite dev、无代理)。
    - 只有一个进程、一个端口,同时提供 页面 + /api + /images。
    - uvicorn 单 worker、无 --reload(对比任务状态在进程内存,必须单 worker)。

  用法:
    .\run-prod.ps1                 # 默认端口 8800,先构建前端再启动
    .\run-prod.ps1 -Port 9000      # 换端口
    .\run-prod.ps1 -SkipBuild      # 前端没改动时跳过构建,直接启动
    .\run-prod.ps1 -Background     # 后台启动(独立窗口),关掉窗口即停止

  前置条件(只需首次):
    后端依赖   backend\.venv          (python -m venv backend\.venv ; backend\.venv\Scripts\pip install -r backend\requirements.txt)
    前端依赖   frontend\node_modules  (cd frontend ; npm install)

  注意:此脚本是「手动运行」模式 —— 关掉窗口/重启电脑后需重新运行。
        若要开机自启,可把它登记进「任务计划程序」(可让我补一个登记脚本)。
#>
param(
  [int]$Port = 8800,
  [switch]$SkipBuild,
  [switch]$Background
)

$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPy   = Join-Path $backend ".venv\Scripts\python.exe"
$dist     = Join-Path $frontend "dist"

# --- 依赖检查 ---
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

# --- 端口占用检查 ---
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
  Write-Host "[!] 端口 $Port 已被占用,请换一个: .\run-prod.ps1 -Port <其他端口>" -ForegroundColor Yellow
  exit 1
}

# --- 构建前端 ---
if ($SkipBuild) {
  if (-not (Test-Path $dist)) {
    Write-Host "[!] 指定了 -SkipBuild 但 frontend\dist 不存在,需先构建一次。" -ForegroundColor Yellow
    exit 1
  }
  Write-Host "[=] 跳过前端构建,沿用已有 dist" -ForegroundColor DarkGray
} else {
  Write-Host "[*] 构建前端 (vite build) ..." -ForegroundColor Cyan
  Push-Location $frontend
  try { & npm run build } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { Write-Host "[!] 前端构建失败" -ForegroundColor Red; exit 1 }
  Write-Host "[*] 前端构建完成 -> $dist" -ForegroundColor Green
}

# --- 取局域网 IPv4(排除回环 / APIPA / 虚拟网卡)---
$ip = (Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object {
    $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and
    $_.InterfaceAlias -notlike '*VMware*' -and $_.InterfaceAlias -notlike '*VirtualBox*' -and
    $_.InterfaceAlias -notlike '*Loopback*'
  } | Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "PixelComparison(生产模式 · 单端口同源)" -ForegroundColor Green
Write-Host "  本机访问 : http://localhost:$Port"
if ($ip) { Write-Host "  局域网访问: http://${ip}:$Port" -ForegroundColor Cyan }
Write-Host "  (页面 / 接口 / 图片同端口提供;单 worker,无热重载)" -ForegroundColor DarkGray
Write-Host ""

# --- 启动后端(同时伺服前端 dist)---
$uvicornArgs = @("-m","uvicorn","app.main:app","--host","0.0.0.0","--port","$Port")
if ($Background) {
  Start-Process -FilePath $venvPy -WorkingDirectory $backend -ArgumentList $uvicornArgs
  Write-Host "[*] 已后台启动(独立窗口),关掉该窗口即停止服务。" -ForegroundColor DarkGray
} else {
  Write-Host "[*] 前台运行中,按 Ctrl+C 停止。" -ForegroundColor DarkGray
  Push-Location $backend
  try { & $venvPy @uvicornArgs } finally { Pop-Location }
}
