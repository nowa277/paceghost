#!/bin/bash
# 构建 JRPatch Xposed 模块并重新打补丁 APK
# 用法: ./build_module.sh [vN]   默认 v7
# 签名用 sign-20261116.jks (CN=JoyRun Tools); 换签名会让已装 app 覆盖安装失败, 必须卸载
set -e
BASE="$(cd "$(dirname "$0")/.." && pwd)"
MOD="$BASE/lsp/module"
LSP="$BASE/lsp"
SDK=/data/Applications/android-sdk
BT=$SDK/build-tools/34.0.0
JDK=/data/Applications/jdk-17
VER=${1:-v7}
SIGN_KS="$LSP/sign-20261116.jks"

cd "$MOD"
rm -rf build4 dexout4 module-$VER*.apk classes.dex
mkdir -p build4/classes build4/appcls dexout4

"$JDK/bin/javac" -nowarn -source 8 -target 8 -encoding UTF-8 \
  -cp "$SDK/platforms/android-34/android.jar" -d build4/classes \
  $(find src stubs -name "*.java") 2>&1 | grep -viE "warning|bootstrap|source value|target value|deprecat" || true

# 只把 com/** 打进 dex (de/robv 是编译期 stub, 运行时由 LSPatch 提供)
cp -r build4/classes/com build4/appcls/
JAVA_HOME=$JDK "$BT/d8" --min-api 21 --lib "$SDK/platforms/android-34/android.jar" \
  --output dexout4 $(find build4/appcls -name "*.class") 2>&1 | grep -v "Warning in\|Type \`de.robv" || true

JAVA_HOME=$JDK PATH=$JDK/bin:$PATH "$BT/aapt" package -f -M AndroidManifest.xml -A assets \
  -I "$SDK/platforms/android-34/android.jar" -F module-$VER-unsigned.apk
cp dexout4/classes.dex classes.dex
zip -q -X module-$VER-unsigned.apk classes.dex
rm -f classes.dex
"$BT/zipalign" -f 4 module-$VER-unsigned.apk module-$VER-aligned.apk
"$BT/apksigner" sign --ks "$SIGN_KS" --ks-pass pass:123456 \
  --ks-key-alias key0 --key-pass pass:123456 --out module-$VER.apk module-$VER-aligned.apk

mkdir -p "$LSP/out-$VER"
cd "$LSP"
unset JAVA_HOME
java -jar "$LSP/lspatch.jar" "$BASE/apk/com.joyrunworld.app/base.apk" \
  -m "module/module-$VER.apk" -l 2 -f -o "out-$VER" \
  --keystore "$SIGN_KS" 123456 key0 123456 2>&1 | tail -4
