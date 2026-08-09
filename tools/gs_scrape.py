# -*- coding: utf-8 -*-
"""GS 원본 대시보드 → 실적 시각화용 구조화 데이터 추출

출처 3곳
  1) index.html 안에 박힌 INSIGHT_DATA / TB_BY_MONTH / data-tpl-* KPI
  2) data/otb_data.json        → 월×세그 목표·실적·예상 (segMonth)
  3) data/rm_fcst_trend.json   → 주간 RM FCST 스냅샷 (fcstTrend)
"""
import re, json, urllib.request

# ── 커밋 작성자 강제 (프롬프트 지시가 누락돼도 Unverified 커밋이 안 생기게) ──
try:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "."))
    from gitid import ensure as _ensure_gitid
    _ensure_gitid()
except Exception as _e:
    print(f"[gitid] 건너뜀 — {_e}")


BASE = "https://cksals00-ai.github.io/gs_daily_trend_news_public_temp/"
SRC = BASE + "index.html"
OTB = BASE + "data/otb_data.json"
RMF = BASE + "data/rm_fcst_trend.json"
OUT = "/home/claude/work/gs_perf.json"


def fetch(url):
    return urllib.request.urlopen(url, timeout=180).read().decode("utf-8", "replace")


s = fetch(SRC)


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

# ── 6) 월 × 세그 목표 대비 (otb_data.json) ───────────────────
# 예산이 붙어 있는 세그는 OTA / G-OTA / Inbound 셋뿐이고, 셋의 예산 합 = 전체 예산이다.
# 그래서 토글 가능한 엔티티를 전체 + 이 셋으로 고정한다(색은 이름에 고정).
SEGS = ["전체", "OTA", "G-OTA", "Inbound"]
otb = json.loads(fetch(OTB))
otbMeta = otb.get("meta") or {}
segMonth = {"segs": SEGS, "labels": [m["label"] for m in months], "data": {}}


def pick(v):
    return {
        "budget": v.get("rns_budget"), "actual": v.get("rns_actual"),
        "ach": v.get("rns_achievement"), "fcst": v.get("rns_fcst"),
        "fcstAch": v.get("fcst_achievement"), "todayNet": v.get("today_net"),
    }


for m in months:
    mk = m["label"].replace("월", "")
    node = (otb.get("allMonths") or {}).get(mk) or {}
    sd = node.get("segmentData") or {}
    su = node.get("summary") or {}
    row = {"전체": pick({
        "rns_budget": su.get("rns_budget"), "rns_actual": su.get("rns_actual"),
        "rns_achievement": su.get("rns_achievement"), "rns_fcst": su.get("rns_fcst"),
        "fcst_achievement": su.get("fcst_achievement"), "today_net": su.get("today_net"),
    })}
    for k in SEGS[1:]:
        if k in sd:
            row[k] = pick(sd[k])
    segMonth["data"][m["label"]] = row

# ── 7) 예상실적 주간 변화 (rm_fcst_trend.json) ───────────────
rmf = json.loads(fetch(RMF))
YEAR = 2026
snaps = [x for x in (rmf.get("snapshots") or []) if x.get("_year") == YEAR]
snaps.sort(key=lambda x: x["_snapshot_date"])

fcstTrend = {"segs": SEGS, "months": []}
for m in months:
    mk = "%d-%02d" % (YEAR, int(m["label"].replace("월", "")))
    dates, series = [], {k: [] for k in SEGS}
    budget = {k: None for k in SEGS}
    for sn in snaps:
        props = sn.get("properties") or {}
        tot, bud = 0, 0
        acc = {k: 0 for k in SEGS[1:]}
        accB = {k: 0 for k in SEGS[1:]}
        hit = False
        for p in props.values():
            mm = p.get(mk)
            if not mm:
                continue
            hit = True
            for k, v in (mm.get("segments") or {}).items():
                if k in acc:
                    acc[k] += v.get("rm_fcst_rn") or 0
                    accB[k] += v.get("rm_budget_rn") or 0
        if not hit:
            continue
        tot = sum(acc.values())
        bud = sum(accB.values())
        d = sn["_snapshot_date"].split("-")
        dates.append("%d/%d" % (int(d[1]), int(d[2])))
        series["전체"].append(tot)
        for k in SEGS[1:]:
            series[k].append(acc[k])
        budget["전체"] = bud
        for k in SEGS[1:]:
            budget[k] = accB[k]
    if dates:
        fcstTrend["months"].append({
            "label": m["label"], "key": mk, "dates": dates,
            "series": series, "budget": budget,
        })

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
    "segMonth": segMonth,
    "fcstTrend": fcstTrend,
    "refresh": otbMeta.get("refreshTime"),
    "fcstAsOf": snaps[-1]["_snapshot_date"] if snaps else None,
}
open(OUT, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
print("asOf", res["asOf"], "| refresh", res["refresh"], "| fcstAsOf", res["fcstAsOf"])
print("months", [(m["label"], m["actual"], m["budget"], m["ach"]) for m in res["months"]])
print("daily cy", len(daily["cy"]), "ly", len(daily["ly"]))
print("seg weekly keys", list(seg["weekly"].keys()), "| allToday", len(seg["allToday"]))
print("chan weeks", [c["l"] for c in chan])
print("prop", len(prop))
for lb, row in segMonth["data"].items():
    print(" segMonth", lb, {k: (v["ach"], v["fcstAch"], v["todayNet"]) for k, v in row.items()})
for mo in fcstTrend["months"]:
    print(" fcstTrend", mo["label"], len(mo["dates"]), mo["dates"][0], "→", mo["dates"][-1],
          "전체", mo["series"]["전체"][0], "→", mo["series"]["전체"][-1], "bud", mo["budget"]["전체"])
