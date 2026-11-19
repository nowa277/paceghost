"""devices.json 事实源读写 (带时间戳备份, 纯 ASCII 命名校验)."""
import json
import re
import shutil
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEVJSON = BASE / "devices.json"
BACKUPS = BASE / "backups"
FACE_DIR = BASE / "work" / "face"

ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DEV_FIELDS = {"serial": str, "wifi": str, "port": int, "mode": str, "cadence": int,
              "speed_kmh": float, "face": str}
MODES = ("testprovider", "settings")
LOCK = threading.Lock()
MAX_BACKUPS = 10


def _norm_entry(alias, d):
    """规范化单条设备记录, 缺省补默认值; 非法字段报 ValueError."""
    if not isinstance(d, dict):
        raise ValueError(f"[{alias}] entry must be an object")
    out = {"serial": str(d.get("serial") or "").strip(),
           "wifi": str(d.get("wifi") or "").strip(),
           "port": int(d.get("port") or 0),
           "mode": str(d.get("mode") or "testprovider").strip(),
           "cadence": int(d.get("cadence") or 131),
           "speed_kmh": float(d.get("speed_kmh") or 13.33),
           "face": str(d.get("face") or "").strip(),
           "jrdevice": str(d.get("jrdevice") or "").strip()}
    if not out["serial"]:
        raise ValueError(f"[{alias}] serial required")
    if out["port"] <= 0 or out["port"] > 65535:
        raise ValueError(f"[{alias}] port invalid: {out['port']}")
    if out["mode"] not in MODES:
        raise ValueError(f"[{alias}] mode must be one of {MODES}")
    if out["wifi"] and ":" not in out["wifi"]:
        out["wifi"] += ":5555"
    return out


def _validate(doc):
    if not isinstance(doc, dict):
        raise ValueError("devices.json must be an object")
    out = {}
    for alias, d in doc.items():
        if alias.startswith("_"):
            out[alias] = d  # 保留 _说明 等元数据键
            continue
        if not ALIAS_RE.match(alias):
            raise ValueError(f"alias [{alias}] must be ascii snake_case (^[a-z][a-z0-9_]*$)")
        out[alias] = _norm_entry(alias, d)
    ports = [v["port"] for k, v in out.items() if not k.startswith("_")]
    if len(ports) != len(set(ports)):
        raise ValueError("duplicate ports in registry")
    return out


def load():
    with LOCK:
        doc = json.loads(DEVJSON.read_text(encoding="utf-8"))
    return _validate(doc)


def get(alias):
    doc = load()
    if alias not in doc or alias.startswith("_"):
        raise KeyError(f"unknown alias: {alias}")
    return doc[alias]


def save(doc):
    """整体保存 (先备份到 backups/), 输入须经校验."""
    doc = _validate(doc)
    with LOCK:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        if DEVJSON.exists():
            bak = BACKUPS / f"devices.json.bak-{time.strftime('%Y%m%d-%H%M%S')}"
            shutil.copy2(DEVJSON, bak)
            baks = sorted(BACKUPS.glob("devices.json.bak-*"))
            for old in baks[:-MAX_BACKUPS]:
                old.unlink(missing_ok=True)
        DEVJSON.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def update_entry(alias, entry):
    doc = load()
    doc[alias] = _norm_entry(alias, entry)
    return save(doc)


def delete_entry(alias):
    doc = load()
    if alias not in doc:
        raise KeyError(f"unknown alias: {alias}")
    del doc[alias]
    return save(doc)


def next_port():
    used = {v["port"] for v in load().values() if isinstance(v, dict) and "port" in v}
    p = max(used, default=8764) + 1
    while p in used:
        p += 1
    return p


def face_mtime(path):
    try:
        return int(Path(path).stat().st_mtime)
    except OSError:
        return None
