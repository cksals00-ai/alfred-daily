# -*- coding: utf-8 -*-
"""GS 원본 대시보드 → 실적 시각화용 구조화 데이터 추출"""
import re, json, urllib.request

SRC = "https://cksals00-ai.github.io/gs_daily_trend_news_public_temp/index.html"
OUT = "/home/claude/work/gs_perf.json"

s = urllib.request.urlopen(SRC, timeout=60).read().decode("utf-8", "replace")


def grab(name):
    m = re.search(r'(?:var|const|let)\s+' + name + r'\s*=\s*([{\[])', s)
    if not m:
        return None
    i = m.end() - 1
    depth, instr, esc = 0, False, False
    for j in range(i, len(s)):
        c = s[j]
        if instr:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': instr = False
            continue
        if c == '"': instr = True
        elif c in '{[': depth += 1
        elif c in '}]':
            depth -= 1
            if depth == 0:
                return json.loads(s[i:j + 1])
    return None


def tpl(key):
    m = re.search(r'data-tpl-' + key + r'\s*>', s)
    if not m:
        return None
    j = s.find('<', m.end())
    return s[m.end():j].strip()


def num(x):
    if x is None: return None
    x = x.replace(",", "").replace("%", "").replace("+", "").replace("실", "").strip()
    try: return float(x)
    except Exception: return None


D = grab("INSIGHT_DATA")
TB = grab("TB_BY_MONTH") or {}

# ── 1) 월별 목표 대비 ────────────────────────────────────────
months = []
for i in range(3):
    label = tpl(f"otb-m{i}-label")
    actual = num(tpl(f"otb-m{i}-actual"))
    ach = num(tpl(f"otb-m{i}-ach"))
    fcst = num(tpl(f"otb-m{i}-fcst"))
    if not label or actual is None or not ach:
        continue
    budget = round(actual / (ach / 100))
    yoy = (D.get("yoyOtb") or {}).get(label, {})
    months.append({
        "label": label, "actual": int(actual), "budget": budget, "ach": ach,
        "fcst": int(fcst) if fcst else None,
        "fcstAch": num(tpl(f"otb-m{i}-fcst-ach")),
        "todayNet": num(tpl(f"otb-m{i}-today-net")),
        "yoyRn": yoy.get("rn_pct"), "yoyRev": yoy.get("rev_pct"), "yoyAdr": yoy.get("adr_pct"),
        "cyRn": yoy.get("cy_rn"), "lyRn": yoy.get("ly_rn"),
    })

# ── 2) 일별 픽업 (올해 / 작년) ───────────────────────────────
def trend(key):
    return [{"l": r["label"], "p": r["pickup"], "c": r["cancel"], "n": r["net"]}
            for r in (D.get(key) or [])]

daily = {"cy": trend("dailyTrend"), "ly": trend("dailyTrendLY")}

# ── 3) 세그먼트 주간 추이 + 당일 ─────────────────────────────
segw = D.get("segWeekly") or {}
segToday = D.get("segToday") or {}
seg = {"weekly": {k: v for k, v in segw.items()},
       "today": {k: v for k, v in segToday.items()},
       "labels": [r["l"] for r in daily["cy"]]}

# 전체 세그(당일 net) — 자사/여행사 등 포함
segAll = (D.get("dailyAnalysis") or {}).get("bySegment") or {}
seg["allToday"] = sorted(
    [{"n": k, "net": v.get("net", 0), "pickup": v.get("pickup", 0), "cancel": v.get("cancel", 0)}
     for k, v in segAll.items()], key=lambda r: -r["net"])

# ── 4) 채널 주간 순증 ────────────────────────────────────────
cws = (D.get("channelWeeklyShare") or {}).get("all") or []
chan = [{"l": r["label"], "ch": r["channels"], "total": r["total"]} for r in cws][-6:]

# ── 5) 사업장별 YoY ─────────────────────────────────────────
prop = []
cur = months[0]["label"] if months else "7월"
bp = ((D.get("yoyOtb") or {}).get(cur) or {}).get("byProperty") or {}
for k, v in bp.items():
    if v.get("pct") is None:
        continue
    prop.append({"n": k, "cy": v.get("cy"), "ly": v.get("ly"), "pct": v.get("pct")})
prop.sort(key=lambda r: -r["pct"])

res = {
    "src": SRC,
    "asOf": D.get("todayDate"),
    "asOfLabel": D.get("todayLabel"),
    "curMonth": cur,
    "months": months,
    "daily": daily,
    "seg": seg,
    "chan": chan,
    "prop": prop,
    "topbot": TB.get(cur.replace("월", ""), {}),
    "revAch": num(tpl("otb-rev-ach")),
    "otbYoy": num(tpl("otb-yoy")),
}
open(OUT, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
print("asOf", res["asOf"], "| months", [(m["label"], m["actual"], m["budget"], m["ach"]) for m in res["months"]])
print("daily cy", len(daily["cy"]), "ly", len(daily["ly"]))
print("seg weekly keys", list(seg["weekly"].keys()), "| allToday", len(seg["allToday"]))
print("chan weeks", [c["l"] for c in chan], "| channels", list(chan[-1]["ch"].keys()) if chan else [])
print("prop", len(prop), prop[:3], prop[-2:])
print("revAch", res["revAch"], "otbYoy", res["otbYoy"], "topbot", res["topbot"])
