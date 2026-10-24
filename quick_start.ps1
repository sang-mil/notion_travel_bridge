$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$EnvPath = Join-Path $ProjectRoot '.env'
$EnvExamplePath = Join-Path $ProjectRoot '.env.example'
$SetupMarker = Join-Path $ProjectRoot '.quickstart_setup_version'
$LoginMarker = Join-Path $ProjectRoot '.mymaps_browser_login_ready'
$SetupVersion = '2026-10-24-quickstart-1'

function Show-Header {
    Clear-Host
    Write-Host '============================================================' -ForegroundColor DarkCyan
    Write-Host '             Notion Travel Bridge - Quick Start' -ForegroundColor Cyan
    Write-Host '        Notion -> Gemini -> Google My Maps -> Notion' -ForegroundColor Gray
    Write-Host '============================================================' -ForegroundColor DarkCyan
    Write-Host ('프로젝트: ' + $ProjectRoot) -ForegroundColor DarkGray
    Write-Host ''
}
function Wait-ForEnter([string]$Message = '계속하려면 Enter를 누르세요') { [void](Read-Host $Message) }
function Find-Chrome {
    $Candidates = @()
    if ($env:ProgramFiles) { $Candidates += (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe') }
    if (${env:ProgramFiles(x86)}) { $Candidates += (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe') }
    if ($env:LOCALAPPDATA) { $Candidates += (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe') }
    return ($Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
}
function Find-PythonBootstrap {
    # Use the official Python launcher when available, otherwise use python.exe from PATH.
    # Avoid `python -c` here: quote/argument handling can differ across Windows PowerShell setups.
    $Py = Get-Command 'py' -CommandType Application -ErrorAction SilentlyContinue
    if ($Py) {
        $script:BootstrapExe = $Py.Source
        $script:UsePyLauncher = $true
    }
    else {
        $Python = Get-Command 'python' -CommandType Application -ErrorAction SilentlyContinue
        if (-not $Python) {
            throw 'Python 3.10 이상을 찾지 못했습니다. https://www.python.org/downloads/windows/ 에서 설치한 뒤 다시 실행하세요.'
        }
        $script:BootstrapExe = $Python.Source
        $script:UsePyLauncher = $false
    }

    if ($script:UsePyLauncher) {
        $VersionOutput = & $script:BootstrapExe -3 --version 2>&1
    }
    else {
        $VersionOutput = & $script:BootstrapExe --version 2>&1
    }
    $VersionExitCode = $LASTEXITCODE
    $VersionText = (@($VersionOutput) -join ' ').Trim()
    if ($VersionExitCode -ne 0 -or $VersionText -notmatch 'Python\s+(\d+)\.(\d+)') {
        throw "Python을 실행하거나 버전을 확인할 수 없습니다. 출력: $VersionText"
    }
    $Major = [int]$Matches[1]
    $Minor = [int]$Matches[2]
    if ($Major -lt 3 -or ($Major -eq 3 -and $Minor -lt 10)) {
        throw "Python $VersionText 는 너무 오래된 버전입니다. Python 3.10 이상이 필요합니다."
    }
    Write-Host "Python 확인: $VersionText" -ForegroundColor Green
}
function Ensure-Environment {
    try { Find-PythonBootstrap } catch { Write-Host $_.Exception.Message -ForegroundColor Red; return $false }
    if (-not (Test-Path $VenvPython)) {
        Write-Host '프로젝트 전용 Python 가상환경을 생성합니다...' -ForegroundColor Yellow
        if ($script:UsePyLauncher) { & $script:BootstrapExe -3 -m venv (Join-Path $ProjectRoot '.venv') }
        else { & $script:BootstrapExe -m venv (Join-Path $ProjectRoot '.venv') }
        if ($LASTEXITCODE -ne 0) { Write-Host '가상환경 생성에 실패했습니다.' -ForegroundColor Red; return $false }
    }
    $NeedsInstall = $true
    if (Test-Path $SetupMarker) {
        $MarkerText = (Get-Content -LiteralPath $SetupMarker -Raw -ErrorAction SilentlyContinue).Trim()
        if ($MarkerText -eq $SetupVersion) {
            & $VenvPython -c 'import requests, dotenv, google.genai; import playwright.sync_api' 2>$null
            if ($LASTEXITCODE -eq 0) { $NeedsInstall = $false }
        }
    }
    if ($NeedsInstall) {
        Write-Host '필요한 Python 패키지를 설치합니다. 인터넷 연결이 필요할 수 있습니다...' -ForegroundColor Yellow
        & $VenvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { Write-Host 'pip 업데이트 실패. 인터넷 연결과 Python 설치를 확인하세요.' -ForegroundColor Red; return $false }
        & $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { Write-Host '패키지 설치 실패. 위 오류를 확인하세요.' -ForegroundColor Red; return $false }
        & $VenvPython -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { Write-Host 'Playwright 브라우저 설치에 실패했습니다.' -ForegroundColor Red; return $false }
        Set-Content -LiteralPath $SetupMarker -Value $SetupVersion -Encoding UTF8
    }
    if (-not (Find-Chrome)) {
        Write-Host 'Google Chrome이 설치되어 있지 않습니다. https://www.google.com/chrome/ 에서 설치하세요.' -ForegroundColor Red
        return $false
    }
    Write-Host 'Python 환경과 Google Chrome 확인 완료.' -ForegroundColor Green
    return $true
}
function Read-EnvMap {
    $Map = @{}
    if (-not (Test-Path $EnvPath)) { return $Map }
    foreach ($Line in Get-Content -LiteralPath $EnvPath -ErrorAction SilentlyContinue) {
        if ($Line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $Name = $Matches[1]; $Value = $Matches[2].Trim()
            if (($Value.StartsWith('"') -and $Value.EndsWith('"')) -or ($Value.StartsWith("'") -and $Value.EndsWith("'"))) { $Value = $Value.Substring(1, [Math]::Max(0, $Value.Length - 2)) }
            $Map[$Name] = $Value
        }
    }
    return $Map
}
function Test-EnvConfigured {
    if (-not (Test-Path $EnvPath)) { return $false }
    $Values = Read-EnvMap; $Required = @('NOTION_TOKEN','NOTION_PAGE_ID','GEMINI_API_KEY'); $Missing = @()
    foreach ($Name in $Required) {
        $Value = [string]$Values[$Name]
        if ([string]::IsNullOrWhiteSpace($Value) -or $Value -match 'your_|placeholder|paste[_ -]?here|secret_or_ntn|your-page-id') { $Missing += $Name }
    }
    if ($Missing.Count -gt 0) { Write-Host ('설정 필요: ' + ($Missing -join ', ')) -ForegroundColor Yellow; return $false }
    return $true
}
function Open-Config {
    if (-not (Test-Path $EnvPath)) { Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath }
    Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $EnvPath + '"')
    Wait-ForEnter '메모장에서 저장한 뒤 이 Quick Start 창으로 돌아와 Enter를 누르세요'
}
function Ensure-Config {
    if (-not (Test-Path $EnvPath)) { Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath; Write-Host '.env 설정 파일을 만들었습니다.' -ForegroundColor Yellow }
    if (-not (Test-EnvConfigured)) {
        Write-Host '메모장이 열립니다. NOTION_TOKEN, NOTION_PAGE_ID, GEMINI_API_KEY를 본인 값으로 입력하고 저장하세요.' -ForegroundColor Yellow
        Open-Config
    }
    if (-not (Test-EnvConfigured)) { Write-Host '.env 설정이 아직 완료되지 않았습니다.' -ForegroundColor Red; return $false }
    Write-Host '필수 .env 항목을 확인했습니다. 비밀값은 화면에 표시하지 않습니다.' -ForegroundColor Green
    return $true
}
function Start-GoogleLogin {
    $Chrome = Find-Chrome
    if (-not $Chrome) { Write-Host 'Google Chrome을 찾지 못했습니다.' -ForegroundColor Red; return }
    $ProfileDir = Join-Path $ProjectRoot '.mymaps_browser_profile'
    $null = New-Item -ItemType Directory -Path $ProfileDir -Force
    $ArgumentLine = '"--user-data-dir=' + $ProfileDir + '" --no-first-run --no-default-browser-check https://www.google.com/mymaps'
    Start-Process -FilePath $Chrome -ArgumentList $ArgumentLine
    Write-Host '전용 Chrome 창에서 Google 계정 로그인을 직접 완료하세요.' -ForegroundColor Yellow
    Write-Host '로그인 뒤 이 전용 Chrome 창을 완전히 닫으세요.' -ForegroundColor Yellow
    Wait-ForEnter 'Google 로그인을 완료하고 전용 Chrome 창을 닫은 뒤 Enter를 누르세요'
    Set-Content -LiteralPath $LoginMarker -Value (Get-Date -Format o) -Encoding UTF8
}
function Run-FullPipeline {
    if (-not (Ensure-Environment)) { Wait-ForEnter; return }
    if (-not (Ensure-Config)) { Wait-ForEnter; return }
    if (-not (Test-Path $LoginMarker)) {
        Write-Host '이 프로젝트의 Google 로그인 준비가 아직 확인되지 않았습니다. 로그인 창을 먼저 엽니다.' -ForegroundColor Yellow
        Start-GoogleLogin
    }
    Write-Host '실행 순서: Notion -> Gemini -> CSV -> Google My Maps -> Notion 결과 기록' -ForegroundColor Cyan
    Write-Host 'My Maps 화면 요소를 못 찾으면 일부 단계를 브라우저에서 직접 완료해야 할 수 있습니다.' -ForegroundColor Yellow
    $Confirm = Read-Host '전체 실행을 시작할까요? (Y/N)'
    if ($Confirm -notin @('Y','y','YES','yes')) { Write-Host '취소했습니다.'; return }
    & $VenvPython (Join-Path $ProjectRoot 'run_all.py')
    if ($LASTEXITCODE -eq 0) { Write-Host '전체 파이프라인이 정상 종료되었습니다.' -ForegroundColor Green }
    else { Write-Host "오류로 종료됨 (코드 $LASTEXITCODE). 위 메시지를 확인하세요." -ForegroundColor Red }
    Wait-ForEnter
}
function Run-WritebackOnly {
    if (-not (Ensure-Environment)) { Wait-ForEnter; return }
    if (-not (Ensure-Config)) { Wait-ForEnter; return }
    $Script = Join-Path $ProjectRoot 'sync_notion_results.py'
    & $VenvPython $Script '--dry-run'
    if ($LASTEXITCODE -ne 0) { Write-Host '사전 확인에 실패했습니다.' -ForegroundColor Red; Wait-ForEnter; return }
    $Confirm = Read-Host '실제 Notion 페이지에 지도 링크/템플릿을 기록할까요? (Y/N)'
    if ($Confirm -notin @('Y','y','YES','yes')) { Write-Host '취소했습니다.'; Wait-ForEnter; return }
    & $VenvPython $Script
    if ($LASTEXITCODE -eq 0) { Write-Host 'Notion 기록이 완료되었습니다.' -ForegroundColor Green } else { Write-Host '동기화 실패. 위 오류를 확인하세요.' -ForegroundColor Red }
    Wait-ForEnter
}
function Open-UserManual {
    # Search the standard docs folder and the project root. Never silently do nothing.
    $HtmlCandidates = @(
        (Join-Path $ProjectRoot 'docs\사용자_설명서.html'),
        (Join-Path $ProjectRoot '사용자_설명서.html')
    )
    foreach ($Html in $HtmlCandidates) {
        if (Test-Path -LiteralPath $Html -PathType Leaf) {
            try {
                $ResolvedHtml = (Resolve-Path -LiteralPath $Html).Path
                Write-Host ('사용자 설명서를 엽니다: ' + $ResolvedHtml) -ForegroundColor Green
                Start-Process -FilePath $ResolvedHtml -ErrorAction Stop
                return
            }
            catch {
                Write-Host ('브라우저 실행 실패: ' + $_.Exception.Message) -ForegroundColor Yellow
                try {
                    # Explorer launches the file through its Windows file association.
                    Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $ResolvedHtml + '"') -ErrorAction Stop
                    return
                }
                catch {
                    Write-Host ('HTML 열기 실패: ' + $_.Exception.Message) -ForegroundColor Yellow
                }
            }
        }
    }

    $TextCandidates = @(
        (Join-Path $ProjectRoot 'docs\사용자_설명서.md'),
        (Join-Path $ProjectRoot '사용자_설명서.md'),
        (Join-Path $ProjectRoot 'README.md')
    )
    foreach ($Markdown in $TextCandidates) {
        if (Test-Path -LiteralPath $Markdown -PathType Leaf) {
            try {
                Write-Host ('문서 파일을 메모장으로 엽니다: ' + $Markdown) -ForegroundColor Green
                Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $Markdown + '"') -ErrorAction Stop
                return
            }
            catch {
                Write-Host ('문서 열기 실패: ' + $_.Exception.Message) -ForegroundColor Red
            }
        }
    }

    Write-Host '사용자 설명서 파일을 찾지 못했습니다.' -ForegroundColor Red
    Write-Host ('확인 경로: ' + (Join-Path $ProjectRoot 'docs\사용자_설명서.html')) -ForegroundColor Yellow
    Write-Host '전체 ZIP에서 docs 폴더를 프로젝트 폴더로 복사하거나 README.md를 확인하세요.' -ForegroundColor Yellow
}

while ($true) {
    Show-Header
    Write-Host '  1. 최초 설정 / 설치 상태 점검'
    Write-Host '  2. Google My Maps 로그인 준비'
    Write-Host '  3. 전체 실행 (Notion -> Gemini -> My Maps -> Notion)' -ForegroundColor Green
    Write-Host '  4. 기존 지도 결과만 Notion에 기록'
    Write-Host '  5. .env 설정 열기'
    Write-Host '  6. 출력 폴더 열기'
    Write-Host '  7. 사용자 설명서 열기'
    Write-Host '  0. 종료'
    Write-Host ''
    $Choice = Read-Host '번호를 선택하세요'
    switch ($Choice) {
        '1' { if (Ensure-Environment) { [void](Ensure-Config) }; Wait-ForEnter }
        '2' { Start-GoogleLogin }
        '3' { Run-FullPipeline }
        '4' { Run-WritebackOnly }
        '5' { Open-Config }
        '6' { $Out = Join-Path $ProjectRoot 'output'; $null = New-Item -ItemType Directory -Path $Out -Force; Start-Process explorer.exe -ArgumentList ('"' + $Out + '"'); Wait-ForEnter }
        '7' { Open-UserManual; Wait-ForEnter }
        '0' { break }
        default { Write-Host '메뉴 번호를 선택하세요.' -ForegroundColor Yellow; Start-Sleep -Seconds 1 }
    }
    if ($Choice -eq '0') { break }
}
