param(
    [string]$ApiEnvPath = "D:\索尼实习\vlm\config\api.env",
    [string]$ClaudeSettingsPath = "$env:USERPROFILE\.claude\settings.json"
)

$ErrorActionPreference = "Stop"

function ConvertFrom-ApiEnvValue {
    param([string]$Value)

    $normalized = $Value.Trim()
    if (
        ($normalized.StartsWith("'") -and $normalized.EndsWith("'")) -or
        ($normalized.StartsWith('"') -and $normalized.EndsWith('"'))
    ) {
        return $normalized.Substring(1, $normalized.Length - 2)
    }
    return $normalized
}

function Read-ApiEnv {
    param([string]$Path)

    if (-not (Test-Path -Path $Path)) {
        throw "api.env not found: $Path"
    }

    $pairs = @{}
    Get-Content -Path $Path | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)\s*=\s*(.*)\s*$') {
            $pairs[$matches[1].Trim()] = ConvertFrom-ApiEnvValue $matches[2]
        }
    }
    return $pairs
}

$apiEnv = Read-ApiEnv $ApiEnvPath
if (-not $apiEnv.ContainsKey("DEEPSEEK_API_KEY")) {
    throw "DEEPSEEK_API_KEY is required in $ApiEnvPath for the DeepSeek Anthropic-compatible Claude Code gateway."
}

if (-not (Test-Path -Path $ClaudeSettingsPath)) {
    throw "Claude Code settings not found: $ClaudeSettingsPath"
}

$settings = Get-Content -Raw -Path $ClaudeSettingsPath | ConvertFrom-Json
if (-not $settings.env) {
    $settings | Add-Member -NotePropertyName env -NotePropertyValue ([pscustomobject]@{})
}

$settings.env.ANTHROPIC_AUTH_TOKEN = $apiEnv["DEEPSEEK_API_KEY"]
$settings.env.ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
$settings.env.CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = "0"

$settings.env.ANTHROPIC_MODEL = "deepseek-v4-pro[1m]"
$settings.env.CLAUDE_CODE_SUBAGENT_MODEL = "deepseek-v4-flash"

$settings.env.ANTHROPIC_DEFAULT_OPUS_MODEL = "deepseek-v4-pro[1m]"
$settings.env.ANTHROPIC_DEFAULT_OPUS_MODEL_NAME = "DeepSeek V4 Pro 1M"
$settings.env.ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION = "DeepSeek deep model for complex coding, reasoning, and long tasks."

$settings.env.ANTHROPIC_DEFAULT_SONNET_MODEL = "deepseek-v4-pro"
$settings.env.ANTHROPIC_DEFAULT_SONNET_MODEL_NAME = "DeepSeek V4 Pro"
$settings.env.ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION = "DeepSeek balanced model for day-to-day coding and project maintenance."

$settings.env.ANTHROPIC_DEFAULT_HAIKU_MODEL = "deepseek-v4-flash"
$settings.env.ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME = "DeepSeek Flash"
$settings.env.ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION = "DeepSeek fast model for short questions, checks, and light edits."

$settings.effortLevel = "max"

if ($settings.availableModels) {
    $models = @($settings.availableModels)
    foreach ($model in @("deepseek-v4-pro[1m]", "deepseek-v4-pro", "deepseek-v4-flash")) {
        if ($models -notcontains $model) {
            $models += $model
        }
    }
    $settings.availableModels = $models
}

$json = $settings | ConvertTo-Json -Depth 100
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ClaudeSettingsPath, $json, $utf8NoBom)

Write-Host "Claude Code is configured for DeepSeek models through DeepSeek Anthropic gateway."
Write-Host "Default: deepseek-v4-pro[1m]"
Write-Host "Switch per run: claude --model deepseek-v4-flash"
