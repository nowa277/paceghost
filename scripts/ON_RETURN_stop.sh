#!/usr/bin/env bash
# 抓包收尾: 停 mitm, 清手机代理, 导出 HAR
set -u
S=10CD9D0FR0001JD
Y=/home/sesley/Workspace/paceghost
cd "$Y/capture"

PID=$(cat .mitm_pid 2>/dev/null || true)
if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
  # SIGINT 让 mitmdump 正常写完 flow
  kill -INT "$PID"
  sleep 3
  kill -0 "$PID" 2>/dev/null && kill "$PID"
  echo "mitmdump stopped (pid $PID)"
fi

echo "清手机代理:"
adb -s "$S" shell settings put global http_proxy : || true
adb -s "$S" reverse --remove-all 2>/dev/null || true

FLOW=$(ls -t yuepao_*.flow 2>/dev/null | head -1)
if [ -n "${FLOW:-}" ]; then
  echo "导出 HAR: ${FLOW%.flow}.har"
  mitmproxy -n -r "$FLOW" -w "${FLOW%.flow}.har" --set console_event_codes= 2>/dev/null \
    || python3 -m mitmproxy -r "$FLOW" -w "${FLOW%.flow}.har" 2>/dev/null
  echo "flow 大小: $(du -h "$FLOW" | cut -f1)"
  ls -la "${FLOW%.flow}.har" 2>/dev/null
fi
echo "done. 喊 Zynamis 读 ${FLOW:-<flow>} (format=mitmproxy)"
