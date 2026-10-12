param(
    [string]$Dataset = "datasets\selfplay-001",
    [string]$Run = "runs\run-001",
    [string]$Checkpoint = "runs\run-001\last",
    [int]$Epochs = 100,
    [int]$BatchSize = 64,
    [double]$LearningRate = 0.0003,
    [ValidateSet("auto", "cpu", "cuda")]
    [string]$Device = "auto",
    [int]$Seed = 42,
    [int]$NumWorkers = 0
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Root ".venv-training\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\training\setup_training.ps1 first." }
function Resolve-RepoPath([string]$Value) {
    if ([IO.Path]::IsPathRooted($Value)) { return $Value }
    return Join-Path $Root $Value
}
Push-Location $Root
try {
    & $Python -m src.training.train `
        --dataset (Resolve-RepoPath $Dataset) `
        --output (Resolve-RepoPath $Run) `
        --resume (Resolve-RepoPath $Checkpoint) `
        --epochs $Epochs `
        --batch-size $BatchSize `
        --lr $LearningRate `
        --device $Device `
        --seed $Seed `
        --num-workers $NumWorkers
} finally { Pop-Location }
exit $LASTEXITCODE
