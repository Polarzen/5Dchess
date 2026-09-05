param(
    [string]$Dataset = "datasets\selfplay-001",
    [string]$Run = "runs\run-001",
    [int]$Epochs = 50,
    [int]$BatchSize = 64,
    [double]$LearningRate = 0.0003,
    [ValidateSet("auto", "cpu", "cuda")]
    [string]$Device = "auto",
    [ValidateSet("tiny", "small", "medium")]
    [string]$Preset = "small",
    [int]$Seed = 42,
    [int]$NumWorkers = 0
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Root ".venv-training\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\training\setup_training.ps1 first." }
$DatasetPath = if ([IO.Path]::IsPathRooted($Dataset)) { $Dataset } else { Join-Path $Root $Dataset }
$RunPath = if ([IO.Path]::IsPathRooted($Run)) { $Run } else { Join-Path $Root $Run }
Push-Location $Root
try {
    & $Python -m src.training.train `
        --dataset $DatasetPath `
        --output $RunPath `
        --epochs $Epochs `
        --batch-size $BatchSize `
        --lr $LearningRate `
        --device $Device `
        --preset $Preset `
        --seed $Seed `
        --num-workers $NumWorkers
} finally { Pop-Location }
exit $LASTEXITCODE
