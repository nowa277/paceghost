#!/usr/bin/env python3
"""按目标步幅自动把 Route Studio 速度 -> 计步 cadence 同步到手机
用法: stride_sync.py [目标步幅cm, 默认175] [目标速度km/h 可选] [--serial X]
公式: cadence = speed_kmh*1000/60 / (stride_cm/100)
"""
import argparse
import json
import subprocess
import urllib.request

API = "http://127.0.0.1:8765/api/status"


def pick_serial(explicit=None):
    if explicit:
        return explicit
    try:
        out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    live = [l.split()[0] for l in out.splitlines()[1:] if "\tdevice" in l]
    # 优先 USB (无冒号), 其次唯一那台
    usb = [s for s in live if ":" not in s]
    if usb:
        return usb[0]
    return live[0] if live else None


def adb(serial, *a):
    cmd = ["adb"] + (["-s", serial] if serial else []) + ["shell", *a]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stride", nargs="?", type=float, default=175.0)
    ap.add_argument("speed", nargs="?", type=float)
    ap.add_argument("--serial")
    a = ap.parse_args()

    serial = pick_serial(a.serial)
    if not serial:
        raise SystemExit("没有可用 adb 设备")

    try:
        st = json.load(urllib.request.urlopen(API, timeout=5))
        speed = a.speed if a.speed else float(st["settings"]["speed_kmh"])
    except Exception:
        if not a.speed:
            raise SystemExit("Route Studio 没在跑, 请显式给速度: stride_sync.py 175 13.33")
        speed = a.speed

    cad = speed * 1000 / 60 / (a.stride / 100.0)
    cad = int(round(cad))
    adb(serial, "settings", "put", "global", "jrstep_cadence", str(cad))
    adb(serial, "settings", "put", "global", "jrstep_on", "1")

    pace_s = 3600 / speed if speed else 0
    print(f"{serial} | 速度 {speed} km/h ({int(pace_s // 60)}'{int(pace_s % 60):02d}\"/km)"
          f" | 目标步幅 {a.stride:.0f}cm -> cadence {cad}/min")
    print("手机实测:", adb(serial, "settings", "get", "global", "jrstep_cadence"))


if __name__ == "__main__":
    main()
