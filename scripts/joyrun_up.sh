#!/bin/bash
# 整体链路一键启动: WebUI + RS 实例 + 设备预置/连接 + 参数 + 守卫 + 注入
# 用法: joyrun_up.sh [别名...] [--no-start] [--no-guard]
#   无参数 = 处理当前所有在线的已登记设备 (离线的跳过)
#   别名   = 只处理指定设备 (vivo / huawei / ...)
#   --no-start  = 预置连接好但不开始注入 (留给 RS 页手动点)
#   --no-guard  = 不起人脸守卫
# 红线: RS 实例 state=playing 时跳过该设备 (不动在跑的实例)
set -uo pipefail
BASE="$(cd "$(dirname "$0")/.." && pwd)"
DEVJSON="$BASE/devices.json"
ADB="${ADB:-$HOME/.local/bin/adb}"
WEBUI_PORT=8800
PKG=com.joyrunworld.app
NO_START=0; NO_GUARD=0
ALIASES=()
for a in "$@"; do
  case "$a" in
    --no-start) NO_START=1 ;;
    --no-guard) NO_GUARD=1 ;;
    *) ALIASES+=("$a") ;;
  esac
done

say() { echo "[$(date +%H:%M:%S)] $*"; }

# ---- 0. adb server 健康自愈 (陈旧句柄会导致 no permissions) ----
if "$ADB" devices -l 2>/dev/null | grep -q "no permissions"; then
  say "检测到 USB no permissions, 重启 adb server 自愈..."
  "$ADB" kill-server; sleep 1; "$ADB" start-server >/dev/null 2>&1; sleep 1
fi

# ---- 1. WebUI 控制台 ----
if curl -s -m 3 -o /dev/null "http://127.0.0.1:$WEBUI_PORT/api/overview"; then
  say "WebUI :$WEBUI_PORT 已在运行"
else
  say "启动 WebUI :$WEBUI_PORT..."
  (cd "$BASE" && nohup python3 -m webui.main --port $WEBUI_PORT \
     >> "$BASE/webui/logs/webui.log" 2>&1 &)
  sleep 2
  curl -s -m 3 -o /dev/null "http://127.0.0.1:$WEBUI_PORT/api/overview" \
    && say "WebUI ok (http://127.0.0.1:$WEBUI_PORT)" || say "!! WebUI 启动失败, 看 webui/logs/webui.log"
fi

