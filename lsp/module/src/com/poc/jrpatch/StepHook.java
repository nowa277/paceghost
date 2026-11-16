package com.poc.jrpatch;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;

/**
 * 计步合成器 (模块 v2)
 *
 * 逆向依据 (jadx v1.1.21 / smali classes4):
 *   L0.a  pedometer 插件; init 后建两个 EventChannel:
 *         "step_detection" -> L0.c(binding, 18) 每步发 1
 *         "step_count"     -> L0.c(binding, 19) 发开机累计步数
 *   L0.c  字段: a=L0.b listener, b=SensorManager, c=Sensor, d=String 通道名("StepDetection"/"StepCount")
 *   L0.c.onListen(Object, EventSink) 注册真实传感器
 *   L0.b.onSensorChanged(SensorEvent) -> values[0] 直接 success() 给 Dart
 *
 * 策略:
 *   1) hook L0.c.onListen: 捕获 EventSink; hook onCancel 释放
 *   2) hook L0.b.onSensorChanged: 默认屏蔽真实传感器 (防手摇双计), jrstep_real=1 放行
 *   3) 合成引擎线程: 按步频累积步数, 主线程 post 到 sink
 *   4) 远程调参 (adb shell settings put global KEY VAL), 每秒热读:
 *        jrstep_on       1/0  合成开关 (默认 1)
 *        jrstep_cadence  步/分 (默认 118)
 *        jrstep_real     1/0  放行真实传感器 (默认 0)
 *        jrstep_base     累计初值 (默认 0 = 自动取时间派生值)
 */
public final class StepHook {
    private static final String TAG = "JRPatch";
    private static final String CLS_A = "L0.a";
    private static final String CLS_B = "L0.b";
    private static final String CLS_C = "L0.c";

    private static volatile Context appCtx;
    private static volatile boolean running = false;
    private static volatile double cadence = 118.0;
    private static volatile boolean synthOn = true;
    private static volatile boolean realPassthrough = false;
    private static volatile int baseOverride = 0;

    private static volatile Object countSink;    // step_count
    private static volatile Object detectSink;   // step_detection

    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final java.util.Random RNG = new java.util.Random(20261116L);

    private StepHook() {}

    public static void install(ClassLoader cl) {
        // app context
        try {
            XposedHelpers.findAndHookMethod(CLS_A, cl, "onAttachedToEngine",
                    "io.flutter.embedding.engine.plugins.FlutterPlugin$FlutterPluginBinding",
                    new XC_MethodHook() {
                @Override protected void afterHookedMethod(MethodHookParam param) {
                    try {
                        appCtx = (Context) XposedHelpers.callMethod(param.args[0], "getApplicationContext");
                        JrLog.bind(appCtx);
                    } catch (Throwable ignored) { }
                }
            });
        } catch (Throwable t) {
            JrLog.w("L0.a hook FAIL: " + t);
        }

        // 通道监听开始 -> 抓 sink 并启动合成
        try {
            XposedHelpers.findAndHookMethod(CLS_C, cl, "onListen",
                    Object.class, "io.flutter.plugin.common.EventChannel$EventSink",
                    new XC_MethodHook() {
                @Override protected void afterHookedMethod(MethodHookParam param) {
                    Object self = param.thisObject;
                    String name;
                    try {
                        name = (String) XposedHelpers.getObjectField(self, "d");
                    } catch (Throwable t) {
                        JrLog.w("read channel name FAIL " + t);
                        return;
                    }
                    Object sink = param.args[1];
                    if ("StepCount".equals(name)) {
                        countSink = sink;
                        JrLog.w("step_count sink captured");
                    } else {
                        detectSink = sink;
                        JrLog.w("step_detection sink captured");
                    }
                    startEngine();
                }
            });
            XposedHelpers.findAndHookMethod(CLS_C, cl, "onCancel", Object.class,
                    new XC_MethodHook() {
                @Override protected void afterHookedMethod(MethodHookParam param) {
                    Object self = param.thisObject;
                    String name = null;
                    try { name = (String) XposedHelpers.getObjectField(self, "d"); } catch (Throwable ignored) { }
                    if ("StepCount".equals(name)) countSink = null;
                    else detectSink = null;
                    if (countSink == null && detectSink == null) stopEngine();
                    JrLog.w("channel cancelled " + name);
                }
            });
            JrLog.w("hook L0.c onListen/onCancel ok");
        } catch (Throwable t) {
            JrLog.w("L0.c hook FAIL: " + t);
        }

        // 真实传感器事件屏蔽 (安全设计: 只在合成真正生效时才屏蔽, 否则放行)
        try {
            XposedHelpers.findAndHookMethod(CLS_B, cl, "onSensorChanged",
                    "android.hardware.SensorEvent", new XC_MethodHook() {
                @Override protected void beforeHookedMethod(MethodHookParam param) {
                    if (realPassthrough) return;              // 显式放行
                    if (!synthOn) return;                     // 合成关闭 -> 真实工作
                    if (!running) return;                     // 引擎没跑 -> 真实工作
                    if (countSink == null && detectSink == null) return; // 无订阅 -> 真实工作
                    param.setResult(null);                    // 合成生效 -> 屏蔽防双计
                }
            });
            JrLog.w("hook L0.b onSensorChanged (conditional suppress) ok");
        } catch (Throwable t) {
            JrLog.w("L0.b hook FAIL: " + t);
        }
    }

