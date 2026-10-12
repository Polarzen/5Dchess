param(
    [int]$Games = 100,
    [ValidateSet("easy", "medium", "hard", "mixed")]
    [string]$Teacher = "mixed",
    [string]$Output = "datasets\selfplay-001",
    [int]$Seed = 42,
    [int]$MaxActions = 200,
    [switch]$DeterministicPlanner,
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Root ".venv-training\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\training\setup_training.ps1 first." }
$OutputPath = if ([IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $Root $Output }
$Args = @(
    "-m", "src.training.selfplay",
    "--games", "$Games",
    "--teacher", $Teacher,
    "--output", $OutputPath,
    "--seed", "$Seed",
    "--max-actions", "$MaxActions"
)
if ($DeterministicPlanner) { $Args += "--deterministic-planner" }
if ($Resume) { $Args += "--resume" }
Push-Location $Root
try { & $Python @Args } finally { Pop-Location }
exit $LASTEXITCODE
