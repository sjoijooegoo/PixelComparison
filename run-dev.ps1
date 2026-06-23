<#
  开发启动 PixelComparison:开两个控制台窗口,分别跑后端与前端,实时显示日志。
    - 后端:uvicorn --reload(8000),日志同时写 backend\data\logs\backend.log
    - 前端:vite dev(5173),代理 /api、/images 到 8000
  日志文件:
    backend\data\logs\backend.log    后端请求与业务日志(+ 前端上报落 frontend.log)
    backend\data\logs\frontend.log   前端 console / 报错(经 /api/client-logs 上报)

  用法:
    .\run-dev.ps1

  前置(只需首次):
    后端依赖 backend\.venv;前端依赖 frontend\node_modules
#>
param(
  [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPy   = Join-Path $backend ".venv\Scripts\python.exe"

if ([string]::IsNullOrWhiteSpace($DataDir)) {
  if ($env:PIXELCOMP_DATA_DIR) {
    $DataDir = $env:PIXELCOMP_DATA_DIR
  } elseif (Test-Path "Y:\") {
    $DataDir = "Y:\PixelComparison"
  } else {
    $DataDir = Join-Path $backend "data"
  }
}
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$env:PIXELCOMP_DATA_DIR = $DataDir

if (-not (Test-Path $venvPy)) {
  Write-Host "[!] 找不到后端虚拟环境: $venvPy" -ForegroundColor Yellow
  Write-Host "    先执行: python -m venv backend\.venv ; backend\.venv\Scripts\pip install -r backend\requirements.txt"
  exit 1
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
  Write-Host "[!] 找不到前端依赖 frontend\node_modules,请先 cd frontend ; npm install" -ForegroundColor Yellow
  exit 1
}

# 后端控制台
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$backend'; Write-Host '后端日志(Ctrl+C 停止)' -ForegroundColor Green; " +
  "& '$venvPy' -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
)

# 前端控制台
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$frontend'; Write-Host '前端日志(Ctrl+C 停止)' -ForegroundColor Green; npm run dev"
)

Write-Host ""
Write-Host "PixelComparison 开发模式已启动(两个控制台窗口)" -ForegroundColor Green
Write-Host "  前端: http://localhost:5173"
Write-Host "  后端: http://127.0.0.1:8000  (API 文档 /docs)"
Write-Host "  后端数据: $DataDir" -ForegroundColor Cyan
Write-Host "  日志: $DataDir\logs\backend.log  /  frontend.log" -ForegroundColor Cyan
Write-Host "  关闭对应控制台窗口即停止服务。" -ForegroundColor DarkGray
