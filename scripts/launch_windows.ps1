[CmdletBinding()]
param(
    [ValidateSet('Local', 'Remote')][string]$Mode = 'Local',
    [ValidateSet('Menu', 'Auto', 'Http2', 'Quic', 'System', 'Manual')][string]$Connection = 'Menu',
    [string]$CloudflaredPath,
    [switch]$Check,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runtimeDirectory = Join-Path $ProjectRoot '.runtime'
$launcherLock = $null
$transcribing = $false
$exitCode = 0
try {
    $architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($env:OS -ne 'Windows_NT' -or $architecture -ne 'AMD64') { throw '一键启动仅支持 Windows 10/11 x64；其他平台请参考 README 手动安装。' }
    foreach ($required in @('requirements.txt', 'src/web/__init__.py', 'scripts/start_p2p.ps1', 'scripts/windows_bootstrap.ps1', 'scripts/p2p/python-runtime.json', 'scripts/p2p/cloudflared-release.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $required) -PathType Leaf)) { throw '项目文件不完整。请先将整个 ZIP 解压到一个文件夹，不要在压缩包内直接双击启动。' }
    }
    if ($ProjectRoot.Length -gt 100) { throw '解压路径太长，可能导致依赖安装失败。请移到较短路径，例如 C:\Games\5DChess。' }
    Set-Location -LiteralPath $ProjectRoot
    try { New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null } catch { throw '项目目录无法写入。请解压到自己有写入权限的目录，例如“文档”或 C:\Games\5DChess。' }
    . (Join-Path $PSScriptRoot 'windows_bootstrap.ps1')
    $launcherLock = Enter-LauncherLock -RuntimeDirectory $runtimeDirectory
    $logDirectory = Join-Path $ProjectRoot 'logs/launcher'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $launcherLog = Join-Path $logDirectory ((Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8) + '.log')
    Start-Transcript -LiteralPath $launcherLog | Out-Null
    $transcribing = $true
    Write-Host "时线棋局 — $(if ($Mode -eq 'Local') { '本地 / 局域网' } else { '远程联机' })"
    Write-Host '首次启动需要联网下载运行组件；后续本地启动无需联网。'
    Write-Host '运行时请保留本窗口。结束时按 Ctrl+C，等待服务关闭后再关闭窗口。'
    $python = Initialize-LauncherPython -ProjectRoot $ProjectRoot -RuntimeDirectory $runtimeDirectory
    $launchArguments = @{ PythonPath = $python; Check = $Check; OpenBrowser = (-not $NoBrowser -and -not $Check) }
    if ($Mode -eq 'Local') {
        $launchArguments.LanOnly = $true
    } else {
        $Connection = Select-LauncherConnection -Connection $Connection -Check:$Check
        if ($Connection -eq 'Manual') {
            $launchArguments.ManualTunnel = $true
        } else {
            try {
                if ($CloudflaredPath) {
                    if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) { throw '指定的 cloudflared 文件不存在。' }
                    $launchArguments.CloudflaredPath = (Resolve-Path -LiteralPath $CloudflaredPath).Path
                } elseif ($Connection -eq 'System') {
                    $command = Get-Command cloudflared -CommandType Application -ErrorAction SilentlyContinue
                    if (-not $command) { throw '系统 PATH 中没有 cloudflared；可选择项目版本或手动连接。' }
                    $launchArguments.CloudflaredPath = $command.Source
                } else {
                    $launchArguments.CloudflaredPath = Initialize-LauncherCloudflared -ProjectRoot $ProjectRoot -RuntimeDirectory $runtimeDirectory
                }
                $launchArguments.TunnelProtocol = if ($Connection -in @('Http2', 'Quic')) { $Connection.ToLowerInvariant() } else { 'auto' }
                Write-Host "Cloudflare 程序：$($launchArguments.CloudflaredPath)；协议：$($launchArguments.TunnelProtocol)"
            } catch {
                if ($Check) { throw }
                Write-Host "Cloudflare 准备未完成：$($_.Exception.Message)" -ForegroundColor Yellow
                Write-Host '继续启动网站，稍后可在另一个终端手动连接。'
                $launchArguments.Remove('CloudflaredPath')
                $launchArguments.ManualTunnel = $true
            }
        }
    }
    & (Join-Path $PSScriptRoot 'start_p2p.ps1') @launchArguments
} catch {
    $exitCode = 1
    Write-Host "`n启动未完成：$($_.Exception.Message)" -ForegroundColor Red
    if ($launcherLog) { Write-Host "启动日志：$launcherLog" }
    Write-Host '请查看项目根目录的“使用说明.txt”。修正后重新双击即可。'
} finally {
    if ($transcribing) { Stop-Transcript | Out-Null }
    if ($launcherLock) { $launcherLock.Dispose() }
}
exit $exitCode
