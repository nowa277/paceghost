"""adb 层封装: 设备列表解析 / 通道探测 / shell 命令. 全部参数列表调用, 不用 shell=True."""
import os
import subprocess
import threading

ADB = os.environ.get("WEBUI_ADB", "/home/sesley/.local/bin/adb")
PKG = "com.joyrunworld.app"
_local = threading.local()


def _run(args, timeout=15, binary=False):
    try:
        r = subprocess.run([ADB, *args], capture_output=True, timeout=timeout)
        if binary:
            return r.returncode, r.stdout, r.stderr
        out = r.stdout.decode("utf-8", "replace")
        err = r.stderr.decode("utf-8", "replace")
        return r.returncode, out, err
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "adb not found"


def parse_devices():
    """adb devices -l -> [{serial, state, model, usb, transport_id}]."""
    rc, out, _ = _run(["devices", "-l"], timeout=10)
    if rc != 0:
        return []
    devs = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        info = {"serial": serial, "state": state, "model": "", "usb": "", "transport_id": ""}
        for kv in parts[2:]:
            if ":" in kv:
                k, _, v = kv.partition(":")
                if k in ("model", "usb", "transport_id"):
                    info[k] = v
        devs.append(info)
    return devs


def online_serials():
    return {d["serial"] for d in parse_devices() if d["state"] == "device"}


def get_state(target):
    rc, _, _ = _run(["-s", target, "get-state"], timeout=8)
    return rc == 0


def connect_wifi(addr, timeout=10):
    rc, out, err = _run(["connect", addr], timeout=timeout)
    text = (out + err).strip()
    ok = rc == 0 and ("connected" in text and "cannot" not in text.lower() and "failed" not in text.lower())
    return ok, text


def shell(target, *args, timeout=20):
    """adb -s <target> shell <args>; 返回 (rc, stdout)."""
    return _run(["-s", target, "shell", *args], timeout=timeout)[:2]


def shell_ok(target, *args, timeout=20):
    rc, _ = shell(target, *args, timeout=timeout)
    return rc == 0


def get_model(target):
    for d in parse_devices():
        if d["serial"] == target:
            return d["model"]
    return ""


# ---- 设备预置 (与 joyrun_switch.sh 等价, 单设备作用域) ----

def preset(target, dev):
    """返回 [(step_name, ok, detail)]"""
    steps = []

    def sh(name, ok, detail=""):
        steps.append((name, ok, detail.strip()[:200]))

    rc, out = shell(target, "appops", "set", PKG, "android:mock_location", "allow")
    sh("appops mock_location allow", rc == 0, out)
    # vivo 类 ROM WiFi 重连后定位总开关被重置, 无条件幂等补开; 华为 cmd location 被裁剪报非零, 吞掉
    rc, out = shell(target, "cmd", "location", "set-location-enabled", "true")
    sh("cmd location set-location-enabled", True, "ok" if rc == 0 else "cmd location unavailable (吞错)")
    if dev.get("mode") == "settings":
        # 华为 EMUI: cmd location 整体被裁, 用 settings 定位主开关 (RUNBOOK §9)
        rc, out = shell(target, "settings", "put", "secure", "location_mode", "3")
        sh("settings secure location_mode 3", rc == 0, out)
    rc, out = shell(target, "settings", "put", "global", "jrstep_cadence", str(int(dev.get("cadence", 131))))
    sh("jrstep_cadence", rc == 0, out)
    rc, out = shell(target, "settings", "put", "global", "jrstep_on", "1")
    sh("jrstep_on", rc == 0, out)
    rc, out = shell(target, "settings", "put", "global", "jrface_on", "1")
    sh("jrface_on", rc == 0, out)
    shell(target, "settings", "put", "global", "jrgps_feed", "0")
    shell(target, "settings", "delete", "global", "jrpos")
    sh("清 jrgps_feed/jrpos 残留", True)
    sh("device identity (jrdevice)", *device_identity(target, dev.get("jrdevice")))
    return steps


def device_identity(target, want_jrdevice=None):
    """坑 #11 固化: jrdevice_rand 归 0 (幂等无害).
       jrdevice 写入是 OPT-IN: 仅当 devices.json 显式配置了 jrdevice 字段且设备当前值为空时才写,
       绝不覆盖已有值, 也绝不在未配置时凭空生成 —— 否则等于改设备标识, 反而触发坑 #11.
       返回 (ok, detail)."""
    rc, cur = shell(target, "settings", "get", "global", "jrdevice")
    cur = (cur or "").strip()
    shell(target, "settings", "put", "global", "jrdevice_rand", "0")
    if cur not in ("", "null"):
        if want_jrdevice and want_jrdevice != cur:
            return True, f"keep existing jrdevice={cur} (registry 配置 {want_jrdevice} 不一致, 未覆盖), rand=0"
        return True, f"keep existing jrdevice={cur}, rand=0"
    if want_jrdevice:
        rc1, o1 = shell(target, "settings", "put", "global", "jrdevice", want_jrdevice)
        return rc1 == 0, f"set jrdevice={want_jrdevice} (registry 配置), rand=0"
    return True, "jrdevice 未设置且 registry 未配置, 保持原样 (rand=0)"


def module_log_tail(target, lines=30):
    rc, out = shell(target, "tail", "-n", str(lines),
                    "/sdcard/Android/data/com.joyrunworld.app/files/jrpatch.log", timeout=15)
    return out if rc == 0 else f"(读取失败: {out.strip()[:120]})"
