import sys
from mitmproxy import io

for path in sys.argv[1:]:
    print(f"\n===== {path} =====")
    with open(path, "rb") as f:
        flows = list(io.FlowReader(f).stream())
    for fl in flows:
        req, resp = fl.request, fl.response
        t = fl.timestamp_start
        status = resp.status_code if resp else "-"
        clen = len(resp.content) if resp and resp.content else 0
        print(f"  {t:.1f}  {req.method:5s} {req.scheme}://{req.host}{req.path[:80]} -> {status} ({clen}B)  proto={resp.http_version if resp else '-'}")
