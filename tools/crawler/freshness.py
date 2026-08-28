# -*- coding: utf-8 -*-
"""대시보드 데이터 소스 신선도 점검기.

대시보드에는 자동 갱신되는 축과 손으로 채우는 축이 섞여 있다. 문제는 자동 축이
조용히 멈춰도 화면은 멀쩡해 보인다는 것이다 — 어제 데이터가 그대로 남아 있으면
'오늘 데이터'처럼 읽힌다. 실제로 digest.py 가 컨테이너에서 사라진 채 몇 주를
돌았고, 그 사실은 재현본 꼭지 수가 16→9→5 로 쪼그라들 때까지 드러나지 않았다.

그래서 이 스크립트는 각 소스의 **가장 최근 날짜**만 본다. 내용의 품질은 score.py
가 보고, 여기서는 "갱신이 돌긴 했는가"만 본다. 둘은 다른 질문이다.

판정 기준
  정상  : 경과일 <= ok
  주의  : 경과일 <= warn
  실패  : 그보다 오래됨
  수동  : 자동화가 없는 축(롱블랙 노트·오늘 안건). 경과일은 보여주되 실패로 세지 않는다.
  조회실패 : 파일·상수를 못 읽음. **추정치로 메우지 않는다.**

GS 계열은 출처 페이지가 주말·공휴일에 갱신되지 않으므로 달력일이 아니라 영업일로
센다. 토요일에 "금요일 데이터라 하루 밀렸다"고 경보를 울리면 그 경보는 곧 무시된다.

사용: python3 tools/crawler/freshness.py
     python3 tools/crawler/freshness.py --line   (보고용 한 줄만)
"""
import json, os, re, sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _paths import PUBLIC  # noqa: E402

DASH = os.path.join(PUBLIC, "dashboard.html")
KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()

OK, WARN, FAIL, MANUAL, UNREAD = "정상", "주의", "실패", "수동", "조회실패"

# 카테고리 → 그걸 실제로 굴리는 예약작업. 담당자가 없는 축은 None 이다.
OWNER = {
    "daily": "Alfred Daily 07:00 (trig_01QSnb9cSoQyNvLku62aKCA4)",
    "gs":    "GS·인사이트 09:00 (trig_01QM65z2VTBqfM4AB5Zgd9dD)",
    "weekly": "주간 브리핑 일 07:00 (trig_01NqusWzxt6ikGFZkKwRJ15C)",
    "manual": "없음 — 손으로 채운다",
}


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dash():
    with open(DASH, encoding="utf-8") as f:
        return f.read()


def block(s, name):
    """최상위 `const NAME` 선언부터 다음 최상위 const 직전까지."""
    i = s.find("const %s " % name)
    if i < 0:
        i = s.find("const %s=" % name)
    if i < 0:
        raise KeyError("const %s 를 dashboard.html 에서 찾지 못했다" % name)
    j = s.find("\nconst ", i + 1)
    return s[i:j if j > 0 else len(s)]


# 키가 따옴표 있는 날(JSON 스타일)과 없는 날(JS 스타일)이 섞여 있다. 한쪽만 맞춘
# 정규식을 쓰면 개수가 조용히 적게 잡힌다 — 실제로 한 번 그렇게 틀렸다.
_DATE = re.compile(r'"?date"?\s*:\s*"(\d{4}-\d{2}-\d{2})"')


def dates_in(s, name):
    return sorted(set(_DATE.findall(block(s, name))))


def kv(s, name, key):
    m = re.search(r'"?%s"?\s*:\s*"([^"]+)"' % re.escape(key), block(s, name))
    return m.group(1) if m else None


def d(x):
    """'2026-08-03' / '20260802' / '2026-08-03 08:26 KST' → date"""
    x = x.strip()
    if re.fullmatch(r"\d{8}", x):
        return datetime.strptime(x, "%Y%m%d").date()
    return datetime.strptime(x[:10], "%Y-%m-%d").date()


def period_end(period):
    """'2026.07.26 ~ 08.01 · 노트 8개 기준 …' → date(2026, 8, 1)"""
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\s*~\s*(\d{2})\.(\d{2})", period)
    if not m:
        raise ValueError("period 형식을 못 읽었다: %r" % period[:40])
    y, m1, d1, m2, d2 = (int(g) for g in m.groups())
    y2 = y + 1 if m2 < m1 else y          # 연말 걸침
    return datetime(y2, m2, d2).date()


def biz_gap(then):
    """then 다음날부터 오늘까지의 영업일 수. 출처가 주말에 안 도는 축에 쓴다."""
    n, cur = 0, then
    while cur < TODAY:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


ROWS = []


def check(label, owner, ok, warn, getter, biz=False, manual=False, note=""):
    try:
        latest = getter()
    except Exception as e:                      # 못 읽으면 못 읽었다고 적는다
        ROWS.append({"항목": label, "최신": None, "경과": None, "담당": owner,
                     "판정": UNREAD, "비고": "%s: %s" % (type(e).__name__, e)})
        return
    gap = biz_gap(latest) if biz else (TODAY - latest).days
    if manual:
        v = MANUAL
    elif gap <= ok:
        v = OK
    elif gap <= warn:
        v = WARN
    else:
        v = FAIL
    ROWS.append({"항목": label, "최신": latest.isoformat(), "경과": gap,
                 "담당": owner, "판정": v, "비고": note,
                 "단위": "영업일" if biz else "일"})


