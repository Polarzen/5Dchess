param(
    [ValidateSet("auto", "cpu", "cuda")]
    [string]$Device = "cpu",
    [string]$WorkDir = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Root ".venv-training\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\training\setup_training.ps1 first." }
$Args = @("-m", "src.training.smoke", "--device", $Device)
if ($WorkDir) {
    $Resolved = if ([IO.Path]::IsPathRooted($WorkDir)) { $WorkDir } else { Join-Path $Root $WorkDir }
    $Args += @("--work-dir", $Resolved)
}
Push-Location $Root
try { & $Python @Args } finally { Pop-Location }
exit $LASTEXITCODE
