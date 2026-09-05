param(
    [string]$OutputDir = "dist-offline"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Output = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    [System.IO.Path]::GetFullPath($OutputDir)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $Root $OutputDir))
}
$Build = Join-Path $Output "_build"

Push-Location (Join-Path $Root "frontend")
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
} finally {
    Pop-Location
}

python -m PyInstaller --noconfirm --clean --onefile --console `
    --name SceneScopeOffline `
    --paths (Join-Path $Root "backend") `
    --add-data "$(Join-Path $Root 'frontend\dist');site" `
    --distpath (Join-Path $Build "dist") `
    --workpath $Build `
    --specpath $Output `
    (Join-Path $PSScriptRoot "gpm_offline_viewer.py")
if ($LASTEXITCODE -ne 0) { throw "离线查看器打包失败" }

$Viewer = Join-Path $Output "SceneScopeOffline"
# 运行依赖和前端内嵌到 EXE；构建区与分发目录分开，保留已有配置和批次。
New-Item $Viewer -ItemType Directory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Build "dist\SceneScopeOffline.exe") -Destination $Viewer -Force
New-Item (Join-Path $Viewer "data") -ItemType Directory -Force | Out-Null
New-Item (Join-Path $Viewer "config") -ItemType Directory -Force | Out-Null

Write-Host "离线查看器已生成：$Viewer"
Write-Host "分发只需 SceneScopeOffline.exe、config/ 和 data/，不再需要 _internal/ 或 site/。"