    private static synchronized void startEngine() {
        if (running) return;
        running = true;
        Thread th = new Thread(StepHook::engineLoop, "jrstep");
        th.setDaemon(true);
        th.start();
        JrLog.w("step engine started");
    }

    private static synchronized void stopEngine() {
        running = false;
        JrLog.w("step engine stopped");
    }

    private static void engineLoop() {
        int base = baseOverride > 0 ? baseOverride
                : 1000 + (int) (System.currentTimeMillis() % 3000);
        double cumulative = base;
        double acc = 0.0;
        long last = System.nanoTime();
        int tick = 0;

        while (running) {
            try { Thread.sleep(100); } catch (InterruptedException e) { break; }
            long now = System.nanoTime();
            double dt = (now - last) / 1e9;
            last = now;

            if ((tick++ % 10) == 0) {
                readConfig();
                if (baseOverride > 0 && cumulative < baseOverride) cumulative = baseOverride;
            }
            if (!synthOn) continue;

            double wob = Math.sin(now / 1e9 / 9.7) * 0.03;          // ±3% 慢漂
            double jit = (RNG.nextDouble() - 0.5) * 0.02;           // ±1% 抖动
            double eff = cadence * (1.0 + wob + jit);

            acc += eff / 60.0 * dt;
            int newSteps = 0;
            while (acc >= 1.0) { acc -= 1.0; cumulative += 1.0; newSteps++; }

            final int steps = newSteps;
            final int cum = (int) cumulative;
            if (steps > 0 || (tick % 10) == 0) {
                MAIN.post(() -> {
                    Object ds = detectSink;
                    if (ds != null) {
                        for (int i = 0; i < steps; i++) {
                            try { XposedHelpers.callMethod(ds, "success", 1); } catch (Throwable ignored) { }
                        }
                    }
                    Object cs = countSink;
                    if (cs != null) {
                        try { XposedHelpers.callMethod(cs, "success", cum); } catch (Throwable ignored) { }
                    }
                });
            }
        }
    }

    private static void readConfig() {
        Context ctx = appCtx;
        if (ctx == null) return;
        try {
            android.content.ContentResolver cr = ctx.getContentResolver();
            synthOn = android.provider.Settings.Global.getInt(cr, "jrstep_on", 1) != 0;
            cadence = android.provider.Settings.Global.getInt(cr, "jrstep_cadence", 118);
            realPassthrough = android.provider.Settings.Global.getInt(cr, "jrstep_real", 0) != 0;
            baseOverride = android.provider.Settings.Global.getInt(cr, "jrstep_base", 0);
        } catch (Throwable ignored) { }
    }
}
