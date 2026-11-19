#!/bin/bash
# 整体链路一键停止: 守卫 + 注入 + 断连 (对称 joyrun_up.sh)
# 用法: joyrun_down.sh [别名...]   无参数 = 停所有已登记设备
# 红线: state=playing 时跳过 (想停正在跑的, 用控制台/RS 页显式确认)
set -uo pipefail
BASE="$(cd "$(dirname "$0")/.." && pwd)"
DEVJSON="$BASE/devices.json"
ADB="${ADB:-$HOME/.local/bin/adb}"
WEBUI_PORT=8800
say() { echo "[$(date +%H:%M:%S)] $*"; }

mapfile -t ALL < <(python3 -c "
import json
d=json.load(open('$DEVJSON'))
for k in d:
    if not k.startswith('_'):
        print(k)")
TARGETS=()
if [ $# -gt 0 ]; then
  for a in "$@"; do grep -qw "$a" <<< "${ALL[*]}" && TARGETS+=("$a") || say "!! 没有[$a]"; done
else
  TARGETS=("${ALL[@]}")
fi

for a in "${TARGETS[@]}"; do
  PORT=$(python3 -c "import json;print(json.load(open('$DEVJSON'))['$a']['port'])")
  STATE=$(curl -s -m 4 "http://127.0.0.1:$PORT/api/status" | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('state'))
except Exception: print('unreachable')")
  curl -s -m 10 -X POST -H 'Content-Type: application/json' -d '{}' \
    "http://127.0.0.1:$WEBUI_PORT/api/devices/$a/guard-stop" >/dev/null
  if [ "$STATE" = "playing" ]; then
    say "$a: 正在跑步, 只停了守卫 (注入保留; 要停请在 RS 页/控制台确认停止)"; continue
  fi
  curl -s -m 8  -X POST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$PORT/api/pause"    >/dev/null
  curl -s -m 8  -X POST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$PORT/api/stop"     >/dev/null
  sleep 1
  curl -s -m 8  -X POST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$PORT/api/disconnect" >/dev/null
  say "$a: 已停止 (守卫+注入+断连, state=$STATE)"
done
