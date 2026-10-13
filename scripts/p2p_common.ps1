# Shared by setup and launcher; dot-sourcing this file starts no processes.
function Resolve-P2PPython {
    param([string]$ProjectRoot, [string]$PythonPath)
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Python not found: $PythonPath" }
        return (Resolve-Path -LiteralPath $PythonPath).Path
    }
    foreach ($relative in @('.venv311\Scripts\python.exe', '.venv\Scripts\python.exe')) {
        $candidate = Join-Path $ProjectRoot $relative
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'Project Python missing. Run scripts/setup_p2p.ps1 first, or specify -PythonPath.'
}

function Resolve-P2PSoftwareDirectory {
    param([string]$ProjectRoot, [string]$SoftwareDirectory)
    if (-not $SoftwareDirectory) { $SoftwareDirectory = '.runtime' }
    if (-not [IO.Path]::IsPathRooted($SoftwareDirectory)) {
        $SoftwareDirectory = Join-Path $ProjectRoot $SoftwareDirectory
    }
    return [IO.Path]::GetFullPath($SoftwareDirectory)
}

function Resolve-P2PCloudflared {
    param([string]$ProjectRoot, [string]$CloudflaredPath)
    if ($CloudflaredPath) {
        if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) { throw "cloudflared not found: $CloudflaredPath" }
        return (Resolve-Path -LiteralPath $CloudflaredPath).Path
    }
    foreach ($relative in @('.runtime\cloudflared\cloudflared.exe', 'cloudflared.exe')) {
        $candidate = Join-Path $ProjectRoot $relative
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $command = Get-Command cloudflared -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw 'cloudflared missing. Run scripts/setup_p2p.ps1, specify -CloudflaredPath, or use -LanOnly for LAN play.'
}

function Test-P2PProcessOwnership {
    param([int]$ProcessId, [int]$RootProcessId)
    # Windows venv python.exe can redirect to a child interpreter. Require
    # ancestry as well as the per-launch identity; never trust an arbitrary PID.
    for ($depth = 0; $depth -lt 4 -and $ProcessId -gt 0; $depth++) {
        if ($ProcessId -eq $RootProcessId) { return $true }
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
        if (-not $processInfo) { return $false }
        $ProcessId = [int]$processInfo.ParentProcessId
    }
    return $false
}

function Get-P2PTunnelFailure {
    param([string]$Output)
    # Match provisioning errors only: a QUIC timeout after provisioning is a
    # different problem. Return fixed messages rather than echoing credentials
    # or other arbitrary configuration that may be present in a log.
    $requestFailure = [regex]::Match($Output, '(?im)^.*failed to (?:request quick Tunnel|read quick-tunnel response):[^\r\n]*').Value
    if ($requestFailure -match '(?i)context deadline exceeded|timeout|timed out') {
        return [pscustomobject]@{
            Retryable = $true
            Message = '向 api.trycloudflare.com 申请临时网址超时（HTTPS 请求）。切换 -TunnelProtocol http2 不会改变这一步；请检查网络到该接口的连通性，或稍后再试。'
        }
    }
    if ($requestFailure -match '(?i)connection reset|connection refused|forcibly closed|unexpected EOF|\bEOF\b|no such host|temporary failure|network is unreachable|no route to host') {
        return [pscustomobject]@{
            Retryable = $true
            Message = '申请 Cloudflare 临时网址时发生网络或 DNS 错误；请检查网络连接，或稍后再试。'
        }
    }
    if ($Output -match '(?im)quick tunnel provisioning failed with status (429|5\d\d)\b') {
        return [pscustomobject]@{
            Retryable = $true
            Message = 'Cloudflare 临时网址接口限流或服务暂时不可用。'
        }
    }
    if ($requestFailure -match '(?i)x509|certificate') {
        return [pscustomobject]@{
            Retryable = $false
            Message = 'Cloudflare 临时网址接口的 TLS 证书校验失败；请检查系统时间及网络证书配置。'
        }
    }
    return [pscustomobject]@{
        Retryable = $false
        Message = 'Cloudflare 启动失败，需查看日志中的具体错误。'
    }
}

function Open-P2PBrowser {
    param([string]$Url)
    try { Start-Process -FilePath $Url | Out-Null } catch {
        Write-Host "[时线棋局] 无法自动打开浏览器，请手动打开：$Url"
    }
}

function Show-P2PManualConnection {
    param([int]$Port, [string]$Executable = 'cloudflared')
    if (-not $Executable) { $Executable = 'cloudflared' }
    Write-Host "[时线棋局] 网站继续运行：http://127.0.0.1:$Port"
    Write-Host '[时线棋局] 保留本窗口，另开一个 CMD 窗口，复制以下整行命令：'
    Write-Host ('"' + $Executable + '" tunnel --url http://127.0.0.1:' + $Port)
    Write-Host '[时线棋局] 如果使用 PowerShell，复制这一行：'
    Write-Host ("& '" + $Executable.Replace("'", "''") + "' tunnel --url http://127.0.0.1:" + $Port)
    Write-Host '[时线棋局] 也可用自己的隧道工具，将上面的本机地址设为源站。'
    Write-Host '[时线棋局] 没有安装 cloudflared 时，请重新选择项目版本或参考使用说明。'
    Write-Host '[时线棋局] 取得公网网址后，双方打开同一公网网址；房主创建房间，再分享邀请链接。'
    Write-Host '[时线棋局] 停止网站：本窗口 Ctrl+C；手动启动的隧道需在它自己的窗口 Ctrl+C。'
}