# ---- 2. 目标设备集合 ----
mapfile -t ALL < <(python3 -c "
import json
d=json.load(open('$DEVJSON'))
for k in d:
    if not k.startswith('_'):
        print(k)")
TARGETS=()
if [ ${#ALIASES[@]} -gt 0 ]; then
  for a in "${ALIASES[@]}"; do
    grep -qw "$a" <<< "${ALL[*]}" && TARGETS+=("$a") || say "!! devices.json 没有[$a], 跳过"
  done
else
  TARGETS=("${ALL[@]}")
fi

# ---- 3. RS systemd 实例保活 ----
for a in "${TARGETS[@]}"; do
  if ! systemctl --user is-active --quiet "route-studio@$a"; then
    say "启动 route-studio@$a..."
    systemctl --user enable --now "route-studio@$a" >/dev/null 2>&1
    sleep 1
  fi
done

# ---- 4. 每台在线设备: 预置 -> 连接 -> 参数 -> 守卫 -> 注入 ----
ONLINE=()
for a in "${TARGETS[@]}"; do
  SER=$(python3 -c "import json;print(json.load(open('$DEVJSON'))['$a']['serial'])")
  WIFI=$(python3 -c "import json;print(json.load(open('$DEVJSON'))['$a'].get('wifi') or '')")
  PORT=$(python3 -c "import json;print(json.load(open('$DEVJSON'))['$a']['port'])")
  SPD=$(python3  -c "import json;print(json.load(open('$DEVJSON'))['$a'].get('speed_kmh',13.33))")

  # 通道: USB 优先 -> WiFi -> connect 唤醒
  TARGET=""
  if "$ADB" -s "$SER" get-state >/dev/null 2>&1; then TARGET="$SER"
  elif [ -n "$WIFI" ] && "$ADB" -s "$WIFI" get-state >/dev/null 2>&1; then TARGET="$WIFI"
  elif [ -n "$WIFI" ]; then
    "$ADB" connect "$WIFI" >/dev/null 2>&1 && sleep 1
    "$ADB" -s "$WIFI" get-state >/dev/null 2>&1 && TARGET="$WIFI"
  fi
  if [ -z "$TARGET" ]; then say "$a: 离线, 跳过 (USB/WiFi 均不通)"; continue; fi
  ONLINE+=("$a")

  ST=$(curl -s -m 4 "http://127.0.0.1:$PORT/api/status" | python3 -c "
import json,sys
try: d=json.load(sys.stdin); print(d.get('state'), d.get('udid') or '-')
except Exception: print('unreachable -')")
  STATE=${ST%% *}; STUD=${ST#* }
  if [ "$STATE" = "playing" ]; then say "$a: 正在跑步, 跳过 (不动在跑的实例)"; continue; fi

  # 预置 (虚拟定位条件; 换机/重插后必须)
  PREP=$(curl -s -m 60 -X POST -H 'Content-Type: application/json' \
    -d "{\"serial\":\"$TARGET\"}" "http://127.0.0.1:$WEBUI_PORT/api/prepare")
  echo "$PREP" | grep -q '"ok": true' && say "$a: 预置 ok ($TARGET)" \
    || say "$a: !! 预置失败: $(echo "$PREP" | head -c 150)"

  # 连接 (同串号已连接则跳过; 失败且绑着别的死设备 -> rs-restart 自愈后重试一次)
  if [ "$STATE" != "unreachable" ] && [ "$STUD" = "$TARGET" ] && [ "$STATE" != "error" ]; then
    say "$a: 实例已连接 $TARGET (state=$STATE), 跳过连接"
  else
    [ "$TARGET" = "$SER" ] && BODY="{\"platform\":\"android\",\"udid\":\"$SER\"}" \
      || BODY="{\"platform\":\"android\",\"address\":\"$WIFI\"}"
    R=$(curl -s -m 40 -X POST -H 'Content-Type: application/json' -d "$BODY" "http://127.0.0.1:$PORT/api/connect")
    if echo "$R" | grep -q '"error"'; then
      if [ "$STATE" != "unreachable" ] && [ "$STUD" != "$TARGET" ] && [ -n "$STUD" ] && [ "$STUD" != "-" ]; then
        say "$a: 实例绑着旧设备 $STUD, 重启实例自愈..."
        curl -s -m 30 -X POST -H 'Content-Type: application/json' \
          -d "{\"alias\":\"$a\"}" "http://127.0.0.1:$WEBUI_PORT/api/rs-restart" >/dev/null
        sleep 2
        R=$(curl -s -m 40 -X POST -H 'Content-Type: application/json' -d "$BODY" "http://127.0.0.1:$PORT/api/connect")
      fi
    fi
    echo "$R" | grep -q '"error"' \
      && say "$a: !! 连接失败: $(echo "$R" | head -c 150)" \
      || say "$a: 连接 ok mode=$(echo "$R" | python3 -c "import json,sys;print((json.load(sys.stdin).get('diagnostics') or {}).get('mode'))")"
  fi

  # 参数整包
  curl -s -m 10 -X POST -H 'Content-Type: application/json' \
    -d "{\"speed_kmh\":$SPD,\"interval\":1.0,\"speed_variation_pct\":3.0,\"lateral_variation_m\":1.5,\"variation_period\":10.0,\"loop\":true,\"random_seed\":14}" \
    "http://127.0.0.1:$PORT/api/settings" >/dev/null \
    && say "$a: 参数 $SPD km/h ok" || say "$a: !! 参数失败"

  # 守卫
  if [ "$NO_GUARD" = 0 ]; then
    G=$(curl -s -m 15 -X POST -H 'Content-Type: application/json' -d '{}' \
      "http://127.0.0.1:$WEBUI_PORT/api/devices/$a/guard-start")
    echo "$G" | grep -qE '"ok": true|already running' \
      && say "$a: 人脸守卫 ok" || say "$a: !! 守卫失败: $(echo "$G" | head -c 120)"
  fi

  # 开始注入
  if [ "$NO_START" = 0 ]; then
    curl -s -m 10 -X POST -H 'Content-Type: application/json' -d '{}' \
      "http://127.0.0.1:$PORT/api/start" >/dev/null
    sleep 2
  fi
done

# ---- 5. 汇总 ----
say "──── 汇总 ────"
for a in "${TARGETS[@]}"; do
  PORT=$(python3 -c "import json;print(json.load(open('$DEVJSON'))['$a']['port'])")
  SUM=$(curl -s -m 4 "http://127.0.0.1:$PORT/api/status" | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  cur=d.get('current') or {}
  print(f\"{d.get('state')} | mode={(d.get('diagnostics') or {}).get('mode')} | {((d.get('route') or {}).get('name') or '-')}\")
except Exception: print('unreachable')")
  GUARD=$(curl -s -m 4 "http://127.0.0.1:$WEBUI_PORT/api/overview" | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  g=next((x['guard'] for x in d['devices'] if x['alias']=='$a'), {})
  print('守卫' + ('运行中' if g.get('running') else '停止'))
except Exception: print('?')")
  echo "  $a (:${PORT}) -> ${SUM} | ${GUARD}"
done
say "完成。手机 app: 开始跑步 -> 至少跑1000米 -> 弹窗确认; 窗口 06:00-23:00"
