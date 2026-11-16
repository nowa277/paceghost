package com.poc.jrpatch;

import android.content.Context;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.lang.reflect.Method;

import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;

/**
 * 人脸校验图片顶替 (模块 v4)
 *
 * 逆向依据 (smali classes5):
 *
 *  A) io.flutter.plugins.camerax.ImageCaptureProxyApi.takePicture(ImageCapture, SystemServicesManager, Function1)
 *       File.createTempFile("CAP", ".jpg", getCacheDir())
 *       -> createImageCaptureOutputFileOptions(file)
 *       -> createOnImageSavedCallback(file, ssm, dartCallback)   // 返回 ImageCaptureProxyApi$1
 *       -> ImageCapture.takePicture(options, executor, callback)
 *
 *  B) io.flutter.plugins.camerax.ImageCaptureProxyApi$1.onImageSaved(OutputFileResults)
 *       val$file.getAbsolutePath()  ->  ResultCompat.success(path, dartCallback)
 *     !! 参数 p1 立刻被 this.val$file 覆盖, 内容从头到尾没人读 -> 传 null 即可
 *
 *  => 完全不需要开相机: 自建临时文件写入预置 jpg, 自建 callback 对象直接回调 onImageSaved(null)
 *
 *  C) io.flutter.plugins.imagepicker.ImagePickerDelegate.takeImageWithCamera(ImageSelectionOptions, Function1)
 *       -> ResultUtilsKt.completeWithValue(callback, path)   (备用路径: 系统相机 Intent)
 *
 * 配置 (adb shell settings put global KEY VAL):
 *   jrface_on   1/0     总开关 (默认 1)
 *   jrface_src  路径    覆盖源图片 (默认取 app 外部私有目录 face_use.jpg)
 */
public final class FaceHook {
    private static final String TAG = "JRPatch";

    private static final String CLS_IMG_CAPTURE = "io.flutter.plugins.camerax.ImageCaptureProxyApi";
    private static final String CLS_SSM         = "io.flutter.plugins.camerax.SystemServicesManager";
    private static final String CLS_FUNCTION1   = "kotlin.jvm.functions.Function1";
    private static final String CLS_PICKER      = "io.flutter.plugins.imagepicker.ImagePickerDelegate";
    private static final String CLS_PICKER_RES  = "io.flutter.plugins.imagepicker.ResultUtilsKt";

    private static final String FACE_NAME = "face_use.jpg";
    private static final String ASSET_PATH = "assets/face.jpg";

    private static volatile ClassLoader appCl;
    private static volatile Context appCtx;
    private static volatile boolean sawTakePicture = false;

    private FaceHook() {}

    public static void install(ClassLoader cl) {
        appCl = cl;
        startSelfTest();

        // ---- camerax: 主干路径 ----
        try {
            XposedHelpers.findAndHookMethod(CLS_IMG_CAPTURE, cl, "takePicture",
                    "androidx.camera.core.ImageCapture", CLS_SSM, CLS_FUNCTION1,
                    new XC_MethodHook() {
                @Override protected void beforeHookedMethod(MethodHookParam param) {
                    try {
                        Context ctx0 = contextOf(param.thisObject);
                        if (ctx0 != null) JrLog.bind(ctx0);
                        if (!sawTakePicture) {
                            sawTakePicture = true;
                            JrLog.w("face: takePicture invoked (first time)");
                        }
                        if (!enabled()) return;
                        Object proxyApi = param.thisObject;
                        Object ssm = param.args[1];
                        Object dartCb = param.args[2];

                        Context ctx = ctx0;
                        if (ctx == null) { JrLog.w("face: no context"); return; }

                        File src = resolveSource(ctx);
                        if (src == null || !src.isFile() || src.length() < 1024) {
                            JrLog.w("face: source image missing");
                            return;
                        }

                        File out = File.createTempFile("CAP", ".jpg", ctx.getCacheDir());
                        copy(src, out);

                        Object cbObj = buildCallback(proxyApi, out, ssm, dartCb);
                        if (cbObj == null) { JrLog.w("face: buildCallback null"); return; }

                        invokeImageSaved(cbObj);
                        param.setResult(null);   // 跳过真实相机
                        JrLog.w("face: substituted " + src.getName() + " (" + out.length()
                                + "B) -> " + out.getName());
                    } catch (Throwable t) {
                        JrLog.w("face: camerax hook error " + t);
                    }
                }
            });
            JrLog.w("hook takePicture ok");
        } catch (Throwable t) {
            JrLog.w("takePicture hook FAIL: " + t);
        }

        // ---- imagepicker: 系统相机 Intent 路径 (备用) ----
        try {
            XposedHelpers.findAndHookMethod(CLS_PICKER, cl, "takeImageWithCamera",
                    "io.flutter.plugins.imagepicker.ImageSelectionOptions", CLS_FUNCTION1,
                    new XC_MethodHook() {
                @Override protected void beforeHookedMethod(MethodHookParam param) {
                    try {
                        if (!enabled()) return;
                        Context ctx = appCtx;
                        if (ctx == null) ctx = contextOf(param.thisObject);
                        if (ctx == null) return;

                        File src = resolveSource(ctx);
                        if (src == null || !src.isFile()) return;

                        File out = File.createTempFile("IMG", ".jpg", ctx.getCacheDir());
                        copy(src, out);

                        Method mv = cl.loadClass(CLS_PICKER_RES).getMethod(
                                "completeWithValue", cl.loadClass(CLS_FUNCTION1), Object.class);
                        mv.invoke(null, param.args[1], out.getAbsolutePath());
                        param.setResult(null);
                        JrLog.w("face: imagepicker substituted -> " + out.getName());
                    } catch (Throwable t) {
                        JrLog.w("face: imagepicker hook error " + t);
                    }
                }
            });
            JrLog.w("hook takeImageWithCamera ok");
        } catch (Throwable t) {
            JrLog.w("takeImageWithCamera hook FAIL: " + t);
        }
    }

