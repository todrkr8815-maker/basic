#!/bin/bash
# 제갈량 상소문을 주소창 없는 독립 창으로 띄운다 (크롬/엣지/브레이브가 없으면 기본 브라우저).
DIR="$(cd "$(dirname "$0")/.." && pwd)"
URL="file://${DIR// /%20}/index.html"
for app in "Google Chrome" "Microsoft Edge" "Brave Browser"; do
  if open -Ra "$app" 2>/dev/null; then
    open -na "$app" --args --app="$URL" --window-size=1080,900
    exit 0
  fi
done
open "$DIR/index.html"
