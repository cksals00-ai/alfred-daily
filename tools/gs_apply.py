# -*- coding: utf-8 -*-
"""gs_perf.json → dashboard.html 의 const GS_PERF 갱신 (한 줄 치환)"""
import json, re, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
PERF = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/work/gs_perf.json"
HTML = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "app", "public", "dashboard.html")

data = json.load(open(PERF, encoding="utf-8"))
line = "const GS_PERF = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"

s = open(HTML, encoding="utf-8").read()
m = re.search(r"^const GS_PERF = .*;$", s, re.M)
assert m, "GS_PERF anchor not found in " + HTML
s = s[:m.start()] + line + s[m.end():]
open(HTML, "w", encoding="utf-8").write(s)
print("OK", data.get("asOf"), "months", [(x["label"], x["ach"], x["fcstAch"]) for x in data["months"]])
