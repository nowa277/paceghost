#!/bin/bash
# WiFi adb 日常维护
# 用法: joyrun_wifi.sh                  重连所有已登记 wifi 设备 (PC/手机重启后跑一次)
#       joyrun_wifi.sh --enable <别名>  给已登记设备开通 WiFi adb (需该机 USB 插着)
set -e
BASE="$(cd "$(dirname "$0")/.." && pwd)"
DEVJSON="$BASE/devices.json"

if [ "${1:-}" = "--enable" ]; then
  ALIAS="${2:?用法: joyrun_wifi.sh --enable <别名>}"
  SER=$(python3 -c "import json;print(json.load(open('$DEVJSON'))['$ALIAS']['serial'])")
  adb -s "$SER" get-state >/dev/null 2>&1 || { echo "!! $ALIAS ($SER) 请先 USB 插上"; exit 1; }
  adb -s "$SER" tcpip 5555 >/dev/null; sleep 1
  IP=$(adb -s "$SER" shell "ip -f inet addr show wlan0" | grep -oP 'inet \K[\d.]+' | head -1)
  [ -z "$IP" ] && { echo "!! 取不到 wlan0 IP"; exit 1; }
  WIFI="$IP:5555"
  adb connect "$WIFI" >/dev/null 2>&1 || true
  adb -s "$WIFI" get-state >/dev/null 2>&1 || { echo "!! adb connect $WIFI 失败"; exit 1; }
  python3 - "$DEVJSON" "$ALIAS" "$WIFI" <<'EOF'
import json, sys
path, alias, wifi = sys.argv[1:4]
d = json.load(open(path)); d[alias]["wifi"] = wifi
json.dump(d, open(path, "w"), ensure_ascii=False, indent=2)
EOF
  echo "$ALIAS: WiFi adb 已开通 $WIFI (USB 可以拔了)"
  exit 0
fi

# ---------- 默认: 重连全部 ----------
python3 - "$DEVJSON" <<'EOF' > /tmp/jr_wifi_list.$$
import json, sys
d = json.load(open(sys.argv[1]))
for a, v in d.items():
    if isinstance(v, dict) and v.get("wifi"):
        print(f"{a}\t{v['serial']}\t{v['wifi']}")
EOF
while IFS=$'\t' read -r ALIAS SER WIFI; do
  if adb -s "$WIFI" get-state >/dev/null 2>&1; then
    echo "$ALIAS: $WIFI 已连着"
    continue
  fi
  if adb connect "$WIFI" >/dev/null 2>&1 && adb -s "$WIFI" get-state >/dev/null 2>&1; then
    echo "$ALIAS: 重连 $WIFI ok"
  elif adb -s "$SER" get-state >/dev/null 2>&1; then
    # 手机重启导致 tcpip 复位 -> USB 恰好插着就自愈
    adb -s "$SER" tcpip 5555 >/dev/null; sleep 1
    if adb connect "$WIFI" >/dev/null 2>&1 && adb -s "$WIFI" get-state >/dev/null 2>&1; then
      echo "$ALIAS: USB 自愈重连 $WIFI ok"
    else
      echo "$ALIAS: 重连失败 (手机重启过? IP 变了? 插 USB 后重跑, 或 --enable 重开)"
    fi
  else
    echo "$ALIAS: $WIFI 不通且 $SER 不在线 -> 插 USB 后重跑本脚本"
  fi
done < /tmp/jr_wifi_list.$$
rm -f /tmp/jr_wifi_list.$$
