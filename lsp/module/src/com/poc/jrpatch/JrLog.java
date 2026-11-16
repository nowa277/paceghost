package com.poc.jrpatch;

import android.app.Application;
import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;

/**
 * 双通道日志: logcat(XposedBridge) + 文件 (app 外部私有目录 jrpatch.log)
 * 文件通道用于 logcat 缓冲区滚掉后回溯 hook 是否触发。
 */
public final class JrLog {
    private static final String TAG = "JRPatch";
    private static final String FILE_NAME = "jrpatch.log";
    private static final long MAX_BYTES = 256 * 1024;

    private static volatile Context ctx;
    private static final SimpleDateFormat TS =
            new SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US);

    private JrLog() {}

    /** handleLoadPackage 阶段调用: 装 Application 钩子拿 Context, 并起兜底轮询线程 */
    public static void install(ClassLoader cl) {
        XC_MethodHook grab = new XC_MethodHook() {
            @Override protected void afterHookedMethod(MethodHookParam param) {
                Object self = param.thisObject;
                if (self instanceof Context) bind((Context) self);
            }
        };
        try {
            XposedHelpers.findAndHookMethod(Application.class, "onCreate", grab);
        } catch (Throwable ignored) { }
        try {
            XposedHelpers.findAndHookMethod(Application.class, "attach", Context.class, grab);
        } catch (Throwable ignored) { }

        Thread t = new Thread(() -> {
            for (int i = 0; i < 120 && ctx == null; i++) {
                try { Thread.sleep(500); } catch (InterruptedException e) { return; }
                ctx();
            }
            if (ctx != null) JrLog.w("context bound: " + ctx.getPackageName());
        }, "jrlogbind");
        t.setDaemon(true);
        t.start();
    }

    public static void bind(Context c) {
        if (c != null) ctx = c.getApplicationContext();
    }

    /** 懒解析: ActivityThread.currentApplication() 兜底 */
    private static Context ctx() {
        Context c = ctx;
        if (c != null) return c;
        try {
            Class<?> at = Class.forName("android.app.ActivityThread");
            Object app = at.getMethod("currentApplication").invoke(null);
            if (app instanceof Context) {
                c = ((Context) app).getApplicationContext();
                ctx = c;
            }
        } catch (Throwable ignored) { }
        return c;
    }

    public static void w(String msg) {
        XposedBridge.log(TAG + ": " + msg);
        Context c = ctx();
        if (c == null) return;
        try {
            File dir = c.getExternalFilesDir(null);
            if (dir == null || !dir.isDirectory()) return;
            File f = new File(dir, FILE_NAME);
            if (f.isFile() && f.length() > MAX_BYTES) {
                File old = new File(dir, FILE_NAME + ".1");
                if (old.isFile()) old.delete();
                f.renameTo(old);
                f = new File(dir, FILE_NAME);
            }
            FileOutputStream out = new FileOutputStream(f, true);
            try {
                String line = TS.format(new Date()) + " " + msg + "\n";
                out.write(line.getBytes("UTF-8"));
            } finally {
                out.close();
            }
        } catch (Throwable ignored) { }
    }
}
