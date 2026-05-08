param(
    [Parameter(Mandatory=$true)]
    [string]$ComfyUIRoot
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "[AnimateDiff Setup] $msg" -ForegroundColor Cyan
}

function Ensure-Git {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is not installed or not in PATH."
    }
}

function Resolve-Python($root) {
    $embedded = Join-Path $root "python_embeded\python.exe"
    if (Test-Path $embedded) {
        return $embedded
    }

    $venv = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $venv) {
        return $venv
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }

    throw "No Python runtime found for ComfyUI."
}

function Sync-Repo($targetDir, $repoUrl) {
    if (Test-Path $targetDir) {
        $gitDir = Join-Path $targetDir ".git"
        if (Test-Path $gitDir) {
            Write-Step "Updating $(Split-Path $targetDir -Leaf)"
            Push-Location $targetDir
            try {
                git pull
            }
            finally {
                Pop-Location
            }
        }
        else {
            $backupDir = "$targetDir.bak_$(Get-Date -Format yyyyMMdd_HHmmss)"
            Write-Step "Existing non-git folder detected, backing up to $(Split-Path $backupDir -Leaf)"
            Move-Item -Path $targetDir -Destination $backupDir
            Write-Step "Cloning $(Split-Path $targetDir -Leaf)"
            git clone $repoUrl $targetDir
        }
    }
    else {
        Write-Step "Cloning $(Split-Path $targetDir -Leaf)"
        git clone $repoUrl $targetDir
    }
}

function Install-Requirements($pythonExe, $repoDir) {
    $requirements = Join-Path $repoDir "requirements.txt"
    if (Test-Path $requirements) {
        Write-Step "Installing requirements for $(Split-Path $repoDir -Leaf)"
        & $pythonExe -m pip install -r $requirements
    }
}

$ComfyUIRoot = (Resolve-Path $ComfyUIRoot).Path
$customNodes = Join-Path $ComfyUIRoot "custom_nodes"

if (-not (Test-Path $customNodes)) {
    throw "custom_nodes directory not found under: $ComfyUIRoot"
}

Ensure-Git
$pythonExe = Resolve-Python -root $ComfyUIRoot
Write-Step "Using Python: $pythonExe"

$repos = @(
    @{ Name = "ComfyUI-Manager"; Url = "https://github.com/ltdrdata/ComfyUI-Manager.git" },
    @{ Name = "ComfyUI-AnimateDiff-Evolved"; Url = "https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git" },
    @{ Name = "ComfyUI-VideoHelperSuite"; Url = "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git" },
    @{ Name = "ComfyUI-Custom-Scripts"; Url = "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git" }
)

foreach ($repo in $repos) {
    $target = Join-Path $customNodes $repo.Name
    Sync-Repo -targetDir $target -repoUrl $repo.Url
    Install-Requirements -pythonExe $pythonExe -repoDir $target
}

Write-Step "Done. Restart ComfyUI now."
Write-Host ""
Write-Host "Next actions:" -ForegroundColor Yellow
Write-Host "1) Put SD1.5 model into models/checkpoints" -ForegroundColor Yellow
Write-Host "2) Put AnimateDiff motion model (example: mm_sd_v15_v2.ckpt) into models/animatediff_models" -ForegroundColor Yellow
Write-Host "3) In this project set comfyui.video.default_workflow to selfhost/video_animatediff_sd15.json" -ForegroundColor Yellow
