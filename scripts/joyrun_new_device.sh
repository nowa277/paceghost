#!/bin/bash
# 新设备接入 (USB 只插一次, 之后只走 WiFi)
# 用法: joyrun_new_device.sh <别名> [序列号]
#   设备需已 USB 连接并开了 USB 调试。序列号省略时自动找未登记的那台 USB 设备。
# 全自动做: 装补丁APK -> 权限/appop -> 推人脸 -> 开 tcpip 5555 + adb connect WiFi
#          -> 登记 devices.json -> 建实例 systemd -> 种子路线 -> connect
set -e
BASE="$(cd "$(dirname "$0")/.." && pwd)"
DEVJSON="$BASE/devices.json"
PKG=com.joyrunworld.app
DEFAULT_FACE="$BASE/work/face/face_src.png"

ALIAS="${1:?用法: joyrun_new_device.sh <别名> [序列号]}"
SER="${2:-}"

# ---------- 0) 别名占用检查 + 找序列号 ----------
python3 - "$ALIAS" "$DEVJSON" <<'EOF'
import json, sys
alias, path = sys.argv[1], sys.argv[2]
d = json.load(open(path))
if alias in d:
    print(f"!! 别名 [{alias}] 已存在, 换一个"); sys.exit(1)
EOF

if [ -z "$SER" ]; then
  REGISTERED=$(python3 -c "import json;print(' '.join(str(v.get('serial','')) for v in json.load(open('$DEVJSON')).values() if isinstance(v,dict)))")
  SER=$(adb devices | awk -v reg="$REGISTERED" '
    $2=="device" && $1 !~ /:/ {          # 只看 USB 设备 (序列号无冒号)
      if (index(reg, $1) == 0) print $1  # 且未登记过
    }' | head -1)
  [ -z "$SER" ] && { echo "!! 没找到未登记的 USB 设备 (adb devices 看一下)"; exit 1; }
  echo "自动选中未登记设备: $SER"
fi
adb -s "$SER" get-state >/dev/null 2>&1 || { echo "!! $SER 不在线"; exit 1; }
echo "== 新设备接入: $ALIAS ($SER) =="

# ---------- 1) 补丁 APK (已装跳过) ----------
if adb -s "$SER" shell "pm path $PKG" >/dev/null 2>&1; then
  echo "[1/6] $PKG 已安装, 跳过"
else
  APK=$(ls -t "$BASE"/lsp/out-v*/base-487-lspatched.apk 2>/dev/null | head -1)
  [ -z "$APK" ] && { echo "!! 没有现成补丁 APK, 先跑 lsp/build_module.sh"; exit 1; }
  echo "[1/6] 安装 $APK ..."
  adb -s "$SER" install -r "$APK" | tail -1
fi

# ---------- 2) 权限 + mock appop ----------
adb -s "$SER" shell "pm grant $PKG android.permission.CAMERA" 2>/dev/null || true
adb -s "$SER" shell "pm grant $PKG android.permission.ACCESS_FINE_LOCATION" 2>/dev/null || true
adb -s "$SER" shell "pm grant $PKG android.permission.ACCESS_COARSE_LOCATION" 2>/dev/null || true
adb -s "$SER" shell "pm grant $PKG android.permission.ACTIVITY_RECOGNITION" 2>/dev/null || true
adb -s "$SER" shell "appops set $PKG android:mock_location allow" >/dev/null
adb -s "$SER" shell "settings put global jrstep_cadence 131" >/dev/null
adb -s "$SER" shell "settings put global jrstep_on 1" >/dev/null
echo "[2/6] 权限/appop/计步参数 ok"

# ---------- 3) 人脸图 ----------
FACE=$(python3 -c "
import json
for v in json.load(open('$DEVJSON')).values():
    if isinstance(v, dict) and v.get('face'): print(v['face']); break
else: print('$DEFAULT_FACE')")
[ -f "$FACE" ] && "$BASE/scripts/face_set.sh" "$FACE" "$SER" >/dev/null 2>&1 && echo "[3/6] 人脸图已推" \
  || echo "[3/6] 人脸图缺失($FACE), 手动: face_set.sh <图> $SER"

# ---------- 4) 开 WiFi adb (核心: 一次 USB, 之后无线) ----------
adb -s "$SER" tcpip 5555 >/dev/null
sleep 1
IP=$(adb -s "$SER" shell "ip -f inet addr show wlan0" | grep -oP 'inet \K[\d.]+' | head -1)
[ -z "$IP" ] && { echo "!! 取不到 wlan0 IP, 保持在 USB 模式 (wifi 字段留空)"; WIFI=""; }
WIFI="${IP:+$IP:5555}"
if [ -n "$WIFI" ]; then
  adb connect "$WIFI" >/dev/null 2>&1 || true
  if adb -s "$WIFI" get-state >/dev/null 2>&1; then
    echo "[4/6] WiFi adb 就绪: $WIFI (现在可以拔 USB 了)"
  else
    echo "[4/6] adb connect $WIFI 未通过, 先按 USB 继续, 稍后 joyrun_wifi.sh --enable 重试"
    WIFI=""
  fi
fi

# ---------- 5) 登记 devices.json + 建实例 ----------
python3 - "$DEVJSON" "$ALIAS" "$SER" "$WIFI" <<'EOF'
import json, sys
path, alias, ser, wifi = sys.argv[1:5]
d = json.load(open(path))
ports = [v["port"] for v in d.values() if isinstance(v, dict) and "port" in v]
port = max(ports + [8764]) + 1
face = next((v.get("face") for v in d.values() if isinstance(v, dict) and v.get("face")), None)
d[alias] = {"serial": ser, "wifi": wifi or None, "port": port, "mode": "auto",
            "cadence": 131, "speed_kmh": 13.33, "face": face}
json.dump(d, open(path, "w"), ensure_ascii=False, indent=2)
print(f"[5/6] devices.json 已登记: {alias} port={port} wifi={wifi or '-'}")
EOF

SEED=$(ls -t ~/.ios-location-controller/session-*.json 2>/dev/null | head -1)
[ -n "$SEED" ] && cp "$SEED" ~/.ios-location-controller/"session-$ALIAS.json" && echo "      路线种子: $(basename "$SEED") -> session-$ALIAS.json"

mkdir -p ~/.config/systemd/user
cp "$BASE/systemd/route-studio@.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now "route-studio@$ALIAS.service" 2>&1 | tail -1
sleep 2
echo "[5/6] 实例 route-studio@$ALIAS 已启动 (端口见 devices.json)"

# ---------- 6) 连接 ----------
"$BASE/scripts/joyrun_switch.sh" "$ALIAS" || echo "(连接未成功也无妨: 手机上打开补丁版登录后重跑 joyrun_switch.sh)"
echo
echo "== 完成。USB 现在可以拔了 =="
echo "  之后日常:  PC 重启后跑 scripts/joyrun_wifi.sh 重连 WiFi; 手机重启后插一下 USB 再跑它即可自愈"
echo "  切换设备:  scripts/joyrun_switch.sh $ALIAS [--start]"
echo "  提醒:      同账号在新设备登录可能触发设备上限 (服务端限制, 与本脚本无关)"
