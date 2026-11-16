#!/usr/bin/env python3
"""GPS 注入桥 — 两路线自动切换

路线 A (vivo / 原生 ROM): ADB test-provider  (Route Studio 原生支持)
路线 B (华为 EMUI 等):     进程内注入, PC 只写 Settings.Global.jrpos

用法:
  gpsbridge.py serve [--serial X] [--speed 13.33] [--loop] [--sink adb|settings]
  gpsbridge.py point LAT LON [--serial X]        # 单点写一次 (settings 路线)
  gpsbridge.py probe [--serial X]                # 检测该机支持哪条路线
  gpsbridge.py off   [--serial X]                # 关注入 + 拆 provider

设置的 settings 键 (路线 B):
  jrpos        "lat,lon,accuracy"
  jrgps_feed   1/0
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
import urllib.request

API = "http://127.0.0.1:8765/api/status"
SETTINGS_FILE = os.path.expanduser("~/.ios-location-controller/session.json")


def pick_serial(explicit=None):
    if explicit:
        return explicit
    try:
        out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    live = [l.split()[0] for l in out.splitlines()[1:] if "\tdevice" in l]
    usb = [s for s in live if ":" not in s]
    return usb[0] if usb else (live[0] if live else None)


def adb(serial, *args, timeout=25):
    serial = serial or pick_serial()
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += ["shell", *args]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def probe(serial):
    """返回 'testprovider' | 'settings'"""
    out = adb(serial, "cmd", "location", "help")
    if "set-test-provider-location" in out:
        return "testprovider"
    return "settings"


def push_settings(serial, lat, lon, acc=5.0):
    adb(serial, "settings", "put", "global", "jrpos", f"{lat:.8f},{lon:.8f},{acc:.1f}")


def load_route():
    """优先用 Route Studio 的当前路线, 退化到 session.json"""
    try:
        d = json.load(urllib.request.urlopen(API, timeout=5))
        pts = (d.get("route") or {}).get("points") or []
        if pts:
            return [(p["lat"], p["lng"]) for p in pts], (d.get("route") or {}).get("name")
    except Exception:
        pass
    try:
        d = json.load(open(SETTINGS_FILE))
        pts = d.get("points") or []
        if pts:
            return [(p["lat"], p["lng"]) for p in pts], d.get("name")
    except Exception:
        pass
    return [], None


def haversine(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def serve(serial, speed_kmh, loop, mode):
    pts, name = load_route()
    if len(pts) < 2:
        print("没有路线点, 先在 Route Studio 画路线", file=sys.stderr)
        return 1
    print(f"路线 {name or '(未命名)'} {len(pts)} 点")
    print(f"注入路线: {mode} ({serial or 'auto'})  {speed_kmh}km/h  loop={loop}")

    adb(serial, "settings", "put", "global", "jrgps_feed", "1")
    total = sum(haversine(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    print(f"单圈 {total:.1f}m")

    seg = 0
    frac = 0.0
    laps = 0
    step_m = speed_kmh * 1000 / 3600 * 0.5   # 0.5s 周期
    try:
        while True:
            nxt = (seg + 1) % len(pts)
            d = haversine(pts[seg], pts[nxt])
            if d <= 0:
                seg = nxt
                continue
            frac += step_m / d
            while frac >= 1.0:
                frac -= 1.0
                seg = nxt
                nxt = (seg + 1) % len(pts)
                if seg == 0:
                    laps += 1
                    if not loop:
                        print(f"完成 {laps} 圈, 停")
                        return 0
                d = haversine(pts[seg], pts[nxt])
                if d <= 0:
                    break
            a, b = pts[seg], pts[nxt]
            lat = a[0] + (b[0] - a[0]) * frac
            lon = a[1] + (b[1] - a[1]) * frac
            push_settings(serial, lat, lon)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n停")
        return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve")
    s.add_argument("--serial")
    s.add_argument("--speed", type=float, default=13.33)
    s.add_argument("--loop", action="store_true", default=True)
    s.add_argument("--no-loop", dest="loop", action="store_false")

    p = sub.add_parser("point")
    p.add_argument("lat", type=float)
    p.add_argument("lon", type=float)
    p.add_argument("--acc", type=float, default=5.0)
    p.add_argument("--serial")

    pr = sub.add_parser("probe")
    pr.add_argument("--serial")

    o = sub.add_parser("off")
    o.add_argument("--serial")

    a = ap.parse_args()

    if a.cmd == "probe":
        m = probe(a.serial)
        print(f"route = {m}")
        print("testprovider" if m == "testprovider" else "settings (需模块 jrgps_feed=1)")
        return 0
    if a.cmd == "point":
        push_settings(a.serial, a.lat, a.lon, a.acc)
        adb(a.serial, "settings", "put", "global", "jrgps_feed", "1")
        print("已注入", adb(a.serial, "settings", "get", "global", "jrpos"))
        return 0
    if a.cmd == "off":
        adb(a.serial, "settings", "put", "global", "jrgps_feed", "0")
        adb(a.serial, "settings", "delete", "global", "jrpos")
        for prov in ("gps", "network"):
            adb(a.serial, "cmd", "location", "providers", "remove-test-provider", prov)
        print("已关闭")
        return 0
    if a.cmd == "serve":
        return serve(a.serial, a.speed, a.loop, probe(a.serial))
    return 1


if __name__ == "__main__":
    sys.exit(main())
