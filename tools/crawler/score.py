# -*- coding: utf-8 -*-
"""재현본 ↔ 원문 대조 채점기.

원문(news.json의 그날 항목) 과 재현본(digest.json의 그날 항목)을 꼭지 단위로 맞춰
- 적중(hit)      : 원문에도 재현본에도 있는 사건
- 누락(miss)     : 원문에만 있는 사건  ← 재현본이 못 잡은 것
- 오탐(extra)    : 재현본에만 있는 사건 ← 원문이 안 다룬 것
를 뽑고, 누락을 카테고리별로 집계해 다음 날 SLOTS/SEEDS 를 고칠 근거를 만든다.

사용: python3 crawler/score.py 2026-08-03
     python3 crawler/score.py --all        (누적 리포트)
"""
import json, os, re, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _paths import PUBLIC  # noqa: E402

NEWS = os.path.join(PUBLIC, "news.json")
DIGEST = os.path.join(PUBLIC, "digest.json")

from digest import toks, GUARD   # noqa: E402

# 원문 꼭지를 카테고리로 되돌린다 — 누락이 어느 슬롯에서 나는지 보려면 필요하다.
CAT_ORDER = ["정치·국회", "국제·안보", "경제·시장", "부동산",
             "사건·사고", "날씨·기후", "사회·생활", "문화·스포츠"]


def categorize(text):
    hits = [(len(re.findall(GUARD[c], text)), c) for c in CAT_ORDER]
    hits.sort(key=lambda x: -x[0])
    return hits[0][1] if hits[0][0] else "미분류"


def split_원문(text):
    parts = [p.strip() for p in text.split("■")]
    return [p for p in parts[1:] if len(p) > 20]


MATCH_STOP = set(
    "대통령 오늘 내일 어제 발표 예정 밝혔 이번 지난 관련 대한 위해 가운데 국내 전국 "
    "가능성 상황 문제 계획 조치 대응 확대 지속 기록 나타났 보입니다 입니다 습니다".split())


def keys(s):
    """고유명사·숫자 중심의 핵심어.

    한국어는 조사가 붙어 '여객선'과 '여객선에'가 다른 토큰이 된다. 원문은 재작성돼
    있으므로 어간만 남겨 비교한다 — 뒤에서 한 글자(≥3자)·두 글자(≥5자)를 떼어
    같이 넣는다. 일반 어휘 겹침은 신호가 아니므로 MATCH_STOP 으로 걸러낸다.
    """
    k = set()
    for w in toks(s):
        if w in MATCH_STOP or len(w) < 2:
            continue
        k.add(w)
        if len(w) >= 3:
            k.add(w[:-1])
        if len(w) >= 5:
            k.add(w[:-2])
    k |= set(re.findall(r"\d[\d,\.]*", s))
    return {x for x in k if x not in MATCH_STOP and len(x) >= 2}


def match(a, b):
    """원문 꼭지 ↔ 재현본 꼭지. 길이가 크게 다르므로 비율과 절대 겹침을 함께 본다."""
    inter = a & b
    if len(inter) < 2:
        return 0.0
    ratio = len(inter) / max(1, min(len(a), len(b)))
    # 고유명사 3개 이상이 겹치면 길이 차와 무관하게 같은 사건으로 본다.
    return max(ratio, 0.25 + 0.05 * len(inter) if len(inter) >= 3 else 0.0)


THRESH = 0.28


def 정본_날짜():
    """src == '원문' 인 날만 채점 대상이다.

    재현본을 news.json 에 그대로 써 넣은 날을 채점하면 자기 자신과 비교하게 되어
    재현율이 100% 로 나온다. 그건 측정이 아니라 착시다.
    """
    return sorted(x["date"] for x in json.load(open(NEWS, encoding="utf-8"))
                  if x.get("src") == "원문")


