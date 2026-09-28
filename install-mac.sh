#!/bin/bash
# 제갈량 상소문 - macOS 설치: 로그인할 때 + 매일 오전 7시에 창을 띄운다.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$DIR/scripts/open-mac.sh"
PLIST="$HOME/Library/LaunchAgents/com.zhugeliang.memorial.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.zhugeliang.memorial</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$DIR/scripts/open-mac.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>7</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
</dict>
</plist>
PLIST
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "신 량, 명을 받들었사옵니다. 로그인할 때와 매일 오전 7시에 상소를 올리겠사옵니다."
