#!/bin/bash
# 换账号 / 重置设备标识 (悦跑世界)
# 用法: joyrun_account.sh [--serial X] [--keep-data]
#   默认: 卸载重装 (清掉 app 自生成设备 UUID -> 服务端视为新设备)
#   --keep-data: 只清 app 数据不卸载 (install -r 保留 APK, 速度更快)
set -e
SER=""
KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --serial) SER="$2"; shift 2;;
    --keep-data) KEEP=1; shift;;
    *) echo "未知参数: $1"; exit 1;;
  esac
done

PKG=com.joyrunworld.app
APK=/home/sesley/Workspace/paceghost/lsp/out-v6/base-487-lspatched.apk
A=(adb); [ -n "$SER" ] && A+=(-s "$SER")

[ -f "$APK" ] || { echo "APK 不存在: $APK"; exit 1; }

echo "[1/6] 备份人脸图"
BK=$(mktemp -d)
"${A[@]}" pull /sdcard/Android/data/$PKG/files/face_use.jpg "$BK/face_use.jpg" >/dev/null 2>&1 \
  && echo "      已备份" || echo "      无备份 (跳过)"

echo "[2/6] 停止 app"
"${A[@]}" shell "am force-stop $PKG" >/dev/null 2>&1 || true

if [ "$KEEP" -eq 1 ]; then
  echo "[3/6] 清 app 数据 (保留 APK)"
  "${A[@]}" shell "pm clear $PKG" >/dev/null
else
  echo "[3/6] 卸载"
  "${A[@]}" uninstall $PKG >/dev/null 2>&1 || true
  echo "[4/6] 重装补丁版"
  "${A[@]}" install -r -d "$APK" | tail -1
fi

echo "[5/6] 补权限 + mock_location"
"${A[@]}" shell "pm grant $PKG android.permission.CAMERA" 2>/dev/null || true
"${A[@]}" shell "pm grant $PKG android.permission.ACTIVITY_RECOGNITION" 2>/dev/null || true
"${A[@]}" shell "pm grant $PKG android.permission.ACCESS_FINE_LOCATION" 2>/dev/null || true
"${A[@]}" shell "pm grant $PKG android.permission.ACCESS_COARSE_LOCATION" 2>/dev/null || true
"${A[@]}" shell "appops set $PKG android:mock_location allow"

echo "[6/6] 恢复人脸图 + 参数"
if [ -f "$BK/face_use.jpg" ]; then
  "${A[@]}" shell "mkdir -p /sdcard/Android/data/$PKG/files" >/dev/null
  "${A[@]}" push "$BK/face_use.jpg" /sdcard/Android/data/$PKG/files/face_use.jpg >/dev/null
  echo "      人脸图已恢复 ($(stat -c%s "$BK/face_use.jpg") 字节)"
fi
"${A[@]}" shell "settings put global jrface_on 1; settings put global jrstep_on 1; settings put global jrstep_cadence 127" >/dev/null

rm -rf "$BK"
echo
echo "完成。现在可以登录任意账号 (服务端会当成新设备)。"
echo "拉起 app: adb -s ${SER:-<auto>} shell monkey -p $PKG -c android.intent.category.LAUNCHER 1"
