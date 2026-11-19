"""一键流水线: 通道解析 -> 预置 -> 推人脸 -> RS connect -> settings -> start -> 守卫.
   单设备作用域: 绝不动其他实例端口 (与 joyrun_switch.sh 的差异点)."""
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import adbtools, procs, store

RS_TIMEOUT = 15
_locks = {}
_active = set()  # 正在执行流水线的 alias (busy 标记)
_last_pipeline = {}  # alias -> {alias, kind, ok, steps[], started_at, finished_at, error}
_lk = threading.Lock()

FACE_TMP = Path("/tmp/webui_face")


def rs_call(port, path, body=None, timeout=RS_TIMEOUT):
    url = f"http://127.0.0.1:{port}/api/{path}"
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def rs_status(port, timeout=4):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def is_busy(alias):
    with _lk:
        return alias in _active


def _lock_for(alias):
    with _lk:
        return _locks.setdefault(alias, threading.Lock())


def _wait_not_playing(port, timeout=8):
    """confirm 停播后等 RS 状态机真正离开 playing (轮询而非盲等)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = rs_status(port, timeout=3)
        if st and st.get("state") != "playing":
            return st
        time.sleep(0.5)
    return rs_status(port, timeout=3)


def _record(alias, kind, ok, steps, error=""):
    rec = {"alias": alias, "kind": kind, "ok": ok, "steps": steps, "error": error,
           "started_at": time.time(), "finished_at": time.time()}
    with _lk:
        _last_pipeline[alias] = rec
    return rec


def resolve_channel(alias, dev):
    """USB 优先 -> WiFi 在线 -> adb connect 唤醒 WiFi 通道. 返回 (target, via, notes)."""
    notes = []
    serial, wifi = dev["serial"], dev.get("wifi") or ""
    if adbtools.get_state(serial):
        return serial, "USB", notes
    notes.append(f"USB({serial}) 不在线")
    if wifi and adbtools.get_state(wifi):
        return wifi, f"WiFi({wifi})", notes
    if wifi:
        ok, text = adbtools.connect_wifi(wifi)
        notes.append(f"adb connect {wifi}: {text[:120]}")
        time.sleep(1.0)
        if adbtools.get_state(wifi):
            return wifi, f"WiFi({wifi})", notes
        notes.append("WiFi 通道仍不可达")
    raise RuntimeError(f"{alias} 不在线: USB({serial}) 和 WiFi({wifi or '未配置'}) 都不通")


def push_face(target, face_path):
    """复刻 face_set.sh: magick 1080x1920 JPEG -> adb push. 返回 (ok, detail)."""
    if not face_path:
        return True, "未配置人脸图, 跳过"
    src = Path(face_path)
    if not src.is_file():
        return False, f"人脸图不存在: {face_path}"
    FACE_TMP.mkdir(exist_ok=True)
    out = FACE_TMP / "face_use.jpg"
    try:
        r = subprocess.run(["/usr/bin/magick", str(src), "-auto-orient",
                            "-resize", "1080x1920^", "-gravity", "center",
                            "-extent", "1080x1920", "-strip", "-quality", "92", str(out)],
                           capture_output=True, timeout=60)
        if r.returncode != 0:
            return False, "magick 处理失败: " + r.stderr.decode(errors="replace")[:150]
        rc, o = adbtools.shell(target, "mkdir", "-p",
                               "/sdcard/Android/data/com.joyrunworld.app/files", timeout=15)
        r2 = subprocess.run([adbtools.ADB, "-s", target, "push", str(out),
                             "/sdcard/Android/data/com.joyrunworld.app/files/face_use.jpg"],
                            capture_output=True, timeout=60)
        if r2.returncode != 0:
            return False, "adb push 失败: " + r2.stderr.decode(errors="replace")[:150]
        rc, size = adbtools.shell(target, "stat", "-c", "%s",
                                  "/sdcard/Android/data/com.joyrunworld.app/files/face_use.jpg", timeout=15)
        return True, f"已推送 face_use.jpg ({(size or '').strip()} B, 源 {src.name})"
    finally:
        out.unlink(missing_ok=True)


def run_pipeline(alias, confirm=False, start=True):
    """一键开跑. RS state=playing/error 时需 confirm=True (前端显式确认). 返回 pipeline 记录."""
    lk = _lock_for(alias)
    if not lk.acquire(blocking=False):
        return {"ok": False, "error": "该设备的流水线正在执行中"}
    with _lk:
        _active.add(alias)
    steps = []
    try:
        dev = store.get(alias)

        def step(name, ok, detail=""):
            steps.append({"step": name, "ok": bool(ok), "detail": str(detail)[:220]})

        try:
            target, via, notes = resolve_channel(alias, dev)
            step("通道解析", True, f"target={target} via={via}" + ("; " + "; ".join(notes) if notes else ""))
        except RuntimeError as e:
            step("通道解析", False, str(e))
            return _finish(_record(alias, "run", False, steps, str(e)))

        st = rs_status(dev["port"])
        if st and st.get("state") == "playing" and not confirm:
            rec = _finish(_record(alias, "run", False, steps,
                                  "RS 实例正在播放 (state=playing), 请在 UI 确认后重试 (confirm)"))
            rec["confirm_required"] = True
            return rec
        if st and st.get("state") == "error" and not confirm:
            rec = _finish(_record(alias, "run", False, steps,
                                  "RS 实例处于 error (设备掉线/注入被拆)。一键开跑会重连覆盖现场, 需 UI 确认 (confirm)"))
            rec["confirm_required"] = True
            return rec
        if st and st.get("state") == "playing" and confirm:
            rs_call(dev["port"], "stop")
            st = _wait_not_playing(dev["port"])
            step("先停旧播放", st.get("state") != "playing" if st else False,
                 f"confirm=true, stop 后 state={(st or {}).get('state')}")

        for name, ok, detail in adbtools.preset(target, dev):
            step(name, ok, detail)

        ok, detail = push_face(target, dev.get("face"))
        step("人脸图推送", ok, detail)
        if not ok:
            step("人脸图推送(继续)", True, "推送失败不影响连接, 可稍后手动 face_set.sh 补")

        if target == dev["serial"]:
            body = {"platform": "android", "udid": dev["serial"]}
        else:
            body = {"platform": "android", "address": dev["wifi"]}
        r = rs_call(dev["port"], "connect", body, timeout=40)
        mode = (r.get("diagnostics") or {}).get("mode")
        step("RS connect", not r.get("error"), f"port={dev['port']} mode={mode} err={r.get('error') or 'ok'}")
        if r.get("error"):
            return _finish(_record(alias, "run", False, steps, f"connect 失败: {r.get('error')}"))

        s = dev
        r = rs_call(dev["port"], "settings", {
            "speed_kmh": float(s.get("speed_kmh", 13.33)), "interval": 1.0,
            "speed_variation_pct": 3.0, "lateral_variation_m": 1.5,
            "variation_period": 10.0, "loop": True, "random_seed": 14})
        step("RS settings 整包", not r.get("error"),
             f"speed={s.get('speed_kmh')} err={r.get('error') or 'ok'}")

        gok, gmsg = procs.guard_start(alias, target)
        step("人脸守卫", True, f"{gmsg} (interval=1.5s)")

        if start:
            r = rs_call(dev["port"], "start")
            step("RS start", not r.get("error"), f"err={r.get('error') or 'ok'}")
            if r.get("error"):
                return _finish(_record(alias, "run", False, steps, f"start 失败: {r.get('error')}"))

        st2 = rs_status(dev["port"])
        step("最终状态", True,
             f"state={st2.get('state')} 里程={st2.get('total_m')}m 路线={(st2.get('route') or {}).get('name') or '-'}")
        return _finish(_record(alias, "run", True, steps))
    except Exception as e:
        return _finish(_record(alias, "run", False, steps, f"{type(e).__name__}: {e}"))
    finally:
        with _lk:
            _active.discard(alias)
        lk.release()


def stop_pipeline(alias, confirm=False, disconnect=True):
    """停守卫+停播放+断连 (runbook §5). state=playing/error 时需 confirm."""
    lk = _lock_for(alias)
    if not lk.acquire(blocking=False):
        return {"ok": False, "error": "该设备的流水线正在执行中"}
    with _lk:
        _active.add(alias)
    steps = []
    try:
        dev = store.get(alias)
        st = rs_status(dev["port"])

        def step(name, ok, detail=""):
            steps.append({"step": name, "ok": bool(ok), "detail": str(detail)[:220]})

        gs, gmsg = procs.guard_stop(alias)
        step("人脸守卫", gs, gmsg)
        procs.bridge_stop(alias)
        step("jrpos 桥", True, "stopped (若有)")

        if st is None:
            step("RS 实例", False, f"端口 {dev['port']} 不可达, 仅停了守卫")
        elif st.get("state") in ("playing", "paused") and not confirm:
            rec = _finish(_record(alias, "stop", False, steps,
                                  "正在播放, 前端须先弹确认 (confirm=true)"))
            rec["confirm_required"] = True
            return rec
        elif st.get("state") == "error" and not confirm:
            rec = _finish(_record(alias, "stop", False, steps,
                                  "RS 处于 error 态, 未经确认不动 RS (避免清掉错误现场); 仅停了守卫/桥"))
            rec["confirm_required"] = True
            return rec
        elif st.get("state") == "error" and confirm:
            step("RS stop(尽力)", False, "error 态, 跳过 pause/stop, 仅尝试 disconnect")
            r = rs_call(dev["port"], "disconnect")
            step("RS disconnect", not r.get("error"), r.get("error") or "ok")
        else:
            r = rs_call(dev["port"], "pause")
            step("RS pause", not r.get("error"), r.get("error") or "ok")
            r = rs_call(dev["port"], "stop")
            step("RS stop", not r.get("error"), r.get("error") or "ok")
            time.sleep(1.0)
            if disconnect:
                st2 = rs_status(dev["port"])
                if st2 and st2.get("state") == "playing":
                    step("RS disconnect", False, "stop 后仍在播放, 跳过 disconnect (防误伤)")
                else:
                    r = rs_call(dev["port"], "disconnect")
                    step("RS disconnect", not r.get("error"), r.get("error") or "ok")
        st3 = rs_status(dev["port"])
        step("最终状态", True, f"state={(st3 or {}).get('state')}")
        return _finish(_record(alias, "stop", True, steps))
    except Exception as e:
        return _finish(_record(alias, "stop", False, steps, f"{type(e).__name__}: {e}"))
    finally:
        with _lk:
            _active.discard(alias)
        lk.release()


def _finish(rec):
    rec["finished_at"] = time.time()
    return rec


def last_pipeline(alias):
    with _lk:
        return _last_pipeline.get(alias)
