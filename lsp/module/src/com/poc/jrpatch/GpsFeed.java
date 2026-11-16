package com.poc.jrpatch;

import android.content.ContentResolver;
import android.content.Context;
import android.location.Criteria;
import android.location.Location;
import android.location.LocationManager;
import android.os.SystemClock;
import android.provider.Settings;

/**
 * 进程内 GPS 注入 (模块 v5) — 给不支持 ADB test-provider 的 ROM 用 (华为 EMUI 等)
 *
 * 背景:
 *   Route Studio 走的是 `cmd location providers add-test-provider gps` 这条 ADB 通道,
 *   华为 EMUI 直接回 "No shell command implementation", 整条链断。
 *
 * 原理:
 *   AOSP LocationManagerService 里 mock provider 存在独立的 mMockProviders 表,
 *   与真实 provider 表互不冲突 -> 只要调用方有 android:mock_location appop,
 *   就能 addTestProvider("gps") 覆盖真实 GPS (这是免 root 假定位 App 的标准做法)。
 *   模块跑在 app 进程里, 只要 `appops set <pkg> android:mock_location allow` 就成立。
 *
 * 数据源:
 *   Settings.Global.jrpos = "lat,lon[,accuracy]"  (PC 侧 adb 写入, ~40ms 一次)
 *
 * 开关 (默认关, 避免和 vivo 那台的 ADB 注入打架):
 *   jrgps_feed  1/0   总开关 (默认 0)
 *
 * 说明:
 *   注入的 Location 天生带 mock 标记 -> 已被 MainHook 的
 *   isFromMockProvider()/isMock() 钩子统一改回 false。
 */
public final class GpsFeed {
    private static final String TAG = "JRPatch";
    private static final String KEY_POS = "jrpos";
    private static final String KEY_ON = "jrgps_feed";
    private static final String PROVIDER = "gps";
    private static final String PROVIDER_NET = "network";

    private static volatile Context ctx;
    private static volatile LocationManager lm;
    private static volatile boolean gpsReady = false;
    private static volatile boolean netReady = false;

    private static double lastLat = Double.NaN, lastLon = Double.NaN;
    private static long lastStamp = 0L;

    private GpsFeed() {}

    public static void install() {
        Thread t = new Thread(GpsFeed::loop, "jrgps-feed");
        t.setDaemon(true);
        t.start();
        JrLog.w("gpsfeed: thread started");
    }

    private static void loop() {
        String lastRaw = null;
        long lastInject = 0L;
        boolean wasOn = false;

        while (true) {
            try {
                Thread.sleep(200);
            } catch (InterruptedException e) {
                return;
            }

            Context c = ctx();
            if (c == null) continue;

            boolean on;
            String raw;
            try {
                ContentResolver cr = c.getContentResolver();
                on = Settings.Global.getInt(cr, KEY_ON, 0) != 0;
                raw = Settings.Global.getString(cr, KEY_POS);
            } catch (Throwable e) {
                continue;
            }

            // 关掉时释放 mock provider, 否则残留的 [mock] provider 会一直顶替真实 GPS
            if (!on) {
                if (wasOn || gpsReady || netReady) {
                    release();
                    wasOn = false;
                }
                continue;
            }
            wasOn = true;

            if (raw == null || raw.length() < 5) continue;

            long now = SystemClock.elapsedRealtime();
            boolean changed = !raw.equals(lastRaw);
            // 参数没变也要按秒刷新时间戳, 否则 app 判定 GPS 过期
            if (!changed && now - lastInject < 1000L) continue;
            lastRaw = raw;

            double[] p = parse(raw);
            if (p == null) continue;

            if (inject(c, p[0], p[1], p.length > 2 ? p[2] : 5.0)) {
                lastInject = now;
            }
        }
    }

    /** 拆掉自己注册的 mock provider, 把 GPS 交还给真实硬件 */
    private static void release() {
        LocationManager m = lm;
        if (m == null) return;
        for (String name : new String[]{PROVIDER, PROVIDER_NET}) {
            try {
                m.setTestProviderEnabled(name, false);
                m.removeTestProvider(name);
                JrLog.w("gpsfeed: removeTestProvider " + name + " ok");
            } catch (IllegalArgumentException e) {
                // 本来就不是 mock provider -> 已经干净
            } catch (Throwable t) {
                JrLog.w("gpsfeed: removeTestProvider " + name + " err " + t);
            }
        }
        gpsReady = false;
        netReady = false;
    }

