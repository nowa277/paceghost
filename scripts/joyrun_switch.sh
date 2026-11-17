#!/bin/bash
# 一条命令把校园跑切到指定设备 (免重新调试; USB 在线用 USB, 否则自动落 WiFi)
# 用法: joyrun_switch.sh <别名> [--start]
#   别名 = devices.json 里的 key (vivo / huawei / ...)
#   --start  连接后直接开跑
# 做的事: 停所有实例播放 -> 设备预置(appop/计步/清残留) -> 推人脸 -> 对应端口实例 connect -> settings 整包 -> (可选 start)
set -e
BASE="$(cd "$(dirname "$0")/.." && pwd)"
DEVJSON="$BASE/devices.json"
FACE_SET="$BASE/scripts/face_set.sh"
PKG=com.joyrunworld.app

ALIAS="${1:-}"
[ -z "$ALIAS" ] && { echo "用法: joyrun_switch.sh <vivo|huawei|...> [--start]"; exit 1; }
shift || true
START=0; for a in "$@"; do [ "$a" = "--start" ] && START=1; done

if ! grep -q "\"$ALIAS\"" "$DEVJSON"; then echo "devices.json 里没有 [$ALIAS]"; exit 1; fi
SER=$(python3  -c "import json;print(json.load(open('$DEVJSON'))['$ALIAS']['serial'])")
WIFI=$(python3 -c "import json;print(json.load(open('$DEVJSON'))['$ALIAS'].get('wifi') or '')")
PORT=$(python3 -c "import json;print(json.load(open('$DEVJSON'))['$ALIAS']['port'])")
CAD=$(python3  -c "import json;d=json.load(open('$DEVJSON'))['$ALIAS'];print(d.get('cadence',131))")
SPD=$(python3  -c "import json;d=json.load(open('$DEVJSON'))['$ALIAS'];print(d.get('speed_kmh',13.33))")
FACE=$(python3 -c "import json;d=json.load(open('$DEVJSON'))['$ALIAS'];print(d.get('face',''))")

# 传输通道解析: USB 优先, 不在线自动落 WiFi
if adb -s "$SER" get-state >/dev/null 2>&1; then
  TARGET="$SER"; VIA="USB"
elif [ -n "$WIFI" ] && adb -s "$WIFI" get-state >/dev/null 2>&1; then
  TARGET="$WIFI"; VIA="WiFi($WIFI)"
else
  echo "!! $ALIAS 不在线: USB($SER) 和 WiFi(${WIFI:-未配置}) 都不通"; exit 1
fi
echo "== 切换到 $ALIAS (通道=$VIA 端口=$PORT) =="

# 1) 所有实例先停播, 防止旧设备还在跑
ALLPORTS=$(python3 -c "import json;print(' '.join(str(v['port']) for v in json.load(open('$DEVJSON')).values() if isinstance(v,dict) and 'port' in v))")
for p in $ALLPORTS; do
  curl -s -m 5 -XPOST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$p/api/pause" >/dev/null || true
  curl -s -m 8 -XPOST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$p/api/stop"  >/dev/null || true
done

# 2) 设备预置: mock appop / 计步参数 / 清上一轮注入残留
adb -s "$TARGET" shell "appops set $PKG android:mock_location allow" >/dev/null
# vivo 类 ROM 在 WiFi adb 重连后定位总开关会被重置, 无条件补开 (幂等); 华为 cmd location 被裁剪会报非零, 吞错防止 set -e 中断
adb -s "$TARGET" shell "cmd location set-location-enabled true" >/dev/null 2>&1 || true
adb -s "$TARGET" shell "settings put global jrstep_cadence $CAD" >/dev/null
adb -s "$TARGET" shell "settings put global jrstep_on 1" >/dev/null
adb -s "$TARGET" shell "settings put global jrgps_feed 0" >/dev/null 2>&1 || true
adb -s "$TARGET" shell "settings delete global jrpos" >/dev/null 2>&1 || true
echo "[1/4] 设备预置 ok (cadence=$CAD)"

# 3) 人脸图推一遍 (幂等, 两秒)
if [ -n "$FACE" ] && [ -f "$FACE" ]; then
  "$FACE_SET" "$FACE" "$TARGET" >/dev/null 2>&1 && echo "[2/4] 人脸图已推送" || echo "[2/4] 人脸推送失败 (不影响连接, 手动 face_set.sh 补)"
else
  echo "[2/4] 未配置人脸图, 跳过"
fi

# 4) 对应端口的实例 connect (USB 走 udid, WiFi 走 address)
if [ "$TARGET" = "$SER" ]; then
  BODY="{\"platform\":\"android\",\"udid\":\"$SER\"}"
else
  BODY="{\"platform\":\"android\",\"address\":\"$WIFI\"}"
fi
echo "[3/4] Route Studio 连接 (端口 $PORT, $VIA)..."
curl -s -m 30 -XPOST -H 'Content-Type: application/json' -d "$BODY" "http://127.0.0.1:$PORT/api/connect" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print('      connect:',d.get('error') or 'ok, mode='+str((d.get('diagnostics') or {}).get('mode')))" || true

# 5) settings 整包 (该接口是整对象替换, 必须发全 7 字段)
curl -s -m 10 -XPOST -H 'Content-Type: application/json' \
  -d "{\"speed_kmh\":$SPD,\"interval\":1.0,\"speed_variation_pct\":3.0,\"lateral_variation_m\":1.5,\"variation_period\":10.0,\"loop\":true,\"random_seed\":14}" \
  "http://127.0.0.1:$PORT/api/settings" >/dev/null

# 6) 可选开跑
if [ "$START" = 1 ]; then
  curl -s -m 10 -XPOST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$PORT/api/start" >/dev/null
fi

curl -s -m 5 "http://127.0.0.1:$PORT/api/status" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print('[4/4] state=%s 路线=%s 里程=%.0fm%s'%(d['state'],(d.get('route') or {}).get('name') or '-',d.get('total_m') or 0,' 已开跑' if d['state']=='playing' else ''))"
echo "完成。UI: http://127.0.0.1:$PORT"
