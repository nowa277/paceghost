#!/bin/bash
# Route Studio 每设备实例启动器 (systemd 模板 route-studio@<别名>.service 调用)
#   别名 -> 端口/状态文件 从 "$BASE/devices.json" 读取
#   状态文件: ~/.ios-location-controller/session-<别名>.json
set -euo pipefail
ALIAS="${1:?usage: rs_instance.sh <alias>}"
BASE="$(cd "$(dirname "$0")/.." && pwd)"
DEVJSON="$BASE/devices.json"

export ADB_PATH=/home/sesley/.local/bin/adb
export IOS_LOCATION_STATE="$HOME/.ios-location-controller/session-$ALIAS.json"
PORT=$(python3 -c "import json,sys;print(json.load(open('$DEVJSON'))['$ALIAS']['port'])")

exec "$BASE/tools/mr-venv/bin/python" -m ios_location_controller map --port "$PORT"
