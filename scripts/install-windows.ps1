# 제갈량 상소문 - Windows 설치 스크립트
# 1) 매일 오전 7시에 창을 띄우는 작업 스케줄러 등록
# 2) 로그인(컴퓨터 켤 때)마다 띄우도록 시작프로그램 바로가기 생성
# 3) 바탕화면 바로가기 생성
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$html = Join-Path $root 'index.html'
if (-not (Test-Path $html)) { throw "index.html 을 찾을 수 없습니다: $html" }
$url = ([System.Uri]$html).AbsoluteUri

$candidates = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$browser = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($browser) {
    # --app: 주소창 없는 독립 창으로 띄움
    $exe = $browser
    $arguments = "--app=`"$url`" --window-size=1080,900"
} else {
    $exe = "$env:WINDIR\explorer.exe"
    $arguments = "`"$html`""
}

# 1) 매일 오전 7시
$taskName = 'ZhugeLiang-Memorial'
$action   = New-ScheduledTaskAction -Execute $exe -Argument $arguments
$trigger  = New-ScheduledTaskTrigger -Daily -At '07:00'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description '제갈량 상소문 - 매일 오전 7시' -Force | Out-Null

# 2) 로그인할 때마다 (시작프로그램) + 3) 바탕화면
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('Desktop'))) {
    $lnk = $shell.CreateShortcut((Join-Path $dir '제갈량 상소문.lnk'))
    $lnk.TargetPath = $exe
    $lnk.Arguments = $arguments
    $lnk.WorkingDirectory = $root
    $lnk.Description = '제갈량 상소문'
    $lnk.Save()
}

Write-Host ''
Write-Host '신 량, 명을 받들었사옵니다.' -ForegroundColor Yellow
Write-Host " - 매일 오전 7시 : 작업 스케줄러 '$taskName'"
Write-Host ' - 컴퓨터를 켤 때 : 시작프로그램에 바로가기 등록'
Write-Host ' - 바탕화면 : "제갈량 상소문" 바로가기'
Write-Host ''
Write-Host '지금 한 번 띄워 드리옵니다...'
Start-Process -FilePath $exe -ArgumentList $arguments
