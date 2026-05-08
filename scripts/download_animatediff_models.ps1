param(
    [string]$ComfyUIRoot = "C:\ComfyUI",
    [int]$RetryCount = 3,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step([string]$Message) {
    Write-Host "[AnimateDiff Download] $Message" -ForegroundColor Cyan
}

function Ensure-Directory([string]$Path) {
    if (-not (Test-Path $Path)) {
        New-Item -Path $Path -ItemType Directory -Force | Out-Null
    }
}

function Invoke-DownloadWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][Int64]$MinExpectedSize,
        [Parameter(Mandatory = $true)][int]$RetryCount,
        [switch]$Force
    )

    if ((Test-Path $Destination) -and -not $Force) {
        $existing = Get-Item $Destination
        if ($existing.Length -ge $MinExpectedSize) {
            Write-Step "Skip existing file: $Destination ($([math]::Round($existing.Length / 1GB, 2)) GB)"
            return
        }
        Write-Step "Existing file is too small, re-downloading: $Destination"
    }

    $tmp = "$Destination.part"
    if (Test-Path $tmp) {
        Remove-Item $tmp -Force
    }

    for ($i = 1; $i -le $RetryCount; $i++) {
        try {
            Write-Step "Downloading ($i/$RetryCount): $Url"
            Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -MaximumRedirection 10 -TimeoutSec 0

            if (-not (Test-Path $tmp)) {
                throw "Download did not produce output file: $tmp"
            }

            $size = (Get-Item $tmp).Length
            if ($size -lt $MinExpectedSize) {
                throw "Downloaded file is too small ($size bytes), expected at least $MinExpectedSize bytes"
            }

            Move-Item -Path $tmp -Destination $Destination -Force
            Write-Step "Downloaded OK: $Destination ($([math]::Round($size / 1GB, 2)) GB)"
            return
        }
        catch {
            Write-Warning "Download failed on attempt ${i}: $($_.Exception.Message)"
            if ($i -eq $RetryCount) {
                throw
            }
        }
    }
}

$checkpointsDir = Join-Path $ComfyUIRoot "models\checkpoints"
$animatediffDir = Join-Path $ComfyUIRoot "models\animatediff_models"

Ensure-Directory -Path $checkpointsDir
Ensure-Directory -Path $animatediffDir

$jobs = @(
    @{
        Name = "SD1.5 checkpoint"
        Url = "https://huggingface.co/runwayml/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors?download=true"
        Destination = (Join-Path $checkpointsDir "v1-5-pruned-emaonly.safetensors")
        MinExpectedSize = 3800000000
    },
    @{
        Name = "AnimateDiff motion module"
        Url = "https://huggingface.co/guoyww/animatediff/resolve/main/mm_sd_v15_v2.ckpt?download=true"
        Destination = (Join-Path $animatediffDir "mm_sd_v15_v2.ckpt")
        MinExpectedSize = 45000000
    }
)

Write-Step "ComfyUI root: $ComfyUIRoot"
Write-Step "Target checkpoint dir: $checkpointsDir"
Write-Step "Target AnimateDiff dir: $animatediffDir"

foreach ($job in $jobs) {
    Write-Step "Start: $($job.Name)"
    Invoke-DownloadWithRetry -Url $job.Url -Destination $job.Destination -MinExpectedSize $job.MinExpectedSize -RetryCount $RetryCount -Force:$Force
}

Write-Step "All downloads completed."
Write-Step "Next: restart ComfyUI, then run:"
Write-Host "  uv run python scripts/validate_animatediff_smoke.py --timeout 600 --report-file output/animatediff_smoke_report.json" -ForegroundColor Green
