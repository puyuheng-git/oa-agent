<#
.SYNOPSIS
  启动 OA LangGraph Agent（单进程 / 单 worker）。

.DESCRIPTION
  1. 安装/同步后端依赖（uv sync）
  2. 前端未构建或指定 -Build 时构建前端（npm ci + npm run build）
  3. 已安装（data/bootstrap.json 存在）时执行数据库迁移（alembic upgrade head）
  4. 启动 uvicorn（必须单 worker：运行状态、取消标记、Checkpointer 都在进程内，见部署文档）

.EXAMPLE
  .\scripts\start.ps1                       # MySQL，Cookie Secure，需 HTTPS 反代
  .\scripts\start.ps1 -Port 9000 -Build
#>
param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8765,
    [string]$DataDir = "",
    [switch]$Build
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $DataDir) { $DataDir = Join-Path $Root "data" }
$DataDir = [IO.Path]::GetFullPath($DataDir)
$env:OA_AGENT_DATA_DIR = $DataDir

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "未找到 uv：请先安装 https://docs.astral.sh/uv/" }

Push-Location (Join-Path $Root "backend")
try {
    uv sync
    if ($LASTEXITCODE -ne 0) { throw "uv sync 失败" }
} finally { Pop-Location }

$dist = Join-Path $Root "frontend\dist\admin\index.html"
if ($Build -or -not (Test-Path $dist)) {
    # 用 npm.cmd，避免 PowerShell 执行策略拦截未签名的 npm.ps1
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCmd) { $npmCmd = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npmCmd) { throw "未找到 npm：请安装 Node.js 18+，或在其他机器构建后拷贝 frontend/dist" }
    Push-Location (Join-Path $Root "frontend")
    try {
        & $npmCmd.Source ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci 失败" }
        & $npmCmd.Source run build
        if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
    } finally { Pop-Location }
}

Push-Location (Join-Path $Root "backend")
try {
    if (Test-Path (Join-Path $DataDir "bootstrap.json")) {
        Write-Host "执行数据库迁移……"
        uv run alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "数据库迁移失败（检查数据库连接与迁移账号权限）" }
    } else {
        Write-Host "尚未安装：启动后访问 http://${BindHost}:${Port}/setup/ ，安装令牌在 $DataDir\setup.token" -ForegroundColor Cyan
    }
    Write-Host "启动 Agent：http://${BindHost}:${Port}/  数据目录：$DataDir"
    uv run uvicorn oa_agent.main:app --host $BindHost --port $Port --workers 1 --proxy-headers
} finally { Pop-Location }
