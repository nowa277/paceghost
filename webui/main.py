"""paceghost WebUI — RS 之上的多机管理层 (纯 stdlib, 零依赖).

启动: 在仓库根目录执行  python3 -m webui.main --port 8800
仅监听 127.0.0.1; 不改 mockrunning, 不碰 systemd, 不动其他在跑实例.
"""
import argparse
import base64
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import adbtools, procs, runner, store

STATIC = Path(__file__).parent / "static"
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_events = []
_events_lock = threading.Lock()
_seq = 0


def log_event(alias, kind, text, ok=True):
    global _seq
    with _events_lock:
        _seq += 1
        _events.append({"seq": _seq, "ts": time.time(),
                        "alias": alias, "kind": kind, "ok": ok, "text": text[:400]})
        del _events[:-500]


def overview():
    registry = store.load()
    devices = [v for k, v in registry.items() if not k.startswith("_")]
    adb_list = adbtools.parse_devices()
    by_serial = {d["serial"]: d for d in adb_list}

    def fetch_one(alias, dev):
        st = runner.rs_status(dev["port"], timeout=3)
        d = {"alias": alias, **{k: dev.get(k) for k in
                                ("serial", "wifi", "port", "mode", "cadence", "speed_kmh", "face")},
             "face_mtime": store.face_mtime(dev.get("face")),
             "channel": None, "rs": None}
        serial, wifi = dev["serial"], dev.get("wifi") or ""
        usb = by_serial.get(serial)
        wifid = by_serial.get(wifi)
        if usb and usb["state"] == "device":
            d["channel"] = {"target": serial, "via": "USB", "model": usb["model"], "state": "device"}
        elif wifid and wifid["state"] == "device":
            d["channel"] = {"target": wifi, "via": "WiFi", "model": wifid["model"], "state": "device"}
        else:
            d["channel"] = {"target": serial, "via": "offline", "model": "", "state": "offline"}
        if st:
            d["rs"] = {"reachable": True, "state": st.get("state"), "connected": st.get("connected"),
                       "platform": st.get("platform"), "udid": st.get("udid"), "error": st.get("error"),
                       "current": st.get("current"), "distance_m": st.get("distance_m"),
                       "elapsed_s": st.get("elapsed_s"), "total_m": st.get("total_m"),
                       "laps": st.get("laps"), "settings": st.get("settings"),
                       "route_name": (st.get("route") or {}).get("name"),
                       "mode": ((st.get("diagnostics") or {}) or {}).get("mode")}
        else:
            d["rs"] = {"reachable": False, "state": "unreachable", "connected": False,
                       "error": f"端口 {dev['port']} 无响应 (systemctl --user route-studio@{alias})"}
        d["guard"] = procs.guard_status(alias)
        d["bridge"] = procs.bridge_status(alias)
        d["pipeline"] = runner.last_pipeline(alias)
        d["busy"] = runner.is_busy(alias)
        return d

    with ThreadPoolExecutor(max_workers=8) as ex:
        cards = list(ex.map(lambda kv: fetch_one(*kv), [(k, v) for k, v in registry.items() if not k.startswith("_")]))

    known = set()
    for d in devices:
        known.add(d["serial"])
        if d.get("wifi"):
            known.add(d["wifi"])
    unregistered = []
    for d in adb_list:
        if d["serial"] in known:
            continue
        if ":" in d["serial"]:
            base_ip = d["serial"].split(":")[0]
            if any(w and w.startswith(base_ip + ":") for w in known):
                continue
        unregistered.append({"serial": d["serial"], "state": d["state"],
                             "model": d["model"], "usb": d["usb"]})
    return {"devices": cards, "unregistered": unregistered,
            "server_time": time.time()}


