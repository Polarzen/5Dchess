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

function Resolve-P2PCloudflared {
    param([string]$ProjectRoot, [string]$CloudflaredPath)
    if ($CloudflaredPath) {
        if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) { throw "cloudflared not found: $CloudflaredPath" }
        return (Resolve-Path -LiteralPath $CloudflaredPath).Path
    }
    foreach ($candidate in @('D:\p2p\cloudflared\cloudflared.exe', (Join-Path $ProjectRoot 'cloudflared.exe'))) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $command = Get-Command cloudflared -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw 'cloudflared missing. Run scripts/setup_p2p.ps1 first, or use -LanOnly for LAN play.'
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
