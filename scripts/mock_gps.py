#!/usr/bin/env python3
"""
悦跑世界 免 root 假 GPS 注入器 (adb shell cmd location 路线)
原理: shell(uid 2000) 授权 appops mock_location 后可用 cmd location 注入 test provider

探测规避原理 (k/a.smali 实测):
  isMockLocationEnabled = AppOps(self) || any(getLastKnownLocation("gps"/"network").isFromMockProvider())
  -> remove-test-provider 后 lastKnown 被清空 => 探测返回 false
  -> re-add 后(未设位置) lastKnown 仍为 null => 探测继续通过
  -> app 已收到的 fix 在 Flutter 侧缓存, 开始按钮不受影响

用法:
  python3 mock_gps.py probe                 # 检查链路
  python3 mock_gps.py arm                   # 加 test provider (未设位置, 探测安全)
  python3 mock_gps.py feed LAT LON [ACC]    # 单点注入
  python3 mock_gps.py route LAT LON RADIUS LAP_METERS SPEED_MS
                                            # 环形轨迹播放
  python3 mock_gps.py disarm                # 拆除, 恢复手机
  python3 mock_gps.py dance                 # 探测规避舞蹈 (清 lastKnown 3 秒)
"""
import subprocess, sys, time, math

SERIAL = "10CD9D0FR0001JD"
PROVIDER = "gps"

def sh(cmd):
    r = subprocess.run(["adb", "-s", SERIAL, "shell", cmd],
                       capture_output=True, text=True, timeout=20)
    return r.stdout.strip(), r.returncode

def probe():
    print("== 1) adb 设备 ==")
    out, _ = sh("get-state"); print("  state:", out)
    print("== 2) appops mock_location (uid 2000) ==")
    out, _ = sh("appops get 2000 android:mock_location"); print("  ", out)
    print("== 3) test provider 是否已加 ==")
    out, rc = sh(f"cmd location providers set-test-provider-enabled {PROVIDER} true")
    print("  enable rc:", rc, out[:120])
    print("== 4) app 的 gps listener 注册 ==")
    out, _ = sh("dumpsys location")
    for line in out.splitlines():
        if "com.joyrunworld.app" in line and ("gps" in line or "registration" in line):
            print("  ", line.strip()[:130])

def arm():
    print("== 授权 shell mock_location ==")
    sh("appops set 2000 android:mock_location allow")
    print("== 加 test provider (不设位置 -> lastKnown=null, 探测安全) ==")
    out, rc = sh(f"cmd location providers add-test-provider {PROVIDER} "
                 "--requiresSatellite --supportsAltitude --supportsSpeed --supportsBearing")
    print("  add rc:", rc, out[:200])
    out, rc = sh(f"cmd location providers set-test-provider-enabled {PROVIDER} true")
    print("  enable rc:", rc, out[:200])

def feed(lat, lon, acc=5.0):
    out, rc = sh(f"cmd location providers set-test-provider-location {PROVIDER} "
                 f"--location {lat},{lon} --accuracy {acc}")
    return rc, out

def disarm():
    print("== 拆 test provider ==")
    out, rc = sh(f"cmd location providers remove-test-provider {PROVIDER}")
    print("  rc:", rc, out[:200])
    sh("appops set 2000 android:mock_location deny")
    print("== done ==")

def dance(hold=3.0):
    """清 lastKnown -> 探测窗口 -> 恢复 provider (app 收不到 fix 的空窗)"""
    sh(f"cmd location providers remove-test-provider {PROVIDER}")
    time.sleep(hold)
    sh(f"cmd location providers add-test-provider {PROVIDER} "
       "--requiresSatellite --supportsAltitude --supportsSpeed --supportsBearing")
    sh(f"cmd location providers set-test-provider-enabled {PROVIDER} true")
    print(f"[dance] lastKnown cleared for {hold}s, provider re-armed (no fix yet)")

def route(lat0, lon0, radius_m=200, lap_m=800, speed=3.0, acc=5.0):
    """以 (lat0,lon0) 为圆心跑环形轨迹, lap_m 米/圈, speed m/s"""
    # 圈数 = lap_m / (2*pi*radius) 至少 1
    circ = 2 * math.pi * radius_m
    laps = max(1, round(lap_m / circ))
    total_m = circ * laps
    total_s = total_m / speed
    print(f"[route] center=({lat0},{lon0}) r={radius_m}m laps={laps} total={total_m:.0f}m "
          f"~{total_s/60:.1f}min @ {speed}m/s")
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
    step_s = 1.0
    t = 0.0
    n = int(total_s / step_s)
    start = time.time()
    for i in range(n):
        frac = (i * speed * step_s) / circ          # 圈内弧长比例
        ang = 2 * math.pi * frac
        # 顺时针沿跑道
        dlat = (radius_m * math.sin(ang)) / m_per_deg_lat
        dlon = (radius_m * math.cos(ang)) / m_per_deg_lon
        la, lo = lat0 + dlat, lon0 + dlon
        rc, out = feed(la, lo, acc)
        if rc != 0:
            print(f"  ! feed fail @{i}: {out[:120]}")
        if i % 30 == 0:
            el = time.time() - start
            print(f"  [{el:6.0f}s] {(i*speed*step_s):7.0f}m  ({la:.6f},{lo:.6f})")
        time.sleep(max(0.0, step_s - (time.time() - start - i * step_s)))
    print(f"[route] done {total_m:.0f}m in {time.time()-start:.0f}s")

if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if a == "probe": probe()
    elif a == "arm": arm()
    elif a == "feed": feed(float(sys.argv[2]), float(sys.argv[3]),
                           float(sys.argv[4]) if len(sys.argv) > 4 else 5.0)
    elif a == "route":
        route(float(sys.argv[2]), float(sys.argv[3]),
              float(sys.argv[4]) if len(sys.argv) > 4 else 200,
              float(sys.argv[5]) if len(sys.argv) > 5 else 800,
              float(sys.argv[6]) if len(sys.argv) > 6 else 3.0)
    elif a == "dance": dance(float(sys.argv[2]) if len(sys.argv) > 2 else 3.0)
    elif a == "disarm": disarm()
    else: print(__doc__)
