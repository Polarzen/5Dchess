param(
    [string]$Checkpoint = "runs\run-001\best",
    [ValidateSet("easy", "medium", "hard")]
    [string]$Opponent = "medium",
    [int]$Games = 20,
    [ValidateSet("auto", "cpu", "cuda")]
    [string]$Device = "auto",
    [int]$Seed = 100,
    [int]$MaxActions = 120
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Root ".venv-training\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\training\setup_training.ps1 first." }
$CheckpointPath = if ([IO.Path]::IsPathRooted($Checkpoint)) { $Checkpoint } else { Join-Path $Root $Checkpoint }
Push-Location $Root
try {
    & $Python -m src.training.arena `
        --checkpoint $CheckpointPath `
        --opponent $Opponent `
        --games $Games `
        --device $Device `
        --seed $Seed `
        --max-actions $MaxActions
} finally { Pop-Location }
exit $LASTEXITCODE
