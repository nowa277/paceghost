#!/bin/bash
# 换人脸照片 (免重打包)
# 用法: face_set.sh <图片路径> [设备序列号]
#   图片会被裁成 1080x1920 JPEG 推到 app 外部私有目录, 模块下次 takePicture 直接用
set -e
SRC="$1"; SER="${2:-}"
[ -z "$SRC" ] && { echo "用法: face_set.sh <图片路径> [序列号]"; exit 1; }
[ -f "$SRC" ] || { echo "文件不存在: $SRC"; exit 1; }

PKG=com.joyrunworld.app
TMP=$(mktemp -d)
OUT="$TMP/face_use.jpg"

echo "[1/4] 处理图片 -> 1080x1920 JPEG"
/usr/bin/magick "$SRC" -auto-orient \
  -resize '1080x1920^' -gravity center -extent 1080x1920 \
  -strip -quality 92 "$OUT"
ls -l "$OUT" | awk '{print "      处理完: "$5" 字节"}'

A=(adb); [ -n "$SER" ] && A+=(-s "$SER")

echo "[2/4] 确保目录存在"
"${A[@]}" shell "mkdir -p /sdcard/Android/data/$PKG/files" >/dev/null

echo "[3/4] 推送"
"${A[@]}" push "$OUT" "/sdcard/Android/data/$PKG/files/face_use.jpg" | tail -1

echo "[4/4] 校验"
"${A[@]}" shell "ls -l /sdcard/Android/data/$PKG/files/face_use.jpg"
"${A[@]}" shell "settings delete global jrface_src" >/dev/null 2>&1 || true
echo
echo "完成。下次弹人脸时模块会自动用新图 (不用重启 app, 不用重装)。"
rm -rf "$TMP"
