# Functions only. Downloads and processes begin only when called by the launcher.
function Get-VerifiedLauncherDownload {
    param([string]$Url, [string]$Sha256, [string]$Destination)
    if ($Url -notmatch '^https://' -or $Sha256 -notmatch '^[a-fA-F0-9]{64}$') {
        throw '下载清单无效，请重新下载完整项目。'
    }
    if ((Test-Path -LiteralPath $Destination) -and (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ieq $Sha256) {
        return
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    $temporary = $Destination + '.download-' + [Guid]::NewGuid().ToString('N')
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                Write-Host "正在下载运行组件（$attempt/3）：$Url"
                Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $temporary -TimeoutSec 120
                break
            } catch {
                if ($attempt -eq 3) { throw "下载失败，请检查网络后重新双击启动：$Url" }
                Start-Sleep -Seconds 2
            }
        }
        if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash -ine $Sha256) {
            throw '下载文件校验失败，已拒绝使用。请检查网络后重试或重新下载项目。'
        }
        Move-Item -LiteralPath $temporary -Destination $Destination -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}

function Enter-LauncherLock {
    param([string]$RuntimeDirectory)
    # An OS file handle prevents racing launches; process exit releases it even
    # after a crash, so there is no stale PID file to delete on the next launch.
    try {
        return [IO.File]::Open((Join-Path $RuntimeDirectory 'launcher.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        throw '本项目已有启动窗口（可能正在安装或运行）。请使用原窗口；切换本地/远程前，先在原窗口按 Ctrl+C。'
    }
}

function Initialize-LauncherPython {
    param([string]$ProjectRoot, [string]$RuntimeDirectory)
    $release = Get-Content -LiteralPath (Join-Path $ProjectRoot 'scripts/p2p/python-runtime.json') -Raw | ConvertFrom-Json
    if ($release.platform -ne 'windows-amd64' -or $release.version -notmatch '^3\.11\.\d+$' -or $release.url -ne "https://api.nuget.org/v3-flatcontainer/python/$($release.version)/python.$($release.version).nupkg") {
        throw 'Python 运行时清单无效，请重新下载完整项目。'
    }
    $installation = Join-Path $RuntimeDirectory ('python-' + $release.version)
    $python = Join-Path $installation 'tools/python.exe'
    $ready = Join-Path $installation '.extracted'
    $extractedHash = if (Test-Path -LiteralPath $ready) { (Get-Content -LiteralPath $ready -Raw).Trim() } else { '' }
    if ($extractedHash -ine $release.sha256 -or -not (Test-Path -LiteralPath $python)) {
        $package = Join-Path $RuntimeDirectory ('downloads/python-' + $release.version + '.zip')
        Get-VerifiedLauncherDownload -Url $release.url -Sha256 $release.sha256 -Destination $package
        # Keep interrupted extraction separate. Never run a partially extracted
        # runtime or remove an existing installation owned by the user.
        $staging = Join-Path $RuntimeDirectory ('extract-' + [Guid]::NewGuid().ToString('N'))
        $backup = $installation + '.backup-' + [Guid]::NewGuid().ToString('N')
        $expectedParent = [IO.Path]::GetFullPath($RuntimeDirectory).TrimEnd('\')
        foreach ($movePath in @($staging, $installation, $backup)) {
            if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($movePath)) -ne $expectedParent) { throw '运行时路径校验失败。' }
        }
        Write-Host '正在解压项目专用 Python（无需安装系统 Python）……'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($package, $staging)
        $stagedPython = Join-Path $staging 'tools/python.exe'
        & $stagedPython -I -c "import sys, struct, pip; assert sys.version_info[:3] == tuple(map(int, '$($release.version)'.split('.'))); assert struct.calcsize('P') == 8" | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '项目 Python 无法运行，请确认使用 Windows 10/11 x64，或查看日志。' }
        [IO.File]::WriteAllText((Join-Path $staging '.extracted'), $release.sha256)
        if (Test-Path -LiteralPath $installation) {
            Move-Item -LiteralPath $installation -Destination $backup
        }
        Move-Item -LiteralPath $staging -Destination $installation
    }
    $requirements = Join-Path $ProjectRoot 'requirements.txt'
    $requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $stamp = Join-Path $installation '.requirements-sha256'
    $installedHash = if (Test-Path -LiteralPath $stamp) { (Get-Content -LiteralPath $stamp -Raw).Trim() } else { '' }
    $env:PYGAME_HIDE_SUPPORT_PROMPT = '1'
    $importProbe = @'
import sys
try:
    import flask, numpy, pygame
except Exception:
    sys.exit(1)
'@
    & $python -I -X utf8 -c $importProbe | Out-Host
    $importsOk = $LASTEXITCODE -eq 0
    if (-not $importsOk -or $installedHash -ne $requirementsHash) {
        Write-Host '首次运行或依赖有更新，正在安装依赖；请等待完成，不要重复点击。'
        & $python -I -X utf8 -m pip --isolated --disable-pip-version-check install --only-binary=:all: --no-warn-script-location --timeout 30 --retries 2 --index-url https://pypi.org/simple -r $requirements | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。请检查网络后重新双击启动；已下载的内容可复用。' }
        & $python -I -X utf8 -m pip --isolated check | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '依赖不兼容，请保留日志并反馈。' }
        & $python -I -X utf8 -c 'import flask, numpy, pygame' | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '依赖导入失败，请保留日志并反馈。' }
        [IO.File]::WriteAllText($stamp, $requirementsHash)
    }
    return $python
}

function Initialize-LauncherCloudflared {
    param([string]$ProjectRoot, [string]$RuntimeDirectory)
    $release = Get-Content -LiteralPath (Join-Path $ProjectRoot 'scripts/p2p/cloudflared-release.json') -Raw | ConvertFrom-Json
    if ($release.platform -ne 'windows-amd64' -or $release.url -notmatch '^https://github\.com/cloudflare/cloudflared/releases/download/[0-9.]+/cloudflared-windows-amd64\.exe$') {
        throw 'Cloudflare 下载清单无效，请重新下载完整项目。'
    }
    $executable = Join-Path $RuntimeDirectory 'cloudflared/cloudflared.exe'
    Get-VerifiedLauncherDownload -Url $release.url -Sha256 $release.sha256 -Destination $executable
    return $executable
}
