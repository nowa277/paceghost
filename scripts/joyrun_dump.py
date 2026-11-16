"""mitmproxy addon: 只记录 joyrunworld / 相关域名，落 JSONL，控制台打摘要。"""
import json, os, time
from mitmproxy import http

OUT = "/home/sesley/Workspace/paceghost/capture/joyrun_api.jsonl"
HOSTS = ("joyrunworld", "joyrun", "zgjkw", "amap", "is.autonavi")

def _txt(content, limit=4000):
    try:
        s = content.decode("utf-8", "replace")
    except Exception:
        return "<binary>"
    return s if len(s) <= limit else s[:limit] + f"...<trunc {len(s)}>"

def response(flow: http.HTTPFlow):
    host = flow.request.pretty_host
    if not any(h in host for h in HOSTS):
        return
    rec = {
        "ts": time.strftime("%H:%M:%S", time.localtime(flow.request.timestamp_start)),
        "method": flow.request.method,
        "url": flow.request.pretty_url,
        "req_headers": dict(flow.request.headers),
        "req_body": _txt(flow.request.content or b""),
        "status": flow.response.status_code if flow.response else None,
        "resp_headers": dict(flow.response.headers) if flow.response else {},
        "resp_body": _txt(flow.response.content or b"") if flow.response else "",
    }
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    msgs = f"[JOYRUN] {rec['method']} {flow.request.path[:90]} -> {rec['status']} ({len(flow.response.content) if flow.response and flow.response.content else 0}B)"
    print(msgs, flush=True)
