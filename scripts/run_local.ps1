param(
    [string]$ModelsDir = "",
    [string]$ServerPath = "",
    [string]$PythonPath = "",
    [ValidateSet("all_4b", "answer_8b", "two_phase")]
    [string]$ModelProfile = "answer_8b",
    [ValidateSet("base_8b", "lora_4b", "lora_8b", "lora_8b_sft_3000")]
    [string]$PlannerVariant = "lora_8b_sft_3000",
    [ValidateSet("terminal", "server")]
    [string]$AppMode = "terminal",
    [int]$Port = 8080,
    [int]$ContextSize = 20000,
    [string]$FactAdapterPath = "",
    [string]$PlannerAdapterPath = "",
    [string]$Planner8BAdapterPath = "",
    [string]$PlannerCandidateAdapterPath = "",
    [string]$PlannerReviseAdapterPath = "",
    [string]$PlannerFullReviseAdapterPath = "",
    [string]$ClaimVerifierAdapterPath = "",
    [string]$ModelsPresetPath = "",
    [switch]$PipelineDebug,
    [int]$DebugMaxChars = 200000
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$bundledLocalAi = Join-Path $projectRoot "vendor\local-ai"
$bundledModels = Join-Path $bundledLocalAi "models"
$bundledServer = Join-Path $bundledLocalAi "llama.cpp\llama-server.exe"
if (-not $ModelsDir) {
    $ModelsDir = if (Test-Path -LiteralPath $bundledModels -PathType Container) {
        $bundledModels
    }
    else {
        "C:\local-ai\models"
    }
}
if (-not $ServerPath) {
    $ServerPath = if (Test-Path -LiteralPath $bundledServer -PathType Leaf) {
        $bundledServer
    }
    else {
        "C:\local-ai\llama.cpp\llama-server.exe"
    }
}
$bundledEmbedding = Join-Path $projectRoot "vendor\huggingface\models\bge-m3"
$bundledReranker = Join-Path $projectRoot "vendor\huggingface\models\bge-reranker-v2-m3"
if (Test-Path -LiteralPath $bundledEmbedding -PathType Container) {
    $env:EMBEDDING_MODEL = $bundledEmbedding
}
if (Test-Path -LiteralPath $bundledReranker -PathType Container) {
    $env:RERANKER_MODEL = $bundledReranker
}
$factModelId = "Fact-Qwen3-8B-LoRA"
$planner4BLoraModelId = "Planner-Qwen3-4B-LoRA"
$planner8BLoraModelId = "Planner-Qwen3-8B-LoRA"
$plannerCandidateModelId = "Planner-Qwen3-8B-SFT-3000"
$plannerReviseModelId = "Planner-Revise-Qwen3-8B-LoRA"
$plannerFullReviseModelId = "Planner-Full-Revise-Qwen3-8B-LoRA"
$claimVerifierModelId = "Claim-Verifier-Qwen3-8B-LoRA"
$plannerModelId = switch ($PlannerVariant) {
    "base_8b" { "Qwen3-8B-Q5_K_M" }
    "lora_4b" { $planner4BLoraModelId }
    "lora_8b" { $planner8BLoraModelId }
    "lora_8b_sft_3000" { $plannerCandidateModelId }
}
$productionModelsDir = Join-Path $projectRoot "models\adapters"
if (-not $FactAdapterPath) {
    $FactAdapterPath = Join-Path $productionModelsDir "fact_qwen3_8b_lora\gguf\fact-qwen3-8b-lora-f16.gguf"
}
if (-not $PlannerAdapterPath) {
    $PlannerAdapterPath = Join-Path $productionModelsDir "planner_qwen3_4b_lora\gguf\planner-qwen3-4b-lora-f16.gguf"
}
if (-not $Planner8BAdapterPath) {
    $Planner8BAdapterPath = Join-Path $productionModelsDir "planner_qwen3_8b_lora\gguf\planner-qwen3-8b-lora-f16.gguf"
}
if (-not $PlannerCandidateAdapterPath) {
    $PlannerCandidateAdapterPath = Join-Path $productionModelsDir "planner_qwen3_8b_sft_3000_candidate\gguf\planner-qwen3-8b-sft-3000-f16.gguf"
}
if (-not $PlannerReviseAdapterPath) {
    $PlannerReviseAdapterPath = Join-Path $productionModelsDir "planner_revise_qwen3_8b_lora\gguf\planner-revise-qwen3-8b-lora-f16.gguf"
}
if (-not $PlannerFullReviseAdapterPath) {
    $PlannerFullReviseAdapterPath = Join-Path $productionModelsDir "planner_full_revise_qwen3_8b_lora\gguf\planner-full-revise-qwen3-8b-lora-f16.gguf"
}
if (-not $ClaimVerifierAdapterPath) {
    $ClaimVerifierAdapterPath = Join-Path $productionModelsDir "claim_verifier_qwen3_8b_lora\gguf\claim-verifier-qwen3-8b-lora-f16.gguf"
}
if (-not $ModelsPresetPath) {
    $ModelsPresetPath = Join-Path $projectRoot "runtime\llama-models.ini"
}
$baseRequiredModels = @("Qwen3-4B-Q4_K_M", "Qwen3-8B-Q5_K_M")
$requiredModels = @(
    $baseRequiredModels
    $factModelId
    $planner4BLoraModelId
    $planner8BLoraModelId
    $plannerCandidateModelId
    $plannerReviseModelId
    $plannerFullReviseModelId
    $claimVerifierModelId
)
$requiredModels = @($requiredModels | Select-Object -Unique)

function Get-LocalModelIds {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2
        return @($response.data | ForEach-Object { $_.id })
    }
    catch {
        return @()
    }
}

