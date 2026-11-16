package com.poc.jrpatch;

import android.content.ContentResolver;
import android.content.Context;
import android.provider.Settings;

import java.security.SecureRandom;

import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedHelpers;

/**
 * 设备标识可控 (模块 v9) — 解决「设备过多无法登录」+ 随时换账号
 *
 * 原理:
 *   Android 8+ 起 Settings.Secure.ANDROID_ID 是 **按签名 + 用户 + 设备** 派生的,
 *   所以换签名会让它变 —— 这是之前 v6 换签名能绕过设备上限的真正原因。
 *   (我之前用 shell 视角读到 fa3ee9198d11f920 就下结论"没变", 那是错的;
 *    app 进程内读到的是 6bb58043615916bc, 两者不同作用域)
 *
 *   与其每次换签名+卸载重装(华为还要按指纹), 不如直接在进程内改返回值。
 *
 * 配置 (adb shell settings put global KEY VAL):
 *   jrdevice      覆盖用的 ANDROID_ID (16 hex); 空/不存在 = 用真实值
 *   jrdevice_rand 1 = 每次启动自动随机一个新的 ANDROID_ID (换账号最省事)
 *
 * 换账号流程:
 *   adb shell "settings put global jrdevice_rand 1"
 *   adb shell "am force-stop com.joyrunworld.app"
 *   # 重新打开 app -> 新设备指纹 -> 登录任意账号
 */
public final class DeviceHook {
    private static final String KEY = "jrdevice";
    private static final String KEY_RAND = "jrdevice_rand";

    private static volatile Context ctx;
    private static volatile String cached;
    private static volatile boolean resolved = false;

    private DeviceHook() {}

    public static void install(ClassLoader cl) {
        XC_MethodHook hook = new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam param) {
                try {
                    Object name = param.args.length > 1 ? param.args[1] : null;
                    if (!"android_id".equals(name)) return;
                    String v = value();
                    if (v != null && v.length() == 16) {
                        param.setResult(v);
                    }
                } catch (Throwable ignored) { }
            }
        };

        Class<?> secure = null;
        try {
            secure = Class.forName("android.provider.Settings$Secure");
        } catch (Throwable t) {
            JrLog.w("device: resolve Settings$Secure FAIL " + t);
        }

        if (secure != null) {
            boolean ok = false;
            try {
                XposedHelpers.findAndHookMethod(secure, "getString",
                        ContentResolver.class, String.class, hook);
                ok = true;
            } catch (Throwable t) {
                JrLog.w("device: hook getString(2) FAIL " + t);
            }
            try {
                XposedHelpers.findAndHookMethod(secure, "getString",
                        ContentResolver.class, String.class, String.class, hook);
                ok = true;
            } catch (Throwable t) {
                JrLog.w("device: hook getString(3) FAIL " + t);
            }
            JrLog.w("device: android_id hook " + (ok ? "ok" : "FAILED"));
        }

        // 启动时决定要不要随机一个
        Thread t = new Thread(DeviceHook::pickRandom, "jrdevice");
        t.setDaemon(true);
        t.start();
    }

    /** jrdevice_rand=1 且 jrdevice 为空时, 生成本进程内的随机值 */
    private static void pickRandom() {
        Context c = null;
        for (int i = 0; i < 80 && c == null; i++) {
            try { Thread.sleep(250); } catch (InterruptedException e) { return; }
            c = ctx();
        }
        if (c == null) { JrLog.w("device: no context"); return; }
        ctx = c;
        try {
            ContentResolver cr = c.getContentResolver();
            boolean rand = Settings.Global.getInt(cr, KEY_RAND, 0) != 0;
            String cur = Settings.Global.getString(cr, KEY);
            if (cur != null && cur.length() == 16) {
                cached = cur;
                resolved = true;
                JrLog.w("device: using jrdevice=" + cur);
            } else if (rand) {
                // app 无 WRITE_SECURE_SETTINGS, 不能回写; 本进程内随机即可
                String fresh = randomHex();
                cached = fresh;
                resolved = true;
                JrLog.w("device: random per-process jrdevice=" + fresh);
            } else {
                JrLog.w("device: passthrough (真实 ANDROID_ID)");
            }
        } catch (Throwable t) {
            JrLog.w("device: pickRandom error " + t);
        }
    }

    private static String value() {
        if (resolved) return cached;
        Context c = ctx();
        if (c == null) return null;
        ctx = c;
        try {
            String v = Settings.Global.getString(c.getContentResolver(), KEY);
            if (v != null && v.length() == 16) {
                cached = v;
                resolved = true;
                return v;
            }
        } catch (Throwable ignored) { }
        return null;
    }

    private static String randomHex() {
        SecureRandom r = new SecureRandom();
        byte[] b = new byte[8];
        r.nextBytes(b);
        StringBuilder sb = new StringBuilder(16);
        for (byte x : b) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    private static Context ctx() {
        try {
            Class<?> at = Class.forName("android.app.ActivityThread");
            Object app = at.getMethod("currentApplication").invoke(null);
            if (app instanceof Context) return ((Context) app).getApplicationContext();
        } catch (Throwable ignored) { }
        return null;
    }
}