def save_face(payload):
    """换人脸: base64 上传 -> work/face/ 落盘 -> magick -> push -> devices.json 更新.
       alias 或 serial 二选一; serial 能从 devices.json 匹配到设备时自动归档, 匹配不到则仅推图."""
    alias = payload.get("alias")
    serial = str(payload.get("serial") or "")
    registry = store.load()
    if not alias and serial:
        for a, dev in registry.items():
            if a.startswith("_"):
                continue
            if dev["serial"] == serial:
                alias = a
                break
            if dev.get("wifi") and serial.startswith(dev["wifi"].split(":")[0] + ":"):
                alias = a
                break
    dev = registry.get(alias) if alias and not alias.startswith("_") else None
    name = str(payload.get("filename") or "upload.png")
    stem, dot, ext = name.rpartition(".")
    stem = stem or name
    ext = (ext or "png").lower()
    if not SAFE_NAME.match(stem) or ext not in ("png", "jpg", "jpeg"):
        raise ValueError("文件名须为 ASCII snake_case, 后缀 png/jpg")
    raw = base64.b64decode(payload.get("data_b64") or "")
    if not 1000 < len(raw) < 20_000_000:
        raise ValueError("图片大小须在 1KB~20MB")
    final = store.FACE_DIR / f"{stem}_ui_{time.strftime('%Y%m%d%H%M%S')}.{ext}"
    final.write_bytes(raw)
    # 推到设备: 优先 registry 通道, 未登记设备用 serial 直推
    target = None
    for cand in ((dev or {}).get("serial"), (dev or {}).get("wifi") or "", serial):
        if cand and adbtools.get_state(cand):
            target = cand
            break
    if not target:
        ok, detail = False, (f"{alias or serial or '设备'} 不在线, 图已存 {final.name}, 上线后再推")
    else:
        ok, detail = runner.push_face(target, str(final))
    if alias and dev:
        store.update_entry(alias, {**dev, "face": str(final)})
    log_event(alias or serial or "?", "face", detail, ok)
    return {"ok": ok, "detail": detail, "face": str(final), "alias": alias or None}


def save_step_cadence(payload):
    """传感器参数写入: adb put jrstep_cadence + jrstep_on=1; 已登记设备同步 devices.json cadence."""
    serial = str(payload.get("serial") or "")
    cadence = int(payload.get("cadence") or 0)
    if not 80 <= cadence <= 220:
        raise ValueError("cadence 须在 80~220 步/分")
    if not serial:
        raise ValueError("serial required")
    registry = store.load()
    alias = None
    for a, dev in registry.items():
        if a.startswith("_"):
            continue
        if dev["serial"] == serial:
            alias = a
            break
        if dev.get("wifi") and serial.startswith(dev["wifi"].split(":")[0] + ":"):
            alias = a
            break
    target = serial if adbtools.get_state(serial) else None
    if not target:
        return {"ok": False, "error": f"{alias or serial} 设备不在线, 无法写入"}
    rc, _ = adbtools.shell(target, "settings", "put", "global", "jrstep_cadence", str(cadence))
    rc2, _ = adbtools.shell(target, "settings", "put", "global", "jrstep_on", "1")
    ok = rc == 0 and rc2 == 0
    detail = f"jrstep_cadence={cadence}, jrstep_on=1 已写入 ({target})"
    if ok and alias:
        store.update_entry(alias, {**registry[alias], "cadence": cadence})
        detail += f", devices.json[{alias}].cadence 已同步"
    log_event(alias or serial, "cadence", detail, ok)
    return {"ok": ok, "detail": detail, "cadence": cadence}


