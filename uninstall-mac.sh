#!/bin/bash
PLIST="$HOME/Library/LaunchAgents/com.zhugeliang.memorial.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "상소를 거두었사옵니다. 자동 실행이 해제되었습니다."
