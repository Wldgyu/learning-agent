$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$systemPython = Get-Command python -ErrorAction SilentlyContinue
$useBundled = $false
if (Test-Path -LiteralPath $projectPython) {
    $pythonExe = $projectPython
} elseif ($systemPython) {
    $pythonExe = $systemPython.Source
} elseif ((Test-Path -LiteralPath $bundledPython) -and
        (Test-Path -LiteralPath (Join-Path $projectRoot '.runtime'))) {
    $pythonExe = $bundledPython
    $useBundled = $true
} else {
    $pythonExe = $null
}
if (-not $pythonExe -or -not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Python을 찾지 못했습니다. Python 3.11 이상을 설치하고 README의 실행 단계를 진행하세요.'
}
if ($useBundled -and (Test-Path -LiteralPath (Join-Path $projectRoot '.runtime'))) {
    $env:PYTHONPATH = (Join-Path $projectRoot '.runtime')
}
& $pythonExe -c "import app.main, uvicorn; uvicorn.run(app.main.app, host='127.0.0.1', port=8000)"