def prepare_device(payload):
    """设备预置 (不连接): appops/定位开关/jrstep/jrface/清残留/jrdevice opt-in.
       扫描卡「连接」前置步骤; 换机后没有过 joyrun_switch 的设备靠它补齐虚拟定位条件.
       serial 按 registry 匹配 alias; 未登记设备用默认参数 (testprovider/cadence 131).
       requester_port: 发起请求的 RS 端口. 若同一串号正在另一个端口播放, 返回冲突 (防双实例互相清 jrgps_feed)."""
    serial = str(payload.get("serial") or "").strip()
    requester_port = int(payload.get("requester_port") or 0)
    if not serial:
        raise ValueError("serial required")
    registry = store.load()
    alias = None
    if requester_port:
        allowed_port = requester_port
    for a, dev in registry.items():
        if a.startswith("_"):
            continue
        if dev["serial"] == serial or (dev.get("wifi") and serial.startswith(dev["wifi"].split(":")[0] + ":")):
            alias = a
            if not requester_port:
                allowed_port = dev["port"]
            break
    # 冲突检查: 正在用这台设备播放的实例 (不论哪个端口) 都不允许预置 ——
    # 预置会清 jrgps_feed/jrpos, 直接掐断进行中的注入
    for a, dev in registry.items():
        if a.startswith("_"):
            continue
        st = runner.rs_status(dev["port"], timeout=2)
        if st and st.get("udid") == serial and st.get("state") in ("playing", "paused"):
            return {"ok": False, "conflict": True,
                    "error": f"该设备正在端口 {dev['port']} ({a}) 播放。预置会清 jrgps_feed 掐断注入 —— "
                             f"先停那边, 或直接在该端口页面操作。"}
    dev = registry.get(alias) if alias else {
        "serial": serial, "wifi": "", "port": 0, "mode": "testprovider",
        "cadence": 131, "speed_kmh": 13.33, "face": "", "jrdevice": ""}
    if not adbtools.get_state(serial):
        wifi = dev.get("wifi") or ""
        if wifi:
            adbtools.connect_wifi(wifi, timeout=8)
            time.sleep(1.0)
        if not adbtools.get_state(serial):
            return {"ok": False, "error": f"{alias or serial} 设备不在线, 无法预置"}
    steps = adbtools.preset(serial, dev)
    ok = all(s[1] for s in steps)
    log_event(alias or serial, "prepare",
              "预置完成: " + ", ".join(n for n, o, _ in steps if o), ok)
    return {"ok": ok, "alias": alias or None,
            "steps": [{"step": n, "ok": bool(o), "detail": d} for n, o, d in steps]}