function Start-P2PRemoteConnection {
    param([string]$Executable, [string]$ProjectRoot, [int]$Port, [string]$Protocol,
          [string]$LogStem, $Server, [ref]$Tunnel, [int]$MaxAttempts = 3,
          [int]$StartupTimeoutSeconds = 180, [switch]$OpenBrowser)
    try {
        Connect-P2PQuickTunnel -Executable $Executable -ProjectRoot $ProjectRoot -Port $Port `
            -Protocol $Protocol -LogStem $LogStem -Server $Server -Tunnel $Tunnel `
            -MaxAttempts $MaxAttempts -StartupTimeoutSeconds $StartupTimeoutSeconds -OpenBrowser:$OpenBrowser
    } catch {
        if ($Server.HasExited) { throw }
        Write-Host "[时线棋局] 自动隧道未连接：$($_.Exception.Message)" -ForegroundColor Yellow
        if ($Tunnel.Value) {
            if (-not $Tunnel.Value.HasExited) { Stop-Process -Id $Tunnel.Value.Id -Force -ErrorAction SilentlyContinue }
            $Tunnel.Value.Dispose()
            $Tunnel.Value = $null
        }
        Show-P2PManualConnection -Port $Port -Executable $Executable
        if ($OpenBrowser) { Open-P2PBrowser -Url "http://127.0.0.1:$Port" }
    }
}

function Connect-P2PQuickTunnel {
    param(
        [string]$Executable,
        [string]$ProjectRoot,
        [int]$Port,
        [string]$Protocol,
        [string]$LogStem,
        $Server,
        [ref]$Tunnel,
        [ValidateRange(1, 5)][int]$MaxAttempts = 3,
        [ValidateRange(10, 600)][int]$StartupTimeoutSeconds = 90,
        [switch]$OpenBrowser
    )
    # The caller owns process cleanup even when Ctrl+C interrupts startup.
    # Never rotate a URL after it has been provisioned or shared with players.
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        if ($Server.HasExited) { throw 'Flask 服务已退出；停止创建 Cloudflare Tunnel。' }
        $attemptStem = $LogStem + '-tunnel-attempt-' + $attempt
        $errorLog = $attemptStem + '-error.log'
        Write-Host "[时线棋局] 正在创建 Cloudflare Quick Tunnel（$attempt/$MaxAttempts）；日志：$errorLog"
        $Tunnel.Value = Start-Process `
            -FilePath $Executable `
            -ArgumentList @('tunnel', '--no-autoupdate', '--protocol', $Protocol, '--url', "http://127.0.0.1:$Port") `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput ($attemptStem + '.log') `
            -RedirectStandardError $errorLog `
            -PassThru
        # Keep the process handle while it is alive. Windows PowerShell 5.1
        # can otherwise lose ExitCode after a process obtained via Start-Process exits.
        try { $null = $Tunnel.Value.Handle } catch [System.InvalidOperationException] {
            # A process that already disappeared can still be diagnosed from its log.
        }
        $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
        while ($true) {
            if ($Server.HasExited) { throw 'Flask 服务已退出；停止创建 Cloudflare Tunnel。' }
            $process = $Tunnel.Value
            $exited = $process.HasExited
            if ($exited) { $process.WaitForExit() }
            # Get-Content on a newly created empty log may yield AutomationNull
            # in Windows PowerShell 5.1, even with an expression-level cast.
            $output = '' + (Get-Content -LiteralPath $errorLog -Raw -ErrorAction SilentlyContinue) + "`n" + (Get-Content -LiteralPath ($attemptStem + '.log') -Raw -ErrorAction SilentlyContinue)
            # api.trycloudflare.com/tunnel in an error is not a provisioned URL.
            $urlMatch = [regex]::Match($output, 'https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com(?=[\s|]|$)')
            $registered = $output.Contains('Registered tunnel connection')
            if ($exited) {
                $failure = Get-P2PTunnelFailure -Output $output
                if ($failure.Retryable -and -not $urlMatch.Success -and -not $registered -and $attempt -lt $MaxAttempts) {
                    $delaySeconds = [int][Math]::Min(2 * [Math]::Pow(2, $attempt - 1), 16)
                    Write-Host "[时线棋局] $($failure.Message)"
                    Write-Host "[时线棋局] $delaySeconds 秒后重试；本地网站继续运行。按 Ctrl+C 可取消。"
                    $process.Dispose()
                    $Tunnel.Value = $null
                    # Check the server during backoff; never relaunch a tunnel
                    # after its origin has exited.
                    for ($tick = 0; $tick -lt $delaySeconds * 4; $tick++) {
                        if ($Server.HasExited) { throw 'Flask 服务已退出；停止重试 Cloudflare Tunnel。' }
                        Start-Sleep -Milliseconds 250
                    }
                    break
                }
                $exitCode = if ($null -eq $process.ExitCode) { '未知' } else { [string]$process.ExitCode }
                throw "Cloudflare Tunnel 已退出（尝试 $attempt/$MaxAttempts，退出码 $exitCode）。$($failure.Message) 查看日志：$errorLog"
            }
            if ($urlMatch.Success -and $registered) {
                Write-Host "[时线棋局] 公网地址：$($urlMatch.Value)"
                Write-Host '[时线棋局] 房主也从此公网地址打开游戏，创建在线房间后复制邀请链接给对手。'
                if ($OpenBrowser) { Open-P2PBrowser -Url $urlMatch.Value }
                return
            }
            if ((Get-Date) -gt $deadline) {
                if ($urlMatch.Success) {
                    throw "已取得临时网址，但隧道在 $StartupTimeoutSeconds 秒内未连接；可尝试 -TunnelProtocol http2、auto 或 quic。查看日志：$errorLog"
                }
                throw "$StartupTimeoutSeconds 秒内未取得可用的 Cloudflare 临时网址；请检查网络到 api.trycloudflare.com 的连通性。查看日志：$errorLog"
            }
            Start-Sleep -Milliseconds 500
        }
    }
}
