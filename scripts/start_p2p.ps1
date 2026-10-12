[CmdletBinding()]
param(
    [switch]$LanOnly,
    [switch]$Check,
    [ValidateRange(1, 65535)][int]$Port = 5050,
    [string]$PythonPath,
    [string]$CloudflaredPath,
    [ValidateSet('auto', 'http2', 'quic')][string]$TunnelProtocol = 'auto'
)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
. (Join-Path $PSScriptRoot 'p2p_common.ps1')

$pythonExecutable = Resolve-P2PPython -ProjectRoot $ProjectRoot -PythonPath $PythonPath
& $pythonExecutable -X utf8 -c "import sys; assert sys.version_info >= (3, 11); import flask, numpy, sqlalchemy, mysql.connector; print('Python dependencies OK: ' + sys.executable)"
if ($LASTEXITCODE -ne 0) { throw 'Dependencies missing. Run scripts/setup_p2p.ps1.' }
if (-not $LanOnly) {
    $cloudflaredExecutable = Resolve-P2PCloudflared -ProjectRoot $ProjectRoot -CloudflaredPath $CloudflaredPath
    & $cloudflaredExecutable --version
    if ($LASTEXITCODE -ne 0) { throw 'cloudflared version check failed.' }
}
if ($Check) { Write-Host 'P2P environment OK; no server or tunnel started.'; return }

$selectedPortOutput = @(& $pythonExecutable -X utf8 "scripts/run_p2p_server.py" "--select-port" "--port" $Port)
if ($LASTEXITCODE -ne 0 -or $selectedPortOutput.Count -ne 1) {
    throw "无法通过 Python 端口选择模式取得唯一端口。"
}
$selectedPortText = ([string]$selectedPortOutput[0]).Trim()
if ($selectedPortText -notmatch '^\d+$') {
    throw "Python 端口选择模式返回了无效端口。"
}
$Port = [int]$selectedPortText
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Python 端口选择模式返回了范围外端口。"
}

