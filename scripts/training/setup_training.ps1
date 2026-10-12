param(
    [string]$Python = "python",
    [ValidateSet("auto", "cpu", "existing")]
    [string]$TorchMode = "auto"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Venv = Join-Path $Root ".venv-training"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    & $Python -m venv $Venv
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")

function Test-TorchInstalled {
    & $VenvPython -c "import torch; print(torch.__version__)" *> $null
    return ($LASTEXITCODE -eq 0)
}

if ($TorchMode -eq "cpu") {
    & $VenvPython -m pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.4"
} elseif ($TorchMode -eq "existing") {
    if (-not (Test-TorchInstalled)) {
        throw "TorchMode=existing but torch is not installed in .venv-training"
    }
} else {
    if (-not (Test-TorchInstalled)) {
        $HasNvidia = $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
        if ($HasNvidia) {
            Write-Host "NVIDIA GPU detected, but no torch build is installed." -ForegroundColor Yellow
            Write-Host "Run nvidia-smi, then use the official PyTorch selector to install the matching CUDA build into:" -ForegroundColor Yellow
            Write-Host "  $Venv" -ForegroundColor Cyan
            Write-Host "After installing torch, rerun this script with -TorchMode existing." -ForegroundColor Yellow
            exit 2
        }
        Write-Host "No NVIDIA tool detected; installing the official CPU PyTorch wheel." -ForegroundColor Cyan
        & $VenvPython -m pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.4"
    }
}

& $VenvPython -m pip install "safetensors>=0.4.5" "numpy>=1.24"
Push-Location $Root
try {
    & $VenvPython scripts\training\check_device.py --device auto
} finally {
    Pop-Location
}

Write-Host "Training environment ready: $Venv" -ForegroundColor Green