def score(date):
    entries = {x["date"]: x for x in json.load(open(NEWS, encoding="utf-8"))}
    news = {k: v["text"] for k, v in entries.items()}
    dig = {x["date"]: x for x in json.load(open(DIGEST, encoding="utf-8"))}
    if date not in news:
        return {"date": date, "error": "원문 없음"}
    if entries[date].get("src") != "원문":
        return {"date": date,
                "error": f"정본 아님(src={entries[date].get('src') or '표시 없음'}) — 채점 제외"}
    if date not in dig:
        return {"date": date, "error": "재현본 없음"}

    src = split_원문(news[date])
    rep = dig[date]["items"]
    st = [(s, keys(s)) for s in src]
    rt = [(i, keys(i["title"] + " " + i["desc"][:80])) for i in rep]

    # 전역 배정 — 원문 순서대로 탐욕적으로 집으면 앞 꼭지가 뒤 꼭지의 짝을 가로챈다.
    # (8/5: 세제 꼭지가 형소법 재현본을 0.40에 선점해 진짜 형소법 꼭지가 누락으로 밀렸다.)
    # 모든 쌍을 점수순으로 세워 높은 쌍부터 확정한다.
    pairs = sorted(((match(a, b), i, j) for i, (s, a) in enumerate(st)
                    for j, (it, b) in enumerate(rt) if match(a, b) >= THRESH),
                   key=lambda x: -x[0])
    used, taken, hits = set(), {}, []
    for v, i, j in pairs:
        if i in taken or j in used:
            continue
        taken[i] = j; used.add(j)
    for i, (s, a) in enumerate(st):
        if i in taken:
            hits.append((s, rep[taken[i]]["title"], round(match(a, rt[taken[i]][1]), 2)))
    misses = [s for i, (s, a) in enumerate(st) if i not in taken]
    extras = [rep[j] for j in range(len(rt)) if j not in used]

    return {
        "date": date,
        "원문": len(src), "재현본": len(rep),
        "적중": len(hits), "누락": len(misses), "오탐": len(extras),
        "재현율": round(len(hits) / max(1, len(src)), 3),
        "정확도": round(len(hits) / max(1, len(rep)), 3),
        "누락_카테고리": collections.Counter(categorize(m) for m in misses),
        "누락목록": [m[:60] for m in misses],
        "오탐목록": [e["cat"] + " | " + e["title"][:55] for e in extras],
        "적중목록": [(h[0][:34], h[2]) for h in hits],
    }


def report(r):
    if r.get("error"):
        return f"{r['date']}  — {r['error']}"
    L = [f"■ {r['date']}  원문 {r['원문']}꼭지 / 재현본 {r['재현본']}꼭지",
         f"  적중 {r['적중']} · 누락 {r['누락']} · 오탐 {r['오탐']}"
         f"  → 재현율 {r['재현율']:.0%} · 정확도 {r['정확도']:.0%}",
         "  누락 카테고리: " + ", ".join(f"{k} {v}" for k, v in r["누락_카테고리"].most_common())]
    L += ["  [누락] " + m for m in r["누락목록"]]
    L += ["  [오탐] " + e for e in r["오탐목록"]]
    return "\n".join(L)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg == "--all":
        dates = 정본_날짜()
        if not dates:
            print("채점 가능한 날 없음 — news.json 에 src:\"원문\" 인 항목이 아직 없다.")
            sys.exit(0)
        agg, rows = collections.Counter(), []
        for d in dates:
            r = score(d)
            print(report(r)); print()
            if not r.get("error"):
                agg.update(r["누락_카테고리"])
                rows.append({k: r[k] for k in
                             ("date", "원문", "재현본", "적중", "누락", "오탐", "재현율", "정확도")})
        print(f"== 정본 {len(rows)}일 누적 누락 카테고리 ==")
        for k, v in agg.most_common():
            print(f"  {k}: {v}")
        if rows:
            avg = sum(x["재현율"] for x in rows) / len(rows)
            print(f"== 평균 재현율 {avg:.0%} ==")
        json.dump({"rows": rows, "누락_카테고리": dict(agg)},
                  open(os.path.join(HERE, "rubric.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    else:
        print(report(score(arg or "")))
