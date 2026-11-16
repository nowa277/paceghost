import sys
from mitmproxy import io
from collections import Counter

for path in sys.argv[1:]:
    print(f"\n===== {path} =====")
    with open(path, "rb") as f:
        r = io.FlowReader(f)
        flows = list(r.stream())
    print(f"total flows: {len(flows)}")
    c = Counter()
    for fl in flows:
        req = fl.request
        if req.host == "localhost" or "mitm.it" in req.path:
            continue
        c[(req.host, req.method)] += 1
    for (host, method), n in c.most_common():
        print(f"  {n:4d}  {method:6s} {host}")
