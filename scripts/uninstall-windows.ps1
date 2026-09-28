# 제갈량 상소문 - Windows 제거 스크립트
Unregister-ScheduledTask -TaskName 'ZhugeLiang-Memorial' -Confirm:$false -ErrorAction SilentlyContinue
foreach ($dir in @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('Desktop'))) {
    Remove-Item (Join-Path $dir '제갈량 상소문.lnk') -ErrorAction SilentlyContinue
}
Write-Host '상소를 거두었사옵니다. 자동 실행이 모두 해제되었습니다.' -ForegroundColor Yellow
