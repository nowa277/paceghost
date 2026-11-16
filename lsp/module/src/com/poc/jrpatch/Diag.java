package com.poc.jrpatch;

import android.content.Context;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.security.MessageDigest;

/**
 * 诊断导出 (模块 v8) — 打印 app 本地存了哪些设备标识
 *
 * 目的: 「设备过多无法登录」是服务端按 deviceId 限流。要确认 deviceId 到底是什么、
 *       存在哪、能不能固定住，先把 app 私有目录里的东西导出来看。
 *
 * 触发: settings put global jrdiag 1   然后重启 app
 * 输出: /sdcard/Android/data/<pkg>/files/diag.txt
 */
public final class Diag {
    private static final String TAG = "JRPatch";
    private static final String OUT = "diag.txt";

    private Diag() {}

    public static void install() {
        Thread t = new Thread(Diag::run, "jrdiag");
        t.setDaemon(true);
        t.start();
    }

    private static void run() {
        Context c = null;
        for (int i = 0; i < 60 && c == null; i++) {
            try { Thread.sleep(500); } catch (InterruptedException e) { return; }
            c = ctx();
        }
        if (c == null) { JrLog.w("diag: no context"); return; }

        boolean on;
        try {
            on = android.provider.Settings.Global.getInt(
                    c.getContentResolver(), "jrdiag", 0) != 0;
        } catch (Throwable t) {
            on = false;
        }
        if (!on) return;

        // 给 Dart 侧一点时间把 pref 写出来
        try { Thread.sleep(4000); } catch (InterruptedException e) { return; }

        StringBuilder sb = new StringBuilder();
        sb.append("=== pkg: ").append(c.getPackageName()).append('\n');
        sb.append("=== dataDir: ").append(c.getApplicationInfo().dataDir).append('\n');
        sb.append("=== sourceDir: ").append(c.getApplicationInfo().sourceDir).append('\n');
        sb.append("=== android_id: ").append(androidId(c)).append("\n\n");

        dumpDir(sb, "shared_prefs", new File(c.getApplicationInfo().dataDir, "shared_prefs"), true);
        dumpDir(sb, "files", c.getFilesDir(), true);
        dumpDir(sb, "databases", new File(c.getApplicationInfo().dataDir, "databases"), false);
        dumpDir(sb, "cache", c.getCacheDir(), false);

        try {
            File dir = c.getExternalFilesDir(null);
            if (dir != null) {
                File out = new File(dir, OUT);
                FileOutputStream fos = new FileOutputStream(out);
                try {
                    fos.write(sb.toString().getBytes("UTF-8"));
                    fos.flush();
                    fos.getFD().sync();
                } finally {
                    fos.close();
                }
                JrLog.w("diag: written " + out.getAbsolutePath()
                        + " (" + out.length() + "B)");
            }
        } catch (Throwable t) {
            JrLog.w("diag: write error " + t);
        }
    }

    private static void dumpDir(StringBuilder sb, String label, File dir, boolean withContent) {
        sb.append("--- ").append(label).append(" (").append(dir).append(")\n");
        if (dir == null || !dir.isDirectory()) {
            sb.append("    <absent>\n\n");
            return;
        }
        File[] fs = dir.listFiles();
        if (fs == null) {
            sb.append("    <unreadable>\n\n");
            return;
        }
        java.util.Arrays.sort(fs);
        for (File f : fs) {
            sb.append("    ").append(f.getName()).append("  ").append(f.length()).append("B\n");
            if (!withContent || !f.isFile() || f.length() > 256 * 1024) continue;
            try {
                sb.append("      >>> ").append(readAll(f)).append("\n");
            } catch (Throwable t) {
                sb.append("      <read error ").append(t).append(">\n");
            }
        }
        sb.append('\n');
    }

    private static String readAll(File f) throws Exception {
        BufferedReader r = new BufferedReader(new InputStreamReader(new FileInputStream(f), "UTF-8"));
        StringBuilder sb = new StringBuilder();
        try {
            char[] buf = new char[4096];
            int n;
            while ((n = r.read(buf)) > 0) sb.append(buf, 0, n);
        } finally {
            r.close();
        }
        return sb.toString();
    }

    private static String androidId(Context c) {
        try {
            return android.provider.Settings.Secure.getString(
                    c.getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
        } catch (Throwable t) {
            return "<err " + t + ">";
        }
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
