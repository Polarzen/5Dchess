[CmdletBinding()]
param(
    [string]$SoftwareDirectory = 'D:\p2p',
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'p2p_common.ps1')

# Pin the official release and verify bytes before executing or replacing it.
$release = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'p2p/cloudflared-release.json') -Raw | ConvertFrom-Json
if ($release.platform -ne 'windows-amd64' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'This installer requires 64-bit Windows (amd64).'
}
if ($release.url -notmatch '^https://github\.com/cloudflare/cloudflared/releases/download/[0-9.]+/cloudflared-windows-amd64\.exe$' -or $release.sha256 -notmatch '^[a-f0-9]{64}$') {
    throw 'Invalid cloudflared release manifest.'
}
$installDir = Join-Path ([IO.Path]::GetFullPath($SoftwareDirectory)) 'cloudflared'
New-Item -ItemType Directory -Path $installDir -Force | Out-Null
$executable = Join-Path $installDir 'cloudflared.exe'
$installedHash = if (Test-Path -LiteralPath $executable) { (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash } else { '' }
if ($installedHash -ine $release.sha256) {
    $download = Join-Path $installDir ('.download-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        Write-Host "Downloading official cloudflared $($release.version) to $installDir"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -UseBasicParsing -Uri $release.url -OutFile $download -TimeoutSec 180
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ine $release.sha256) {
            throw 'cloudflared SHA256 mismatch; downloaded file will not be installed.'
        }
        if (Test-Path -LiteralPath $executable) {
            Copy-Item -LiteralPath $executable -Destination ($executable + '.backup-' + [Guid]::NewGuid().ToString('N'))
        }
        Move-Item -LiteralPath $download -Destination $executable -Force
    } finally {
        if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download }
    }
}
& $executable --version
if ($LASTEXITCODE -ne 0) { throw 'cloudflared version check failed.' }

$projectPython = Join-Path $ProjectRoot '.venv311\Scripts\python.exe'
if ($PythonPath) {
    $basePython = Resolve-P2PPython -ProjectRoot $ProjectRoot -PythonPath $PythonPath
} elseif (Test-Path -LiteralPath $projectPython) {
    $basePython = $projectPython
} else {
    $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
    if (-not $launcher) { throw 'Install Python 3.11 first (new software belongs in D:\p2p), or specify -PythonPath.' }
    $basePython = [string](& $launcher.Source -3.11 -c 'import sys; print(sys.executable)')
    if ($LASTEXITCODE -ne 0 -or -not $basePython) { throw 'Python 3.11 missing; install it or specify -PythonPath.' }
}
& $basePython -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
if ($LASTEXITCODE -ne 0) { throw 'Python version check failed.' }
if (-not (Test-Path -LiteralPath $projectPython)) {
    & $basePython -m venv (Join-Path $ProjectRoot '.venv311')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create project virtual environment.' }
}
& $projectPython -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Project dependency installation failed.' }
& (Join-Path $PSScriptRoot 'start_p2p.ps1') -Check -PythonPath $projectPython -CloudflaredPath $executable
Write-Host 'Ready. Start online play: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_p2p.ps1'
if ($SoftwareDirectory -ne 'D:\p2p') { Write-Host "Custom installation: pass -CloudflaredPath `"$executable`" when starting." }