$ReadinessPath = "/__p2p/readiness"
$LaunchId = [Guid]::NewGuid().ToString("N")
$server = $null
$serviceProcess = $null
$tunnel = $null
$httpHandler = $null
$httpClient = $null
$logDirectory = Join-Path $ProjectRoot 'logs/p2p'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logStem = Join-Path $logDirectory ((Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$serverLog = $logStem + '-server.log'
$serverErrorLog = $logStem + '-server-error.log'
$tunnelLog = $logStem + '-tunnel.log'
$tunnelErrorLog = $logStem + '-tunnel-error.log'

Write-Host "[时线棋局] P2P Flask 监听 0.0.0.0:$Port；本机访问 http://127.0.0.1:$Port (debug=False)"
Write-Host "[时线棋局] 服务日志：$serverErrorLog"
Write-Host '[时线棋局] 结束时在此窗口按 Ctrl+C，服务与隧道会一起停止。'

try {
    $hadLaunchIdEnv = Test-Path Env:FIVE_D_P2P_LAUNCH_ID
    $previousLaunchId = $env:FIVE_D_P2P_LAUNCH_ID
    $env:FIVE_D_P2P_LAUNCH_ID = $LaunchId
    try {
        $server = Start-Process `
            -FilePath $pythonExecutable `
            -ArgumentList @('-u', '-X', 'utf8', "scripts/run_p2p_server.py", "--port", [string]$Port) `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $serverLog `
            -RedirectStandardError $serverErrorLog `
            -PassThru
    } finally {
        if ($hadLaunchIdEnv) {
            $env:FIVE_D_P2P_LAUNCH_ID = $previousLaunchId
        } else {
            Remove-Item Env:FIVE_D_P2P_LAUNCH_ID -ErrorAction SilentlyContinue
        }
    }

    Add-Type -AssemblyName System.Net.Http
    $httpHandler = New-Object System.Net.Http.HttpClientHandler
    $httpHandler.UseProxy = $false
    $httpHandler.AllowAutoRedirect = $false
    $httpClient = New-Object System.Net.Http.HttpClient($httpHandler)
    $httpClient.Timeout = [TimeSpan]::FromMilliseconds(750)

    $readinessUrl = "http://127.0.0.1:$Port$ReadinessPath"
    $ready = $false
    $deadline = (Get-Date).AddSeconds(30)
    while (-not $ready -and (Get-Date) -lt $deadline) {
        if ($server.HasExited) {
            throw "Flask 服务启动失败，请先运行 python scripts/run_p2p_server.py 查看错误。"
        }

        $response = $null
        try {
            $response = $httpClient.GetAsync($readinessUrl).GetAwaiter().GetResult()
            if ($response.StatusCode -eq [System.Net.HttpStatusCode]::OK) {
                $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
                if (
                    ([string]$payload.launch_id -ceq $LaunchId) -and
                    (Test-P2PProcessOwnership -ProcessId ([int]$payload.pid) -RootProcessId $server.Id)
                ) {
                    $serviceProcess = Get-Process -Id ([int]$payload.pid) -ErrorAction Stop
                    $ready = $true
                }
            }
        } catch {
            # The bounded loop below retries until the identity endpoint is ready.
        } finally {
            if ($response) {
                $response.Dispose()
            }
        }
        if ($server.HasExited -and -not $ready) {
            throw "Flask 服务在就绪检查期间退出。"
        }
        if (-not $ready) {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ready) {
        throw "Flask 服务在 30 秒内未通过身份就绪检查。查看日志：$serverErrorLog"
    }
    if ($server.HasExited) {
        throw "Flask 服务在启动 Tunnel 前退出。"
    }

    if ($LanOnly) {
        $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' -and $_.AddressState -eq 'Preferred' }
        foreach ($address in $addresses) { Write-Host "[时线棋局] 局域网地址：http://$($address.IPAddress):$Port" }
        Write-Host '[时线棋局] 双方打开房主的局域网地址；房主创建在线房间，再复制邀请链接。'
    } else {
        Write-Host "[时线棋局] 正在创建 Cloudflare Quick Tunnel；日志：$tunnelErrorLog"
        $tunnel = Start-Process `
            -FilePath $cloudflaredExecutable `
            -ArgumentList @('tunnel', '--no-autoupdate', '--protocol', $TunnelProtocol, "--url", "http://127.0.0.1:$Port") `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $tunnelLog `
            -RedirectStandardError $tunnelErrorLog `
            -PassThru
    }

    $tunnelReady = $false
    $tunnelDeadline = (Get-Date).AddSeconds(90)
    while ($true) {
        if ($server.HasExited) {
            throw "Flask 服务已退出；正在关闭 Cloudflare Tunnel。"
        }
        if ($tunnel) {
            if ($tunnel.HasExited) { throw "Cloudflare Tunnel 已退出；查看日志：$tunnelErrorLog" }
            if (-not $tunnelReady) {
                $tunnelOutput = [string](Get-Content -LiteralPath $tunnelErrorLog -Raw -ErrorAction SilentlyContinue)
                $urlMatch = [regex]::Match($tunnelOutput, 'https://[a-z0-9-]+\.trycloudflare\.com')
                if ($urlMatch.Success -and $tunnelOutput.Contains('Registered tunnel connection')) {
                    $tunnelReady = $true
                    Write-Host "[时线棋局] 公网地址：$($urlMatch.Value)"
                    Write-Host '[时线棋局] 房主也从此公网地址打开游戏，创建在线房间后复制邀请链接给对手。'
                } elseif ((Get-Date) -gt $tunnelDeadline) {
                    throw "Tunnel 在 90 秒内未连接。可尝试 -TunnelProtocol http2。查看日志：$tunnelErrorLog"
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    if ($httpClient) {
        $httpClient.Dispose()
    }
    if ($httpHandler) {
        $httpHandler.Dispose()
    }
    try {
        if ($tunnel -and -not $tunnel.HasExited) {
            Write-Host "[时线棋局] 关闭 Cloudflare Tunnel。"
            Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
        }
    } catch {
        # The tunnel may exit between the state check and Stop-Process.
    }
    try {
        if ($serviceProcess -and -not $serviceProcess.HasExited -and $serviceProcess.Id -ne $server.Id) {
            Stop-Process -InputObject $serviceProcess -Force -ErrorAction SilentlyContinue
        }
        if ($server -and -not $server.HasExited) {
            Write-Host "[时线棋局] 关闭本地 Flask 服务。"
            # Also covers Ctrl+C / failure before the readiness response when
            # the Windows venv redirector's child has not been recorded yet.
            & taskkill.exe /PID $server.Id /T /F 2>$null | Out-Null
        }
    } catch {
        # The Flask process may exit between the state check and Stop-Process.
    }
}
