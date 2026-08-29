param(
    [int]$Port = 5000
)

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

Write-Host "[5D Chess] 启动本地 Flask 服务: http://127.0.0.1:$Port"
$server = Start-Process \
    -FilePath $python.Source \
    -ArgumentList @("src/main.py", "--web") \
    -WorkingDirectory $ProjectRoot \
    -PassThru

try {
    Start-Sleep -Seconds 2
    if ($server.HasExited) {
        throw "Flask 服务启动失败，请先运行 python src/main.py --web 查看错误。"
    }

    if ($Port -ne 5000) {
        Write-Warning "当前 src/main.py --web 固定使用 5000 端口；已改用 5000 建立 Tunnel。"
        $Port = 5000
    }

    Write-Host "[5D Chess] 正在创建 Cloudflare Quick Tunnel..."
    Write-Host "[5D Chess] 终端出现 https://*.trycloudflare.com 地址后，把该地址发给对手。"
    Write-Host "[5D Chess] 双方打开同一地址：房主点‘创建真人房间’，对手点‘加入真人房间’。"
    & $cloudflaredPath tunnel --url "http://127.0.0.1:$Port"
}
finally {
    if ($server -and -not $server.HasExited) {
        Write-Host "[5D Chess] 关闭本地 Flask 服务。"
        Stop-Process -Id $server.Id -Force
    }
}
