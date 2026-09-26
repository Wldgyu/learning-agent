param([switch]$Check)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$systemPython = Get-Command python -ErrorAction SilentlyContinue
$runtimePath = Join-Path $projectRoot '.runtime'
$originalPythonPath = $env:PYTHONPATH
$candidates = @(
    @{ Path = $projectPython; Runtime = $false }
    @{ Path = if ($systemPython) { $systemPython.Source } else { $null }; Runtime = $false }
    @{ Path = $bundledPython; Runtime = $true }
)
$pythonExe = $null
try {
    foreach ($candidate in $candidates) {
        if (-not $candidate.Path -or -not (Test-Path -LiteralPath $candidate.Path)) { continue }
        $env:PYTHONPATH = $null
        if ($candidate.Runtime -and (Test-Path -LiteralPath $runtimePath)) {
            $env:PYTHONPATH = $runtimePath
        }
        & $candidate.Path -c "import sys; assert sys.version_info >= (3, 11); import fastapi, uvicorn, pydantic, starlette" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonExe = $candidate.Path
            break
        }
    }
    if (-not $pythonExe) {
        throw '실행에 필요한 패키지가 설치된 Python을 찾지 못했습니다. py -3 -m venv .venv 실행 후 .\.venv\Scripts\python.exe -m pip install -r requirements.txt 를 실행하세요.'
    }
    Write-Host "Python: $pythonExe"
    if ($Check) {
        Write-Host '필수 패키지 확인 완료'
    } else {
        & $pythonExe -c "import app.main, uvicorn; uvicorn.run(app.main.app, host='127.0.0.1', port=8000)"
    }
} finally {
    $env:PYTHONPATH = $originalPythonPath
}