function Find-Python {
    param([string]$RequestedPath)

    $candidates = @(
        @(
            $RequestedPath,
            (Join-Path $projectRoot ".venv\Scripts\python.exe"),
            (Join-Path $projectRoot "venv\Scripts\python.exe"),
            $env:CONDA_PYTHON_EXE
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    )
    if ($candidates.Count -gt 0) {
        return $candidates[0]
    }
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }
    throw "Không tìm thấy Python. Hãy kích hoạt môi trường Python rồi chạy lại, hoặc truyền -PythonPath."
}

$startedServer = $false
$serverProcess = $null
$preexistingServerPids = @()

try {
    if (-not (Test-Path -LiteralPath $ModelsDir -PathType Container)) {
        throw "Không tìm thấy thư mục model: $ModelsDir"
    }
    foreach ($modelId in $baseRequiredModels) {
        $modelPath = Join-Path $ModelsDir "$modelId.gguf"
        if (-not (Test-Path -LiteralPath $modelPath)) {
            throw "Không tìm thấy model: $modelPath"
        }
    }
    if (-not (Test-Path -LiteralPath $FactAdapterPath -PathType Leaf)) {
        throw "Không tìm thấy Fact LoRA GGUF: $FactAdapterPath"
    }
    if (-not (Test-Path -LiteralPath $PlannerAdapterPath -PathType Leaf)) {
        throw "Không tìm thấy Planner LoRA 4B GGUF: $PlannerAdapterPath"
    }
    if (-not (Test-Path -LiteralPath $Planner8BAdapterPath -PathType Leaf)) {
        throw "Không tìm thấy Planner LoRA 8B GGUF: $Planner8BAdapterPath"
    }
    if (-not (Test-Path -LiteralPath $PlannerCandidateAdapterPath -PathType Leaf)) {
        throw "Không tìm thấy Planner SFT 3000 GGUF: $PlannerCandidateAdapterPath"
    }
    if (-not (Test-Path -LiteralPath $PlannerReviseAdapterPath -PathType Leaf)) {
        throw "Không tìm thấy Planner Revise LoRA 8B GGUF: $PlannerReviseAdapterPath"
    }
    if (-not (Test-Path -LiteralPath $PlannerFullReviseAdapterPath -PathType Leaf)) {
        throw "Không tìm thấy Planner Full Revise LoRA GGUF: $PlannerFullReviseAdapterPath"
    }
    if (-not (Test-Path -LiteralPath $ClaimVerifierAdapterPath -PathType Leaf)) {
        throw "Không tìm thấy Claim Verifier LoRA GGUF: $ClaimVerifierAdapterPath"
    }
    if (-not (Test-Path -LiteralPath $ServerPath)) {
        throw "Không tìm thấy llama-server: $ServerPath"
    }

    $base4BPath = [System.IO.Path]::GetFullPath((Join-Path $ModelsDir "Qwen3-4B-Q4_K_M.gguf"))
    $base8BPath = [System.IO.Path]::GetFullPath((Join-Path $ModelsDir "Qwen3-8B-Q5_K_M.gguf"))
    $factAdapterFullPath = [System.IO.Path]::GetFullPath($FactAdapterPath)
    $planner4BAdapterFullPath = [System.IO.Path]::GetFullPath($PlannerAdapterPath)
    $planner8BAdapterFullPath = [System.IO.Path]::GetFullPath($Planner8BAdapterPath)
    $plannerCandidateAdapterFullPath = [System.IO.Path]::GetFullPath($PlannerCandidateAdapterPath)
    $plannerReviseAdapterFullPath = [System.IO.Path]::GetFullPath($PlannerReviseAdapterPath)
    $plannerFullReviseAdapterFullPath = [System.IO.Path]::GetFullPath($PlannerFullReviseAdapterPath)
    $claimVerifierAdapterFullPath = [System.IO.Path]::GetFullPath($ClaimVerifierAdapterPath)
    $presetDirectory = Split-Path -Parent $ModelsPresetPath
    New-Item -ItemType Directory -Path $presetDirectory -Force | Out-Null
    $presetContent = @"
version = 1

[Qwen3-4B-Q4_K_M]
model = $base4BPath
ctx-size = $ContextSize
jinja = true
load-on-startup = false
stop-timeout = 30

[Qwen3-8B-Q5_K_M]
model = $base8BPath
ctx-size = $ContextSize
jinja = true
load-on-startup = false
stop-timeout = 30

[$factModelId]
model = $base8BPath
lora = $factAdapterFullPath
ctx-size = $ContextSize
jinja = true
load-on-startup = false
stop-timeout = 30

[$planner4BLoraModelId]
model = $base4BPath
lora = $planner4BAdapterFullPath
ctx-size = $ContextSize
jinja = true
load-on-startup = false
stop-timeout = 30

[$planner8BLoraModelId]
model = $base8BPath
lora = $planner8BAdapterFullPath
ctx-size = $ContextSize
jinja = true
load-on-startup = false
stop-timeout = 30

[$plannerCandidateModelId]
model = $base8BPath
lora = $plannerCandidateAdapterFullPath
ctx-size = $ContextSize
jinja = true
load-on-startup = false
stop-timeout = 30

[$plannerReviseModelId]
model = $base8BPath
lora = $plannerReviseAdapterFullPath
ctx-size = $ContextSize
jinja = true
load-on-startup = false
stop-timeout = 30

[$plannerFullReviseModelId]
model = $base8BPath
lora = $plannerFullReviseAdapterFullPath
ctx-size = $ContextSize
jinja = true
load-on-startup = false
stop-timeout = 30

[$claimVerifierModelId]
model = $base8BPath
lora = $claimVerifierAdapterFullPath
ctx-size = $ContextSize
jinja = true
load-on-startup = false
stop-timeout = 30
"@
    [System.IO.File]::WriteAllText(
        [System.IO.Path]::GetFullPath($ModelsPresetPath),
        $presetContent,
        [System.Text.UTF8Encoding]::new($false)
    )

    $modelIds = Get-LocalModelIds
    if ($modelIds.Count -gt 0) {
        $missingIds = @($requiredModels | Where-Object { $_ -notin $modelIds })
        if ($missingIds.Count -gt 0) {
            throw "Cổng $Port đang chạy server cũ và thiếu model: $($missingIds -join ', '). Hãy tắt server cũ rồi mở launcher lại."
        }
        Write-Host "Multi-model server đã chạy sẵn tại cổng $Port." -ForegroundColor Green
    }
    else {
        Write-Host "Đang khởi động local model router (chỉ nạp một model cùng lúc)..." -ForegroundColor Cyan
        $preexistingServerPids = @(
            Get-Process -Name "llama-server" -ErrorAction SilentlyContinue |
                ForEach-Object { $_.Id }
        )
        $serverArguments = @(
            "--models-dir", $ModelsDir,
            "--models-preset", $ModelsPresetPath,
            "--models-max", "1",
            "--models-autoload",
            "--sleep-idle-seconds", "60",
            "--host", "127.0.0.1",
            "--port", "$Port",
            "--ctx-size", "$ContextSize",
            "--temp", "0.35",
            "--top-p", "0.9",
            "--repeat-penalty", "1.1",
            "--cache-type-k", "q8_0",
            "--cache-type-v", "q8_0",
            "--flash-attn", "on",
            "--n-gpu-layers", "all",
            "--batch-size", "256",
            "--ubatch-size", "128",
            "--jinja"
        )
        $serverProcess = Start-Process `
            -FilePath $ServerPath `
            -ArgumentList $serverArguments `
            -PassThru `
            -WindowStyle Hidden
        $startedServer = $true

        $ready = $false
        for ($attempt = 1; $attempt -le 90; $attempt++) {
            Start-Sleep -Seconds 1
            $modelIds = Get-LocalModelIds
            if (($requiredModels | Where-Object { $_ -notin $modelIds }).Count -eq 0) {
                $ready = $true
                break
            }
            if ($serverProcess.HasExited) {
                throw "llama-server đã dừng trong lúc khởi tạo router."
            }
            Write-Progress -Activity "Đang khởi tạo multi-model server" -Status "$attempt/90 giây" -PercentComplete (($attempt / 90) * 100)
        }
        Write-Progress -Activity "Đang khởi tạo multi-model server" -Completed
        if (-not $ready) {
            throw "Multi-model server chưa sẵn sàng sau 90 giây."
        }
        Write-Host "Multi-model server đã sẵn sàng." -ForegroundColor Green
    }

    $answerModel = if ($ModelProfile -in @("answer_8b", "two_phase")) { "Qwen3-8B-Q5_K_M" } else { "Qwen3-4B-Q4_K_M" }
    $evidenceModel = if ($ModelProfile -in @("answer_8b", "two_phase")) { $answerModel } else { "Qwen3-4B-Q4_K_M" }
    $researchModel = if ($ModelProfile -eq "answer_8b") { $plannerModelId } else { "Qwen3-4B-Q4_K_M" }
    # In 8B profiles, the audit checks whether an answer over-applies a
    # conditional rule. It reuses the reasoning model after retrieval is off GPU.
    $critiqueModel = if ($ModelProfile -in @("answer_8b", "two_phase")) { $answerModel } else { "Qwen3-4B-Q4_K_M" }
    $env:MODEL_PROFILE = $ModelProfile
    $env:TERMINAL_PIPELINE = "clean"
    # Web/API remains on the current production pipeline. The replacement is
    # promoted first through terminal chat as requested.
    $env:AGENT_PIPELINE = "clean"
    $env:VN_LAND_LOCAL_ONLY = "true"
    # the parent shell. Research runners may opt in separately under research/.
    @(
        "ENABLE_HEURISTIC_CONDITION_REWRITE",
        "ENABLE_HEURISTIC_CONDITION_PREFILTER",
        "ENABLE_HARD_CONDUCT_REGEX_GATE",
        "ENABLE_HARD_TRANSACTION_SUBTYPE_GATE",
        "ENABLE_HEURISTIC_SELECTION_REWRITE",
        "ENABLE_HEURISTIC_CLAIM_PREFILTER",
        "ENABLE_EXACT_SOURCE_RECOVERY",
        "ENABLE_HEURISTIC_PLANNER_TEMPLATE_REWRITE",
        "ENABLE_FORCED_TRANSFER_COVERAGE",
        "ENABLE_LEXICAL_GROUNDING_AS_PRIMARY"
    ) | ForEach-Object { Set-Item -Path "Env:$_" -Value "false" }
    $env:LOCAL_LLM_MODEL = $answerModel
    $env:LOCAL_LLM_TEMPERATURE = "0.35"
    $env:LOCAL_LLM_TOP_P = "0.9"
    $env:LOCAL_LLM_REPETITION_PENALTY = "1.1"
    $env:LOCAL_LLM_DISABLE_THINKING = "true"
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    $env:PLANNING_MODEL = "Qwen3-4B-Q4_K_M"
    $env:ROUTER_MODEL = "Qwen3-8B-Q5_K_M"
    $env:FACT_MODEL = $factModelId
    $env:PLANNER_MODEL = $plannerModelId
    $env:PLANNER_REVISE_MODEL = $plannerReviseModelId
    $env:PLANNER_FULL_REVISE_MODEL = $plannerFullReviseModelId
    $env:PLANNER_4B_MODEL = $planner4BLoraModelId
    $env:PLANNER_8B_MODEL = $plannerModelId
    $env:PLANNER_VARIANT = $PlannerVariant
    $env:PLANNER_CONTRACT_VARIANT = if ($PlannerVariant -eq "lora_8b_sft_3000") { "candidate_3000" } else { "baseline" }
    $env:DECOMPOSER_MODEL = "Qwen3-4B-Q4_K_M"
    $env:AGENT_MODEL = $researchModel
    $env:EVIDENCE_MODEL = $evidenceModel
    $env:ADJUDICATOR_MODEL = $answerModel
    $env:CLAIM_VERIFIER_MODEL = $claimVerifierModelId
    $env:CLAIM_VERIFIER_ENABLED = "true"
    # Giữ biến cũ trong một chu kỳ chuyển tiếp cho các entry point chưa đổi tên.
    $env:CLAIM_EXTRACTOR_PARALLEL = "true"
    $env:CLAIM_EXTRACTOR_WORKERS = "3"
    $env:CLAIM_VERIFIER_WORKERS = "4"
    $env:CONDITION_EXTRACTOR_WORKERS = "2"
    $env:CONDITION_MATCHER_WORKERS = "4"
    $env:CRITIQUE_MODEL = $critiqueModel
    $env:AUTO_EVIDENCE_RECOVERY = "true"
    $env:PIPELINE_INCREMENTAL_RECOVERY_ENABLED = "true"
    $env:PIPELINE_RECOVERY_MAX_REQUIREMENTS = "2"
    $env:PIPELINE_ANSWER_CONTROL_ENABLED = "true"
    $env:MAX_PLAN_REFINE_LOOPS = "1"
    # Full Revise dùng trực tiếp Audit và Request Anchor. Chỉ dẫn chi tiết
    # là bước tùy chọn, không bắt buộc thêm một lượt LLM.
    $env:PLANNER_STRUCTURED_REPAIR_ENABLED = "false"
    $env:PIPELINE_DEBUG = $PipelineDebug.IsPresent.ToString().ToLowerInvariant()
    $env:PIPELINE_DEBUG_MAX_CHARS = [string]$DebugMaxChars
    if ($PipelineDebug.IsPresent) {
        $env:HF_HUB_DISABLE_PROGRESS_BARS = "0"
        $env:TQDM_DISABLE = "0"
        $env:TRANSFORMERS_VERBOSITY = "warning"
    }
    else {
        $env:HF_HUB_DISABLE_PROGRESS_BARS = "1"
        $env:TQDM_DISABLE = "1"
        $env:TRANSFORMERS_VERBOSITY = "error"
    }

    Write-Host "Planner đang dùng: $plannerModelId ($PlannerVariant)." -ForegroundColor Green
    Write-Host "Planner Full Revise đang dùng: $plannerFullReviseModelId." -ForegroundColor Green
    Write-Host "Pipeline: clean." -ForegroundColor Green
    if ($AppMode -eq "server") {
        Write-Host "Chế độ server-only: không nạp app, embedding hoặc reranker." -ForegroundColor Green
        Write-Host "Giữ cửa sổ này mở khi chạy evaluation ở terminal khác." -ForegroundColor Cyan
        Write-Host "Nhấn Ctrl+C để tắt llama-server và giải phóng GPU." -ForegroundColor Yellow
        while ($true) {
            Start-Sleep -Seconds 5
            if ($serverProcess -and $serverProcess.HasExited) {
                throw "llama-server đã dừng khi đang chạy chế độ server-only."
            }
            if ((Get-LocalModelIds).Count -eq 0) {
                throw "Cổng $Port không còn phản hồi danh sách model."
            }
        }
    }
    else {
        $python = Find-Python -RequestedPath $PythonPath
        $entryPoint = "main.py"
        Write-Host "Đang mở VN Land Counsel ($AppMode)..." -ForegroundColor Cyan
        & $python (Join-Path $projectRoot $entryPoint)
    }
}
finally {
    if ($startedServer -and $serverProcess -and -not $serverProcess.HasExited) {
        Write-Host "Đang tắt multi-model server và giải phóng GPU..." -ForegroundColor Yellow
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($startedServer) {
        # The llama.cpp model router may spawn one backend worker per loaded
        # model.  If the proxy exits first, that worker can remain orphaned.
        # Stop only processes created during this launcher session.
        Get-Process -Name "llama-server" -ErrorAction SilentlyContinue |
            Where-Object { $_.Id -notin $preexistingServerPids } |
            Stop-Process -Force -ErrorAction SilentlyContinue
    }
}
