$ErrorActionPreference = "Stop"

$Project = Split-Path -Parent $MyInvocation.MyCommand.Path
$Profile = Join-Path $Project ".mymaps_browser_profile"
New-Item -ItemType Directory -Path $Profile -Force | Out-Null

$ChromeCandidates = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
) | Where-Object { $_ -and (Test-Path $_) }

$Chrome = $ChromeCandidates | Select-Object -First 1
if (-not $Chrome) {
    throw "Google Chrome 실행 파일을 찾지 못했습니다. Chrome 설치 상태를 확인하세요."
}

Write-Host "전용 My Maps 로그인용 Chrome을 엽니다." -ForegroundColor Cyan
Write-Host "프로필 경로: $Profile"
Write-Host "1) 이 Chrome 창에서 Google 계정에 직접 로그인하세요."
Write-Host "2) https://www.google.com/mymaps 가 로그인된 상태로 열리는지 확인하세요."
Write-Host "3) 이 전용 Chrome 창을 완전히 닫으세요. 프로필을 사용하는 창이 열려 있으면 자동화가 시작되지 않습니다."
Write-Host "4) 그 다음 .venv\Scripts\python.exe publish_mymaps.py 를 실행하세요."

$ArgumentLine = "--user-data-dir=`"$Profile`" https://accounts.google.com/"
Start-Process -FilePath $Chrome -ArgumentList $ArgumentLine
