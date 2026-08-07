# -*- coding: utf-8 -*-
"""네이버 검색 API 실제 호출 수 기록.

화면의 「무료 한도 대비 호출량」은 2026-08-07 까지 손으로 박아둔 상수(300)였다.
한 번도 안 변했고, 매일 도는 재현본 수집(씨앗어 수만큼 호출)은 아예 세어지지도
않았다. 설계치를 실측처럼 보여주는 미터는 미터가 아니라 장식이다.

그래서 각 작업이 그날 실제로 쓴 콜 수를 여기에 적어 쌓는다. 기록이 없는 날은
0으로 채우지 않는다 — 0은 「측정된 0」을 뜻하기 때문이다. 기록이 없으면 그냥
없는 날이고, 화면은 실측 시작일을 같이 보여준다.

주간 레이더는 따로 부를 필요가 없다. 레이더는 실행할 때마다 dashboard.html 의
TREND_PLAN 에 자기가 쓴 콜 수(calls)와 실행일(updated)을 이미 적어 둔다. 그래서
sync_radar() 가 그걸 읽어 옮긴다 — 07:00 재현본 실행이 매일 한 번씩 부르므로,
예약작업 프롬프트를 건드리지 않아도 일요일 레이더 실행이 다음 날 아침 반영된다.

사용:
    python3 tools/crawler/apiusage.py 재현본 37
    python3 tools/crawler/apiusage.py 레이더 84 2026-08-09
    python3 tools/crawler/apiusage.py --sync-radar
"""
import datetime, json, os, re, sys

try:
    from _paths import PUBLIC
except ImportError:
    from tools.crawler._paths import PUBLIC

PATH = os.path.join(PUBLIC, "apiusage.json")
JOBS = ("재현본", "레이더")          # 재현본 = 07:00 아침뉴스 수집 · 레이더 = 일요일 키워드


def kst_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")


def load():
    if not os.path.exists(PATH):
        return []
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def record(job, calls, date=None):
    """같은 (날짜, 작업) 기록이 있으면 덮어쓴다. 재실행이 누적을 부풀리면 안 된다."""
    if job not in JOBS:
        raise ValueError(f"모르는 작업 이름: {job} (가능: {', '.join(JOBS)})")
    calls = int(calls)
    if calls < 0:
        raise ValueError("콜 수는 음수가 될 수 없다")
    date = date or kst_today()
    rows = [r for r in load() if not (r["date"] == date and r["job"] == job)]
    rows.append({"date": date, "job": job, "calls": calls})
    rows.sort(key=lambda r: (r["date"], r["job"]))
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    return rows


def sync_radar(dash=None):
    """dashboard.html 의 TREND_PLAN 에서 마지막 레이더 실행의 콜 수를 옮겨 적는다.

    없거나 못 읽으면 예외를 낸다 — 0 으로 채우지 않는다. 0 은 「측정된 0」이다.
    """
    dash = dash or os.path.join(PUBLIC, "dashboard.html")
    with open(dash, encoding="utf-8") as f:
        s = f.read()
    m = re.search(r"const TREND_PLAN\s*=\s*(\{.*?\n\});", s, re.S)
    if not m:
        raise RuntimeError("dashboard.html 에서 TREND_PLAN 을 찾지 못했다")
    tp = json.loads(m.group(1))
    if not tp.get("calls") or not tp.get("updated"):
        raise RuntimeError("TREND_PLAN 에 calls/updated 가 없다")
    return record("레이더", tp["calls"], tp["updated"])


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--sync-radar":
        rows = sync_radar()
        last = [r for r in rows if r["job"] == "레이더"][-1]
        print(f"[apiusage] 레이더 {last['date']} {last['calls']}콜 동기화 · 총 {len(rows)}건")
        sys.exit(0)
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    rows = record(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    mo = rows[-1]["date"][:7]
    tot = sum(r["calls"] for r in rows if r["date"].startswith(mo))
    print(f"[apiusage] {sys.argv[1]} {sys.argv[2]}콜 기록 · {mo} 누적 {tot}콜 · 총 {len(rows)}건")
