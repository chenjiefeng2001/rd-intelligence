import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

BASE = os.environ.get("IDE_BASE", "http://127.0.0.1:8760")
CAPTURE = sys.argv[1]


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


info = get("/api/info")
print("info:", info["capture"].split("\\")[-1])

diff = get("/api/diff?a=320,240&b=10,10")
first = diff["firstDivergence"] or {}
print("diff:", diff["comparison"], "| first:", first.get("layer"))

trace = get("/api/trace?x=320&y=240")
reads = [e["to"] for e in trace["edges"] if e["label"] == "reads"]
print("trace reads:", reads)

res = get("/api/resource?id=ResourceId::47")
print("resource writers:", [(w["eventId"], w["usage"]) for w in res["writers"]])

exp = get("/api/explain?a=320,240&b=10,10")
print("prompt head:", exp["prompt"].splitlines()[0])
print("evidence ids:", len(exp["evidenceIds"]))

with urllib.request.urlopen(BASE + "/") as r:
    html = r.read().decode("utf-8")
print("index.html bytes:", len(html))
print("IDE SMOKE OK")
