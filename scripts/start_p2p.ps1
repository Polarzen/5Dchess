$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "未找到 python。请先安装 Python 3.11+ 并确保 python 在 PATH 中。"
}

$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
    $localCloudflared = Join-Path $ProjectRoot "cloudflared.exe"
    if (Test-Path $localCloudflared) {
        $cloudflaredPath = $localCloudflared
    } else {
        throw @"
未找到 cloudflared。
请从 Cloudflare 官方 Downloads 页面下载 Windows 64-bit cloudflared，
将 cloudflared.exe 放到项目根目录或加入 PATH，然后重新运行本脚本。
"@
    }
} else {
    $cloudflaredPath = $cloudflared.Source
}

$selectedPortOutput = @(& $python.Source "scripts/run_p2p_server.py" "--select-port")
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
$tunnel = $null
$httpHandler = $null
$httpClient = $null

Write-Host "[5D Chess] 启动本地 P2P Flask 服务: http://127.0.0.1:$Port (debug=False)"

try {
    $hadLaunchIdEnv = Test-Path Env:FIVE_D_P2P_LAUNCH_ID
    $previousLaunchId = $env:FIVE_D_P2P_LAUNCH_ID
    $env:FIVE_D_P2P_LAUNCH_ID = $LaunchId
    try {
        $server = Start-Process `
            -FilePath $python.Source `
            -ArgumentList @("scripts/run_p2p_server.py", "--port", [string]$Port) `
            -WorkingDirectory $ProjectRoot `
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
    $deadline = (Get-Date).AddSeconds(10)
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
                    ([int64]$payload.pid -eq [int64]$server.Id)
                ) {
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
        throw "Flask 服务在 10 秒内未通过身份就绪检查 http://127.0.0.1:$Port$ReadinessPath。"
    }
    if ($server.HasExited) {
        throw "Flask 服务在启动 Tunnel 前退出。"
    }

    Write-Host "[5D Chess] 正在创建 Cloudflare Quick Tunnel..."
    Write-Host "[5D Chess] 终端出现 https://*.trycloudflare.com 地址后，把该地址发给对手。"
    Write-Host "[5D Chess] 双方打开同一地址：房主点‘创建真人房间’，对手点‘加入真人房间’。"
    $tunnel = Start-Process `
        -FilePath $cloudflaredPath `
        -ArgumentList @("tunnel", "--url", "http://127.0.0.1:$Port") `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -PassThru

    while ($true) {
        if ($server.HasExited) {
            throw "Flask 服务已退出；正在关闭 Cloudflare Tunnel。"
        }
        if ($tunnel.HasExited) {
            throw "Cloudflare Tunnel 已退出（状态 $($tunnel.ExitCode)）；正在关闭 Flask 服务。"
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
            Write-Host "[5D Chess] 关闭 Cloudflare Tunnel。"
            Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
        }
    } catch {
        # The tunnel may exit between the state check and Stop-Process.
    }
    try {
        if ($server -and -not $server.HasExited) {
            Write-Host "[5D Chess] 关闭本地 Flask 服务。"
            Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
        }
    } catch {
        # The Flask process may exit between the state check and Stop-Process.
    }
}
