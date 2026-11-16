#!/usr/bin/env python3
"""人脸验证弹窗守卫: 检测到"本人验证"弹窗 -> 立刻点"确定" -> 回读模块日志

用法:
  face_watch.py                    # 一直守着, Ctrl-C 停 (自动选设备)
  face_watch.py --serial X         # 指定设备
  face_watch.py --once             # 只查一次当前状态
"""
import argparse
import re
import subprocess
import sys
import time

LOG = "/sdcard/Android/data/com.joyrunworld.app/files/jrpatch.log"
TXT_VERIFY = "本人验证"
DESC_CONFIRM = "确定"

_serial_cache = None


def pick_serial():
    global _serial_cache
    if _serial_cache:
        return _serial_cache
    try:
        out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    live = [l.split()[0] for l in out.splitlines()[1:] if "\tdevice" in l]
    usb = [s for s in live if ":" not in s]
    _serial_cache = usb[0] if usb else (live[0] if live else None)
    return _serial_cache


def adb(*args, timeout=25):
    base = ["adb"]
    s = pick_serial()
    if s:
        base += ["-s", s]
    try:
        r = subprocess.run(base + list(args), capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def dump_ui():
    adb("shell", "uiautomator", "dump", "/sdcard/ui_face.xml")
    return adb("shell", "cat", "/sdcard/ui_face.xml")


def parse_nodes(xml):
    out = []
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        txt = re.search(r'text="([^"]*)"', tag)
        desc = re.search(r'content-desc="([^"]*)"', tag)
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bounds:
            continue
        x1, y1, x2, y2 = map(int, bounds.groups())
        out.append({
            "text": txt.group(1) if txt else "",
            "desc": desc.group(1) if desc else "",
            "center": ((x1 + x2) // 2, (y1 + y2) // 2),
        })
    return out


def find_dialog(nodes):
    hit_verify = any(TXT_VERIFY in (n["text"] + n["desc"]) for n in nodes)
    confirm = None
    for n in nodes:
        if n["desc"] == DESC_CONFIRM or n["text"] == DESC_CONFIRM:
            if confirm is None or n["center"][1] > confirm["center"][1]:
                confirm = n
    return hit_verify, confirm


def tail_log(n=8):
    t = adb("shell", "cat", LOG)
    if not t or "No such file" in t:
        return "(无日志)"
    lines = [l for l in t.splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--no-tap", action="store_true")
    ap.add_argument("--serial")
    args = ap.parse_args()

    global _serial_cache
    if args.serial:
        _serial_cache = args.serial

    if not pick_serial():
        print("没有可用 adb 设备", file=sys.stderr)
        return 1

    print(f"守卫已启动 (设备 {pick_serial()}), 轮询 {args.interval}s/次")
    taps = 0
    idle = 0
    while True:
        nodes = parse_nodes(dump_ui())
        is_face, confirm = find_dialog(nodes)

        if is_face and confirm:
            cx, cy = confirm["center"]
            print(f"[{time.strftime('%H:%M:%S')}] 检测到本人验证弹窗 -> 点确定 @ ({cx},{cy})")
            if not args.no_tap:
                adb("shell", "input", "tap", str(cx), str(cy))
                taps += 1
                time.sleep(2.0)
                print("  模块日志尾部:")
                for line in tail_log(6).splitlines():
                    print("   " + line)
            if args.once:
                return 0
            idle = 0
        else:
            idle += 1
            if idle % 20 == 0:
                print(f"[{time.strftime('%H:%M:%S')}] 待命中... 已点 {taps} 次")
            if args.once:
                print("当前无本人验证弹窗")
                return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已停止")
