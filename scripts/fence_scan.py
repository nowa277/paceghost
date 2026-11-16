#!/usr/bin/env python3
"""悦跑世界 电子围栏扫描器: 网格喂 mock 点 -> 按钮像素分类 蓝=在围栏内"""
import subprocess, sys, time, struct

SERIAL = "10CD9D0FR0001JD"
BTN = (538, 824)   # 开始跑步 按钮圆心 (native 1080x2388)

def sh(cmd, timeout=15):
    return subprocess.run(["adb", "-s", SERIAL, "shell", cmd],
                          capture_output=True, text=True, timeout=timeout).stdout.strip()

def feed(lat, lon, acc=5.0):
    sh(f"cmd location providers set-test-provider-location gps --location {lat},{lon} --accuracy {acc}")

def pixel(x, y):
    raw = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap"],
                         capture_output=True, timeout=15).stdout
    w, h = struct.unpack("<II", raw[:8])
    off = 16 + (y * w + x) * 4   # header: w,h,format,colorspace
    r, g, b = raw[off], raw[off+1], raw[off+2]
    return r, g, b

def in_fence():
    r, g, b = pixel(*BTN)
    return b > 150 and b > r + 40   # 蓝色按钮 / 灰色按钮

def scan(lat0, lat1, lon0, lon1, nlat, nlon, settle=1.6):
    out = []
    for i in range(nlat):
        lat = lat0 + (lat1 - lat0) * i / (nlat - 1)
        row = []
        for j in range(nlon):
            lon = lon0 + (lon1 - lon0) * j / (nlon - 1)
            feed(lat, lon)
            time.sleep(settle)
            ok = in_fence()
            row.append(ok)
            print(f"  ({lat:.5f},{lon:.5f}) -> {'IN ' if ok else 'out'}", flush=True)
        out.append((lat, row))
    return out

if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "cal"
    if a == "cal":
        print("current btn px:", pixel(*BTN), "in_fence:", in_fence())
    elif a == "scan":
        # 7x7 over campus bbox
        res = scan(22.9195, 22.9297, 113.8560, 113.8650, 7, 7)
        print("\n=== MASK (rows=lat desc? lat asc top->bottom, cols lon asc) ===")
        for lat, row in res:
            print(f"{lat:.5f} " + "".join("#" if x else "." for x in row))

def scan2(lat0, lat1, lon0, lon1, nlat, nlon):
    """tab-switch 复位法: 每个点独立评估 (避开 进围栏锁存)"""
    import subprocess
    S = SERIAL
    def tap(x, y):
        subprocess.run(["adb","-s",S,"shell","input","tap",str(x),str(y)])
    res = []
    for i in range(nlat):
        lat = lat0 + (lat1-lat0)*i/(nlat-1)
        row = []
        for j in range(nlon):
            lon = lon0 + (lon1-lon0)*j/(nlon-1)
            tap(917,2290); time.sleep(1.6)   # 我的
            tap(540,2290); time.sleep(1.6)   # 运动 -> 定位中
            feed(lat, lon); time.sleep(2.6)  # 首帧 fix -> 围栏评估
            ok = in_fence()
            row.append(ok)
            print(f"  ({lat:.5f},{lon:.5f}) -> {'IN ' if ok else 'out'}", flush=True)
        res.append((lat,row))
    return res