def run():
    s = _dash()

    news = _read_json(os.path.join(PUBLIC, "news.json"))
    last_news = max(news, key=lambda x: x["date"])
    check("데일리 뉴스 (news.json)", OWNER["daily"], 1, 2,
          lambda: d(last_news["date"]),
          note="src=%s · 총 %d일" % (last_news.get("src") or "미표기", len(news)))

    dg = _read_json(os.path.join(PUBLIC, "digest.json"))
    last_dg = max(dg, key=lambda x: x["date"])
    mine = any(i.get("mine") for i in last_dg.get("items", []))
    check("재현본 아카이브 (digest.json)", OWNER["daily"], 1, 2,
          lambda: d(last_dg["date"]),
          note="%d꼭지 · %s" % (len(last_dg.get("items", [])),
                              "digest.py 산출" if mine else "mine 표식 없음(수작업 의심)"))

    def insta():
        j = _read_json(os.path.join(PUBLIC, "insta.json"))
        return d(j["asOf"])
    check("리아 인스타 (insta.json)", OWNER["daily"] + " · 교신함 수급", 1, 2, insta,
          note="수집기는 자격증명 없음 — 기획실장 교신함 수급이 유일한 경로")

    # 출처 페이지는 '전일까지의 실적'을 싣는다. 그래서 asOf 는 구조적으로 1영업일
    # 뒤처진다 — 그걸 매일 경보로 올리면 경보가 무의미해진다. 임계를 한 칸 민다.
    # 2026-08-28 GS 데일리 탭 제거 — GS_DAILY·INSIGHT_DAILY 감시는 뺐다.
    # GS_PERF 는 09:00 워크플로가 계속 채우므로 남겨 둔다(오늘 탭에는 안 뜬다).
    check("GS 실적 (GS_PERF.asOf)", OWNER["gs"], 2, 3,
          lambda: d(kv(s, "GS_PERF", "asOf")), biz=True,
          note="refresh=%s · 출처가 전일 실적을 싣는 구조라 1영업일 지연은 정상" %
               kv(s, "GS_PERF", "refresh"))
    check("GS 예상착지 (GS_PERF.fcstAsOf)", OWNER["gs"], 7, 10,
          lambda: d(kv(s, "GS_PERF", "fcstAsOf")), note="주간 RM FCST 스냅샷")
    check("키워드 레이더 (TREND_PLAN)", OWNER["gs"] + " · 일요일만", 7, 9,
          lambda: d(kv(s, "TREND_PLAN", "updated")))

    check("노트 주간 브리핑 (WEEKLY_BRIEF)", OWNER["weekly"], 7, 9,
          lambda: period_end(kv(s, "WEEKLY_BRIEF", "period")))
    check("뉴스 주간 브리핑 (NEWS_WEEKLY)", OWNER["weekly"], 7, 9,
          lambda: period_end(kv(s, "NEWS_WEEKLY", "period")))

    check("롱블랙 노트 (NOTES)", OWNER["manual"], 0, 0,
          lambda: d(dates_in(s, "NOTES")[-1]), manual=True,
          note="alfred 가 링크를 보낼 때만 늘어난다 — 공백이 곧 고장은 아니다")

    def agenda_until():
        return d(kv(s, "TODAY_AGENDA", "until"))
    check("오늘 안건 (TODAY_AGENDA)", OWNER["manual"], 0, 0, agenda_until,
          manual=True, note="until 기준 — 음수 경과일이면 아직 유효, 양수면 만료")

    return ROWS


def line(rows):
    """4)번 보고에 붙일 한 줄."""
    c = {}
    for r in rows:
        c[r["판정"]] = c.get(r["판정"], 0) + 1
    bad = [r for r in rows if r["판정"] in (WARN, FAIL, UNREAD)]
    head = "[신선도] " + " · ".join("%s %d" % (k, c[k]) for k in
                                  (OK, WARN, FAIL, UNREAD, MANUAL) if c.get(k))
    if not bad:
        return head + " — 정체 없음"
    return head + " — " + ", ".join(
        "%s(%s%s)" % (r["항목"].split(" (")[0], r["경과"], r.get("단위", "일"))
        if r["경과"] is not None else "%s(조회실패)" % r["항목"].split(" (")[0]
        for r in bad)


if __name__ == "__main__":
    rows = run()
    if "--line" not in sys.argv:
        print("== 대시보드 신선도 · 기준일 %s (KST) ==" % TODAY)
        w = max(len(r["항목"]) for r in rows)
        for r in rows:
            gap = "  --" if r["경과"] is None else "%+4d%s" % (r["경과"], r.get("단위", "일")[0])
            print("%-4s %s  최신 %s  경과 %s  | %s" % (
                r["판정"], r["항목"].ljust(w), r["최신"] or "?", gap, r["담당"]))
            if r["비고"]:
                print("     └ %s" % r["비고"])
        print()
    print(line(rows))
    json.dump({"asOf": TODAY.isoformat(), "rows": rows, "line": line(rows)},
              open(os.path.join(HERE, "freshness.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