    // ------------------------------------------------------------------

    /** 启动自检: 等 app context 就绪后探一次源图可用性, 结果写日志 */
    private static void startSelfTest() {
        Thread t = new Thread(() -> {
            Context c = null;
            for (int i = 0; i < 120 && c == null; i++) {
                try { Thread.sleep(500); } catch (InterruptedException e) { return; }
                c = appCtx != null ? appCtx : probeContext();
            }
            if (c == null) { JrLog.w("face: selftest no context"); return; }
            appCtx = c;
            File f = resolveSource(c);
            if (f == null) {
                JrLog.w("face: selftest FAIL no source image");
            } else {
                JrLog.w("face: selftest ok " + f.getAbsolutePath() + " " + f.length() + "B");
            }
        }, "jrface-selftest");
        t.setDaemon(true);
        t.start();
    }

    private static Context probeContext() {
        try {
            Class<?> at = Class.forName("android.app.ActivityThread");
            Object app = at.getMethod("currentApplication").invoke(null);
            if (app instanceof Context) return ((Context) app).getApplicationContext();
        } catch (Throwable ignored) { }
        return null;
    }

    private static Object buildCallback(Object proxyApi, File file, Object ssm, Object dartCb)
            throws Exception {
        ClassLoader cl = appCl;
        Method mk = proxyApi.getClass().getMethod("createOnImageSavedCallback",
                File.class, cl.loadClass(CLS_SSM), cl.loadClass(CLS_FUNCTION1));
        return mk.invoke(proxyApi, file, ssm, dartCb);
    }

    private static void invokeImageSaved(Object cbObj) throws Exception {
        ClassLoader cl = appCl;
        Method m = cbObj.getClass().getDeclaredMethod("onImageSaved",
                cl.loadClass("androidx.camera.core.ImageCapture$OutputFileResults"));
        m.setAccessible(true);
        m.invoke(cbObj, new Object[]{null});
    }

    private static Context contextOf(Object proxyApi) {
        try {
            Method g = proxyApi.getClass().getMethod("getPigeonRegistrar");
            Object reg = g.invoke(proxyApi);
            Method gc = reg.getClass().getMethod("getContext");
            Context c = (Context) gc.invoke(reg);
            if (c != null) appCtx = c.getApplicationContext();
            return appCtx;
        } catch (Throwable t) {
            return appCtx;
        }
    }

    private static File resolveSource(Context ctx) {
        String over = cfg("jrface_src", "");
        if (over.length() > 0) {
            File f = new File(over);
            if (f.isFile()) return f;
        }
        File ext = ctx.getExternalFilesDir(null);
        if (ext != null) {
            File f = new File(ext, FACE_NAME);
            if (f.isFile()) return f;
        }
        File internal = new File(ctx.getFilesDir(), FACE_NAME);
        if (internal.isFile()) return internal;
        File dl = new File("/sdcard/Download/" + FACE_NAME);
        if (dl.isFile()) return dl;
        return extractAsset(ctx);
    }

    /** 从模块 APK 自带资产解出图片到 cacheDir (免权限, 免外部文件, 重启不丢) */
    private static File extractAsset(Context ctx) {
        try {
            ClassLoader cl = FaceHook.class.getClassLoader();
            InputStream in = cl.getResourceAsStream(ASSET_PATH);
            if (in == null) {
                in = FaceHook.class.getResourceAsStream("/" + ASSET_PATH);
            }
            if (in == null) return null;
            File out = new File(ctx.getCacheDir(), FACE_NAME);
            FileOutputStream fos = new FileOutputStream(out);
            try {
                byte[] buf = new byte[16384];
                int n;
                long total = 0;
                while ((n = in.read(buf)) > 0) { fos.write(buf, 0, n); total += n; }
                fos.flush();
                fos.getFD().sync();
                if (total < 1024) return null;
            } finally {
                try { in.close(); } catch (Throwable ignored) { }
                try { fos.close(); } catch (Throwable ignored) { }
            }
            return out;
        } catch (Throwable t) {
            JrLog.w("face: extractAsset error " + t);
            return null;
        }
    }

    private static boolean enabled() {
        Context ctx = appCtx;
        if (ctx == null) return true;
        try {
            return android.provider.Settings.Global.getInt(
                    ctx.getContentResolver(), "jrface_on", 1) != 0;
        } catch (Throwable t) {
            return true;
        }
    }

    private static String cfg(String key, String def) {
        Context ctx = appCtx;
        if (ctx == null) return def;
        try {
            String v = android.provider.Settings.Global.getString(ctx.getContentResolver(), key);
            return v == null ? def : v;
        } catch (Throwable t) {
            return def;
        }
    }

    private static void copy(File src, File dst) throws Exception {
        InputStream in = new FileInputStream(src);
        FileOutputStream out = new FileOutputStream(dst);
        try {
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            out.flush();
            out.getFD().sync();
        } finally {
            try { in.close(); } catch (Throwable ignored) { }
            try { out.close(); } catch (Throwable ignored) { }
        }
    }
}
