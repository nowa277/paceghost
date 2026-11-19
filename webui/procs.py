"""托管子进程管理: face_watch.py 人脸守卫 / jrpos 桥接 (坑 #9 兜底).
   每设备一把锁, 日志落 webui/logs/, 进程生命周期由本模块独占管理.
   WebUI 重启后按命令行特征收养上一轮的孤儿进程 (按 --serial 归属设备), 防止双守卫."""
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "webui" / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
PY = "/usr/bin/python3"

_handles = {}  # kind:alias -> {"pid", "popen"|None, "log_path", "started_at", "target", "adopted"}
_lock = threading.Lock()


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _spawn(kind, alias, argv, log_name, meta):
    key = f"{kind}:{alias}"
    with _lock:
        h = _handles.get(key)
        if h and _alive(h["pid"]):
            return False, "already running"
        log_path = LOGS / log_name
        logf = open(log_path, "a", encoding="utf-8")
        try:
            p = subprocess.Popen(argv, cwd=str(BASE), stdout=logf, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
        finally:
            logf.close()
        _handles[key] = {"popen": p, "pid": p.pid, "log_path": str(log_path), "started_at": time.time(),
                         "target": meta.get("target", ""), "adopted": False, "kind": kind}
        return True, f"started pid={p.pid}"


def _kill_pid(pid, timeout=5):
    """按 pid 停进程 (含收养的孤儿); 对 start_new_session 的进程需杀进程组."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _alive(pid):
            return
        time.sleep(0.2)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _stop(kind, alias):
    key = f"{kind}:{alias}"
    with _lock:
        h = _handles.get(key)
        if not h:
            return True, "not running"
        pid = h["pid"]
        if _alive(pid):
            if h.get("popen"):
                try:
                    h["popen"].terminate()
                    h["popen"].wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _kill_pid(pid, timeout=3)
            else:
                _kill_pid(pid)
        del _handles[key]
        return True, f"stopped pid={pid}"


def _status(kind, alias):
    key = f"{kind}:{alias}"
    h = _handles.get(key)
    if not h:
        return {"running": False}
    alive = h["popen"].poll() is None if h.get("popen") else _alive(h["pid"])
    info = {"running": alive, "pid": h["pid"], "started_at": h["started_at"],
            "target": h["target"], "log_path": h["log_path"], "adopted": h.get("adopted", False)}
    info["log_tail"] = tail_file(h["log_path"], 15)
    return info


def tail_file(path, n=15):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def _cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def adopt_orphans(aliases):
    """启动时收养上一轮 WebUI 启动的守卫/桥进程.
       aliases: {alias: dev} 用于把 --serial 归属到设备; 归属不了的按 UNKNOWN 保留可停.
       返回收养数量."""
    import glob
    adopted = 0
    pids = []
    for f in glob.glob("/proc/[0-9]*/cmdline"):
        pid = int(f.split("/")[2])
        if pid == os.getpid():
            continue
        cmd = _cmdline(pid)
        if "face_watch.py" in cmd or "jrpos_bridge_local.py" in cmd:
            pids.append((pid, cmd))
    for pid, cmd in pids:
        kind = "guard" if "face_watch.py" in cmd else "bridge"
        target = ""
        if kind == "guard" and "--serial" in cmd:
            target = cmd.split("--serial", 1)[1].split()[0] if len(cmd.split("--serial", 1)[1].split()) else ""
        elif kind == "bridge":
            target = (cmd.split("jrpos_bridge_local.py", 1)[1].split() or [""])[0]
            # bridge 参数是 <port> <serial>, 取第二个词
            toks = cmd.split("jrpos_bridge_local.py", 1)[1].split()
            target = toks[1] if len(toks) > 1 else target
        alias = None
        for a, dev in aliases.items():
            if target and target in (dev.get("serial"), dev.get("wifi")):
                alias = a
                break
        key = f"{kind}:{alias or 'orphan'}"
        log_name = f"{kind}-{alias or 'orphan'}.log"
        with _lock:
            h = _handles.get(key)
            if h and _alive(h["pid"]):
                continue  # 已有活的托管实例, 跳过 (收养不了, 留给 reap 处理)
            _handles[key] = {"popen": None, "pid": pid, "log_path": str(LOGS / log_name),
                             "started_at": time.time(), "target": target, "adopted": True, "kind": kind}
        adopted += 1
        print(f"adopted orphan {key} pid={pid} target={target}", flush=True)
    return adopted


def guard_start(alias, target):
    argv = [PY, "-u", "-I", str(BASE / "scripts" / "face_watch.py"),
            "--serial", target, "--interval", "1.5"]
    return _spawn("guard", alias, argv, f"guard-{alias}.log", {"target": target})


def guard_stop(alias):
    return _stop("guard", alias)


def guard_status(alias):
    return _status("guard", alias)


def bridge_start(alias, target, port):
    argv = [PY, "-u", "-I", str(BASE / "webui" / "jrpos_bridge_local.py"), str(port), target]
    return _spawn("bridge", alias, argv, f"bridge-{alias}.log", {"target": target, "port": port})


def bridge_stop(alias):
    return _stop("bridge", alias)


def bridge_status(alias):
    return _status("bridge", alias)


def all_status():
    with _lock:
        keys = list(_handles.keys())
    out = {}
    for key in keys:
        kind, alias = key.split(":", 1)
        out.setdefault(alias, {})[kind] = _status(kind, alias)
    return out


def stop_all():
    """进程退出时清理 (不碰 RS/systemd, 只管自己起/收养的孩子)."""
    with _lock:
        keys = list(_handles.keys())
    for key in keys:
        kind, alias = key.split(":", 1)
        _stop(kind, alias)
