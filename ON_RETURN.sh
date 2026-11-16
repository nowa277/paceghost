#!/usr/bin/env bash
# 悦跑世界 · 回家开工 runbook (手机 USB 插上后跑)
# 用法: bash ~/Workspace/paceghost/ON_RETURN.sh
set -u
S=10CD9D0FR0001JD
Y=/home/sesley/Workspace/paceghost
TS=$(date +%m%d_%H%M)
FLOW=$Y/capture/yuepao_${TS}.flow

echo "===== [0] 设备确认 ====="
adb -s "$S" wait-for-device get-state || { echo "!! 设备未就绪(看手机是否弹'允许USB调试')"; exit 1; }
echo "SDK: $(adb -s "$S" shell getprop ro.build.version.sdk | tr -d '\r')"

echo "===== [1] USB 反向代理: 手机 127.0.0.1:8080 -> PC:8080 (流量走USB, 不依赖Wi-Fi) ====="
adb -s "$S" reverse tcp:8080 tcp:8080 && echo "reverse ok"

echo "===== [2] 手机全局代理指向 mitm ====="
adb -s "$S" shell settings put global http_proxy 127.0.0.1:8080
echo "当前代理: $(adb -s "$S" shell settings get global http_proxy | tr -d '\r')"
echo "(若返回 null 说明 adb 无权限写 global, 改手动: 手机设置→WLAN→当前网络→代理→手动 127.0.0.1 8080)"

echo "===== [3] mitmdump 启动, 存 flow ====="
cd "$Y/capture"
mitmdump -w "$FLOW" --set console_event_codes=Wr &
MITM_PID=$!
echo $MITM_PID > "$Y/capture/.mitm_pid"
echo "mitmdump PID=$MITM_PID  flow=$FLOW"
sleep 2
kill -0 $MITM_PID 2>/dev/null || { echo "!! mitmdump 起不来"; exit 1; }
echo "listening on :8080"

cat <<EOF

================ 接下来在手机上做 ================
 1. 打开悦跑世界, 登录, 随便点几个页面
    -> 浏览器开 http://mitm.it 能出图 = 链路通
 2. 开始一次真实跑步(正常速度跑300米~1公里即可, 别刷圈)
 3. 跑完点结束, 等上传完
 4. 再开第二次(间隔几秒的连续上报才对比得出字段变化)
 5. 回来喊我, 我跑: bash $Y/ON_RETURN_stop.sh 然后读 flow
EOF