    private static double[] parse(String raw) {
        try {
            String[] parts = raw.trim().split(",");
            if (parts.length < 2) return null;
            double lat = Double.parseDouble(parts[0].trim());
            double lon = Double.parseDouble(parts[1].trim());
            double acc = parts.length > 2 ? Double.parseDouble(parts[2].trim()) : 5.0;
            if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
            if (!Double.isFinite(lat) || !Double.isFinite(lon)) return null;
            return new double[]{lat, lon, acc};
        } catch (Throwable t) {
            return null;
        }
    }

    private static boolean inject(Context c, double lat, double lon, double acc) {
        try {
            LocationManager m = lm;
            if (m == null) {
                m = (LocationManager) c.getSystemService(Context.LOCATION_SERVICE);
                lm = m;
            }
            if (m == null) return false;

            if (!gpsReady && !ensureProvider(m, PROVIDER)) return false;
            if (!netReady) ensureProvider(m, PROVIDER_NET);

            long nowMs = System.currentTimeMillis();
            long nowNs = SystemClock.elapsedRealtimeNanos();

            Location loc = new Location(PROVIDER);
            loc.setLatitude(lat);
            loc.setLongitude(lon);
            loc.setAccuracy((float) acc);
            loc.setTime(nowMs);
            loc.setElapsedRealtimeNanos(nowNs);
            if (Double.isFinite(lastLat) && lastStamp > 0) {
                double dt = (nowMs - lastStamp) / 1000.0;
                if (dt > 0.2 && dt < 30) {
                    loc.setSpeed((float) (distance(lastLat, lastLon, lat, lon) / dt));
                }
            }
            try {
                loc.setAltitude(10.0);
            } catch (Throwable ignored) { }

            m.setTestProviderLocation(PROVIDER, loc);
            if (netReady) {
                Location n = new Location(PROVIDER_NET);
                n.setLatitude(lat);
                n.setLongitude(lon);
                n.setAccuracy((float) Math.max(acc, 50.0));
                n.setTime(nowMs);
                n.setElapsedRealtimeNanos(nowNs);
                try { m.setTestProviderLocation(PROVIDER_NET, n); } catch (Throwable ignored) { }
            }

            lastLat = lat;
            lastLon = lon;
            lastStamp = nowMs;
            return true;
        } catch (Throwable t) {
            JrLog.w("gpsfeed: inject error " + t);
            return false;
        }
    }

    private static boolean ensureProvider(LocationManager m, String name) {
        try {
            // 已存在同名 mock provider 会抛 IllegalArgumentException -> 视为就绪
            m.addTestProvider(name, false, true, false, false, true, true, true,
                    Criteria.POWER_LOW, Criteria.ACCURACY_FINE);
            JrLog.w("gpsfeed: addTestProvider " + name + " ok");
        } catch (IllegalArgumentException e) {
            JrLog.w("gpsfeed: " + name + " provider already mock");
        } catch (SecurityException e) {
            JrLog.w("gpsfeed: addTestProvider " + name + " DENIED (缺 mock_location appop) " + e);
            return false;
        } catch (Throwable t) {
            JrLog.w("gpsfeed: addTestProvider " + name + " err " + t);
        }
        try {
            m.setTestProviderEnabled(name, true);
        } catch (Throwable t) {
            JrLog.w("gpsfeed: setTestProviderEnabled " + name + " err " + t);
            return false;
        }
        if (PROVIDER.equals(name)) gpsReady = true;
        else netReady = true;
        JrLog.w("gpsfeed: " + name + " ready");
        return true;
    }

    private static double distance(double lat1, double lon1, double lat2, double lon2) {
        double r = 6371000.0;
        double p1 = Math.toRadians(lat1), p2 = Math.toRadians(lat2);
        double dp = p2 - p1;
        double dl = Math.toRadians(lon2 - lon1);
        double a = Math.sin(dp / 2) * Math.sin(dp / 2)
                + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
        return 2 * r * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

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
}
