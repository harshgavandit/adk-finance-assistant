param(
    [ValidateSet('web', 'cli', 'check', 'live', 'test')]
    [string]$Mode = 'web',
    [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$pythonPath = Join-Path (Split-Path -Parent $projectDir) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv in the parent folder and install requirements-dev.txt first. See README.md.'
}
$env:PYTHONUTF8 = '1'
$env:LITELLM_LOCAL_MODEL_COST_MAP = 'True'
$env:LITELLM_LOG = 'ERROR'
$taskTempDir = Join-Path (Split-Path -Parent $projectDir) '.tmp'
New-Item -ItemType Directory -Path $taskTempDir -Force | Out-Null
$env:TEMP = $taskTempDir
$env:TMP = $taskTempDir
Push-Location -LiteralPath $projectDir
try {
    switch ($Mode) {
        'web' { & $pythonPath -m google.adk.cli web --host 127.0.0.1 --port $Port . }
        'cli' { & $pythonPath -m google.adk.cli run finance_assistant_agent }
        'check' { & $pythonPath verify.py }
        'live' { & $pythonPath verify.py --live }
        'test' {
            New-Item -ItemType Directory -Path '.runtime' -Force | Out-Null
            & $pythonPath -m pytest -q --basetemp=.runtime/pytest
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE." }
}
finally { Pop-Location }
