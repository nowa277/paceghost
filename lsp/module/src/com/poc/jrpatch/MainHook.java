package com.poc.jrpatch;

import android.app.AppOpsManager;
import android.location.Location;

import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;
import de.robv.android.xposed.callbacks.XC_LoadPackage;

/**
 * 悦跑世界 mock 放行模块 (LSPatch 内嵌)
 *
 * smali 依据 (dec_v2):
 *  - com/amap/flutter/location/AMapLocationClientImpl.smali: setLocationOption 硬编码 setMockEnable(false)
 *  - com/amap/api/col/3sl/f.smali: !isMockEnable 且 fix 为 mock -> 计数>4 -> errorCode(15)
 *      "GpsLocation has been mocked!#1501" + 坐标清零
 *  - com/amap/api/col/3sl/u.smali:338: Reflect.invokeMethod(loc,"isFromMockProvider") 反射读取
 *      (ArtMethod hook 对反射同样生效)
 *  - smali_classes2/k/a.smali: security_plus 检测链:
 *      AppOps.checkOp("android:mock_location") + getLastKnownLocation().isFromMockProvider()
 */
public class MainHook implements IXposedHookLoadPackage {
    private static final String TAG = "JRPatch";
    private static final String TARGET_PKG = "com.joyrunworld.app";
    private static final String AMAP_OPT = "com.amap.api.location.AMapLocationClientOption";

    @Override
    public void handleLoadPackage(XC_LoadPackage.LoadPackageParam lpp) {
        if (!TARGET_PKG.equals(lpp.packageName)) return;
        XposedBridge.log(TAG + ": injected into " + lpp.packageName);
        ClassLoader cl = lpp.classLoader;

        // 0) 日志: logcat + app 外部私有目录文件双通道 (尽早, 后面 hook 都走它)
        try {
            JrLog.install(cl);
        } catch (Throwable t) {
            XposedBridge.log(TAG + ": JrLog install FAIL: " + t);
        }

        // 1) AMapLocationClientOption.setMockEnable(false) -> 参数改为 true
        try {
            XposedHelpers.findAndHookMethod(AMAP_OPT, cl, "setMockEnable",
                    boolean.class, new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    param.args[0] = Boolean.TRUE;
                }
            });
            XposedBridge.log(TAG + ": hook setMockEnable ok");
        } catch (Throwable t) {
            XposedBridge.log(TAG + ": setMockEnable hook FAIL: " + t);
        }

        // 2) isMockEnable() -> 永远 true (引擎 3sl/f 的放行开关)
        try {
            XposedHelpers.findAndHookMethod(AMAP_OPT, cl, "isMockEnable",
                    new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    param.setResult(Boolean.TRUE);
                }
            });
            XposedBridge.log(TAG + ": hook isMockEnable ok");
        } catch (Throwable t) {
            XposedBridge.log(TAG + ": isMockEnable hook FAIL: " + t);
        }

        // 3) Location.isFromMockProvider() -> false (覆盖直调 + AMap 反射 + security_plus)
        try {
            XposedHelpers.findAndHookMethod(Location.class, "isFromMockProvider",
                    new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    param.setResult(Boolean.FALSE);
                }
            });
            XposedBridge.log(TAG + ": hook isFromMockProvider ok");
        } catch (Throwable t) {
            XposedBridge.log(TAG + ": isFromMockProvider hook FAIL: " + t);
        }

        // 4) API 31+: Location.isMock() -> false
        try {
            XposedHelpers.findAndHookMethod(Location.class, "isMock",
                    new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    param.setResult(Boolean.FALSE);
                }
            });
            XposedBridge.log(TAG + ": hook isMock ok");
        } catch (Throwable ignored) { }

        // 5) AppOpsManager.checkOp(String,int,String) -> mock_location 一律非 allowed
        try {
            XposedHelpers.findAndHookMethod(AppOpsManager.class, "checkOp",
                    String.class, int.class, String.class, new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    Object op = param.args[0];
                    if (op instanceof String && ((String) op).contains("mock_location")) {
                        param.setResult(1); // MODE_IGNORED != MODE_ALLOWED(0)
                    }
                }
            });
            XposedBridge.log(TAG + ": hook checkOp ok");
        } catch (Throwable t) {
            XposedBridge.log(TAG + ": checkOp hook FAIL: " + t);
        }

        // 6) 计步合成 (v2): L0.c sink 接管 + L0.b 真实事件屏蔽, settings global 调参
        StepHook.install(cl);

        // 7) 人脸校验图片顶替 (v4): takePicture 不走相机, 直接回预置 jpg 路径
        FaceHook.install(cl);

        // 8) 进程内 GPS 注入 (v5): 华为等无 ADB test-provider 的 ROM 靠这条
        //    (默认关闭 jrgps_feed=0, 与 ADB 注入路线互斥)
        GpsFeed.install();

        // 9) 设备标识诊断 (v8): jrdiag=1 时导出 shared_prefs 到外部目录
        Diag.install();

        // 10) 设备标识可控 (v9): 覆盖 ANDROID_ID, 免重装换账号
        DeviceHook.install(cl);

        JrLog.w("module v9 loaded");
    }
}