def rs_restart(payload):
    """重启指定 RS systemd 实例 (自愈死绑定: 实例绑着已拔设备时 connect 只会向死设备重发坐标).
       红线: state=playing 时拒绝 (不动在跑的实例)."""
    alias = str(payload.get("alias") or "").strip()
    if not alias:
        raise ValueError("alias required")
    dev = store.get(alias)  # 校验存在
    st = runner.rs_status(dev["port"], timeout=3)
    if st and st.get("state") == "playing":
        return {"ok": False, "error": "实例正在播放, 拒绝重启"}
    import subprocess
    r = subprocess.run(["/usr/bin/systemctl", "--user", "restart", f"route-studio@{alias}"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return {"ok": False, "error": "systemctl 失败: " + (r.stderr or "").strip()[:200]}
    time.sleep(2.0)
    st2 = runner.rs_status(dev["port"], timeout=5)
    return {"ok": True, "detail": f"route-studio@{alias} 已重启, state={(st2 or {}).get('state')}",
            "state": (st2 or {}).get("state")}


def save_registry(doc):
    out = store.save(doc)
    log_event("*", "registry", "devices.json 已保存 (备份见 devices.json.bak-*)")
    return {"ok": True, "devices": {k: v for k, v in out.items() if not k.startswith("_")}}


class Handler(BaseHTTPRequestHandler):
    def host_allowed(self):
        host = self.headers.get("Host", "").partition(":")[0].lower()
        return host in ("localhost", "127.0.0.1")

    def _headers(self, code, ctype, length, cors=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cors:
            # 仅本机回环页面 (RS 各实例 :876x) 的只读跨源读取
            origin = self.headers.get("Origin") or ""
            if re.match(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$", origin):
                self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()

    def json(self, data, code=200, cors=False):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self._headers(code, "application/json; charset=utf-8", len(body), cors=cors)
        self.wfile.write(body)

    def _static(self, path):
        name = "index.html" if path == "/" else path.removeprefix("/static/")
        target = (STATIC / name).resolve()
        if (path != "/" and not path.startswith("/static/")) or not target.is_relative_to(STATIC.resolve()) or not target.is_file():
            self.json({"error": "Not found"}, 404)
            return
        mime = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
                "css": "text/css; charset=utf-8"}.get(target.suffix.lstrip("."), "application/octet-stream")
        body = target.read_bytes()
        self._headers(200, mime, len(body))
        self.wfile.write(body)

    def do_GET(self):
        if not self.host_allowed():
            self.json({"error": "Host denied"}, 403)
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/overview":
                self.json(overview())
            elif path == "/api/adb-list":
                self.json({"devices": adbtools.parse_devices(), "server_time": time.time()}, cors=True)
            elif path == "/api/events":
                with _events_lock:
                    items = list(_events)
                self.json({"events": items[-120:]})
            elif path == "/api/registry":
                doc = store.load()
                self.json({"devices": {k: v for k, v in doc.items() if not k.startswith("_")}}, cors=True)
            elif path == "/api/device-log":
                q = parse_qs(urlparse(self.path).query)
                alias = (q.get("alias") or [""])[0]
                if not alias:
                    raise ValueError("alias query param required")
                dev = store.get(alias)
                ch = None
                for cand in (dev["serial"], dev.get("wifi") or ""):
                    if cand and adbtools.get_state(cand):
                        ch = cand
                        break
                if not ch:
                    self.json({"log": "(设备不在线)", "channel": None})
                else:
                    self.json({"log": adbtools.module_log_tail(ch, 40), "channel": ch})
            elif path in ("/", "/static/index.html", "/static/app.js", "/static/style.css", "/favicon.ico"):
                if path == "/favicon.ico":
                    self.json({"error": "Not found"}, 404)
                else:
                    self._static(path)
            else:
                self.json({"error": "Not found"}, 404)
        except Exception as e:
            self.json({"error": f"{type(e).__name__}: {e}"}, 500)

    _LOCAL_ORIGIN = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$")

    def do_OPTIONS(self):
        """CORS 预检: 仅放行本机回环页面对 /api/face 与 /api/step-cadence 的跨源写入 (RS 卡片用)."""
        if urlparse(self.path).path not in ("/api/face", "/api/step-cadence", "/api/prepare", "/api/rs-restart") \
                or not self._LOCAL_ORIGIN.match(self.headers.get("Origin") or ""):
            self.json({"error": "Not found"}, 404)
            return
        body = b""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin"))
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            path = urlparse(self.path).path
            if not self.host_allowed():
                self.json({"error": "Host denied"}, 403)
                return
            # /api/face 与 /api/step-cadence 额外接受本机回环页面 (RS 卡片) 的跨源写入; 其余仅同源
            cors_ok = path in ("/api/face", "/api/step-cadence", "/api/prepare", "/api/rs-restart") \
                and origin and self._LOCAL_ORIGIN.match(origin)
            if origin and not cors_ok and origin != "http://" + self.headers.get("Host", ""):
                self.json({"error": "Origin denied"}, 403)
                return
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json")
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 30_000_000:
                raise ValueError("bad content length")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            self.json(self._dispatch(path, data), cors=cors_ok)
        except KeyError as e:
            self.json({"error": str(e)}, 404)
        except (ValueError, KeyError) as e:
            self.json({"error": str(e)}, 400)
        except Exception as e:
            self.json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _dispatch(self, path, data):
        if path == "/api/registry":
            return save_registry(data)
        if path == "/api/face":
            return save_face(data)
        if path == "/api/step-cadence":
            return save_step_cadence(data)
        if path == "/api/prepare":
            return prepare_device(data)
        if path == "/api/rs-restart":
            return rs_restart(data)
        if path.startswith("/api/devices/"):
            rest = path.removeprefix("/api/devices/").split("/")
            if len(rest) == 2:
                alias, action = rest
                return self._device_action(alias, action, data)
        raise KeyError("Not found")

    def _device_action(self, alias, action, data):
        dev = store.get(alias)
        confirm = bool(data.get("confirm"))
        if action == "run":
            out = runner.run_pipeline(alias, confirm=confirm, start=True)
            ok = out.get("ok")
            log_event(alias, "run", ("一键开跑完成" if ok else "开跑失败: " + str(out.get("error"))), ok)
            return out
        if action == "stop":
            out = runner.stop_pipeline(alias, confirm=confirm)
            ok = out.get("ok")
            log_event(alias, "stop", ("已停止 (守卫+注入)" if ok else "停止失败: " + str(out.get("error"))), ok)
            return out
        if action == "guard-start":
            ch = _channel_of(dev)
            if not ch:
                return {"ok": False, "error": "设备不在线"}
            ok, msg = procs.guard_start(alias, ch)
            log_event(alias, "guard", f"守卫 {msg}", ok)
            return {"ok": ok, "detail": msg}
        if action == "guard-stop":
            ok, msg = procs.guard_stop(alias)
            log_event(alias, "guard", f"守卫 {msg}", ok)
            return {"ok": ok, "detail": msg}
        if action == "bridge-start":
            ch = _channel_of(dev)
            if not ch:
                return {"ok": False, "error": "设备不在线"}
            ok, msg = procs.bridge_start(alias, ch, dev["port"])
            log_event(alias, "bridge", f"jrpos 桥 {msg}", ok)
            return {"ok": ok, "detail": msg}
        if action == "bridge-stop":
            ok, msg = procs.bridge_stop(alias)
            log_event(alias, "bridge", f"jrpos 桥 {msg}", ok)
            return {"ok": ok, "detail": msg}
        # RS 透传 (单端口)
        if action in ("connect", "disconnect", "start", "pause", "stop"):
            st = runner.rs_status(dev["port"], timeout=3)
            if st and st.get("state") == "playing" and action in ("stop", "disconnect", "connect") and not confirm:
                return {"ok": False, "confirm_required": True, "error": "实例正在播放, 需要确认"}
            body = {}
            if action == "connect":
                ch = _channel_of(dev)
                if not ch:
                    return {"ok": False, "error": "设备不在线 (USB/WiFi 均不可达)"}
                body = ({"platform": "android", "udid": dev["serial"]} if ch == dev["serial"]
                        else {"platform": "android", "address": dev["wifi"]})
            out = runner.rs_call(dev["port"], action, body,
                                 timeout=40 if action == "connect" else 15)
            mode = (out.get("diagnostics") or {}).get("mode")
            log_event(alias, action, f"{action}: err={out.get('error') or 'ok'} mode={mode}",
                      not out.get("error"))
            return {"ok": not out.get("error"), "rs": out}
        if action == "settings":
            body = data.get("settings")
            if not isinstance(body, dict) or len(body) != 7:
                raise ValueError("settings 必须为完整 7 字段对象")
            out = runner.rs_call(dev["port"], "settings", body)
            log_event(alias, "settings", f"settings err={out.get('error') or 'ok'}", not out.get("error"))
            return {"ok": not out.get("error"), "rs": out}
        raise KeyError(f"unknown action: {action}")


def _channel_of(dev):
    for cand in (dev["serial"], dev.get("wifi") or ""):
        if cand and adbtools.get_state(cand):
            return cand
    return None


def serve(port=8800):
    try:
        registry = store.load()
        procs.adopt_orphans({k: v for k, v in registry.items() if not k.startswith("_")})
    except Exception as e:
        print(f"adopt_orphans skipped: {e}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(f"paceghost WebUI: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        procs.stop_all()
        server.server_close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    args = ap.parse_args()
    serve(args.port)


if __name__ == "__main__":
    main()
