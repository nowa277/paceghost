"""jrpos 桥 — RS 实时坐标 -> Settings.Global.jrpos (GpsFeed 进程内注入读取)
   坑 #9 兜底: MagicOS 周期性拆 adb test provider, 但拆不掉 app 进程内 provider.
   用法: python3 jrpos_bridge_local.py <rs端口> <serial>"""
import json
import subprocess
import sys
import time
import urllib.request

PORT = sys.argv[1]
SER = sys.argv[2]
BASE = f"http://127.0.0.1:{PORT}"


def status():
    try:
        with urllib.request.urlopen(BASE + "/api/status", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


def put_jrpos(lat, lng):
    try:
        subprocess.run(["adb", "-s", SER, "shell",
                        f"settings put global jrpos {lat:.8f},{lng:.8f},5.0"],
                       capture_output=True, timeout=8)
        return True
    except Exception:
        return False


last = None
print(f"jrpos bridge -> {SER} (from RS :{PORT})", flush=True)
while True:
    st = status()
    cur = (st or {}).get("current") or {}
    lat, lng = cur.get("lat"), cur.get("lng")
    if lat is not None and lng is not None:
        if last != (lat, lng):
            put_jrpos(lat, lng)
            last = (lat, lng)
            print(f"[{time.strftime('%H:%M:%S')}] {lat:.6f},{lng:.6f}", flush=True)
    else:
        last = None
    time.sleep(0.45)
