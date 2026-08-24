# -*- coding: utf-8 -*-
"""주간 키워드 레이더 — dashboard.html 의 TREND_PLAN 을 갱신한다.

2026-08-24 신설. 원래 이 로직은 히그스필드 예약작업 **프롬프트 안에** 있었고
레포에는 한 번도 들어온 적이 없다(문서 docs/keyword-radar.md 만 있었다).
그래서 히그스필드가 죽자 8/16 갱신을 끝으로 멈췄고 8/23 주일을 걸렀다.
같은 일이 없도록 레포 안에 코드로 넣는다 — 예약작업이 사라져도 이 파일은 남는다.

기준 문서: docs/keyword-radar.md (사양은 그 문서가 정본이다)

  세는 것은 **보도량**이지 관심량이 아니다. 「호캉스 84건 ▼37%」는 사람들이
  덜 찾았다는 뜻이 아니라 기자들이 덜 썼다는 뜻이다.

실행:
    TZ=Asia/Seoul python3 tools/crawler/radar.py            # 가장 최근에 끝난 주(월~일)
    TZ=Asia/Seoul python3 tools/crawler/radar.py 2026-08-23 # 그 주(일요일 지정)
"""
import os
import re
import sys
import json
import time
import datetime
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _paths import PUBLIC, cred                       # noqa: E402

DASHBOARD = os.path.join(PUBLIC, "dashboard.html")
ENDPOINT = "https://naverapihub.apigw.ntruss.com/search/v1/news"

# docs/keyword-radar.md 「지금 보고 있는 키워드」 표와 같아야 한다.
GROUPS = [
    ("리조트·호캉스", ["호캉스", "워터파크", "풀빌라", "한옥스테이"]),
    ("소노 브랜드",   ["소노벨", "쏠비치", "소노캄", "소노펠리체"]),
    ("경쟁 브랜드",   ["한화리조트", "하이원리조트", "휘닉스파크", "롯데호텔"]),
    ("예약 채널",     ["여기어때", "야놀자", "트립닷컴", "아고다"]),
    ("내 관심 주제",  ["사이드 프로젝트", "퍼스널 브랜딩", "1인 창업", "브랜드 마케팅"]),
    ("농구·필리핀",   ["KBL", "필리핀 농구", "아시안게임 농구", "EASL"]),
]

MAX_PAGES = 10          # 최대 10페이지 = 1,000건 (문서 사양)
DISPLAY = 100
CALLS = [0]
FAILED = []             # 조회 실패는 「실패 + 사유」로 남긴다. 0 으로 채우지 않는다.


def _cred():
    return cred(".naver.json", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")


def search(q, start=1):
    cid, csec = _cred()
    CALLS[0] += 1
    url = ENDPOINT + "?" + urllib.parse.urlencode(
        {"query": q, "display": DISPLAY, "start": start, "sort": "date"})
    req = urllib.request.Request(url, headers={
        "X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": csec})
    with urllib.request.urlopen(req, timeout=20) as f:
        return json.load(f).get("items", [])


def clean(s):
    s = re.sub(r"<[^>]+>", "", s)
    return (s.replace("&quot;", '"').replace("&amp;", "&")
             .replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'").strip())


def variants(kw):
    """띄어쓰기 변형. 「한화리조트」와 「한화 리조트」를 같은 것으로 본다."""
    v = {kw, kw.replace(" ", "")}
    if " " not in kw and len(kw) >= 4:
        for i in range(2, len(kw) - 1):
            v.add(kw[:i] + " " + kw[i:])
    return v


def literal_hit(kw, text):
    """검색 엔진이 단어를 쪼개 매칭하므로 키워드가 **문자 그대로** 있는 것만 센다.
    (「롯데호텔」로 부르면 롯데 울산 공장 기사가 섞여 들어온다.)"""
    t = text.replace(" ", "")
    return any(x.replace(" ", "") in t for x in variants(kw))


def parse_pub(s):
    """RFC 822 → date. 실패하면 None (추정하지 않는다)."""
    try:
        return datetime.datetime.strptime(s[:25].strip(), "%a, %d %b %Y %H:%M:%S").date()
    except ValueError:
        return None


def collect(kw, cur_from, cur_to, prev_from, prev_to):
    """한 키워드의 (이번주 건수, 앞주 건수, 이번주 상위 3건)."""
    cur, prev, top, seen, err = 0, 0, [], set(), None
    for page in range(MAX_PAGES):
        start = page * DISPLAY + 1
        if start > 901:
            break
        try:
            items = search(kw, start)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"    [조회 실패] {kw} start={start} — {err}")
            break
        if not items:
            break
        oldest = None
        for it in items:
            d = parse_pub(it.get("pubDate", ""))
            if d is None:
                continue
            oldest = d if oldest is None else min(oldest, d)
            title, desc = clean(it["title"]), clean(it["description"])
            if not literal_hit(kw, title + " " + desc):
                continue
            link = it.get("originallink") or it.get("link") or ""
            if prev_from <= d <= prev_to:
                prev += 1
            elif cur_from <= d <= cur_to:
                cur += 1
                if link and link not in seen and len(top) < 3:
                    seen.add(link)
                    top.append({"t": title[:44] + ("..." if len(title) > 44 else ""),
                                "u": link})
        if oldest and oldest < prev_from:
            break
        time.sleep(0.05)
    if err:
        FAILED.append((kw, err))
    return cur, prev, top, err


def week_range(sunday=None):
    """기준 주(월~일). 인자가 없으면 「가장 최근에 끝난 주」."""
    today = datetime.date.today()
    if sunday:
        end = datetime.date(*map(int, sunday.split("-")))
    else:
        end = today - datetime.timedelta(days=(today.weekday() + 1) % 7)
        if end == today and today.weekday() != 6:
            end = today - datetime.timedelta(days=7)
    start = end - datetime.timedelta(days=6)
    return start, end


def build(sunday=None):
    cur_from, cur_to = week_range(sunday)
    prev_to = cur_from - datetime.timedelta(days=1)
    prev_from = prev_to - datetime.timedelta(days=6)
    print(f"[radar] 이번 주 {cur_from} ~ {cur_to} · 앞 주 {prev_from} ~ {prev_to}")

    groups = []
    for name, kws in GROUPS:
        row = {"name": name, "kw": []}
        for kw in kws:
            cur, prev, top, err = collect(kw, cur_from, cur_to, prev_from, prev_to)
            delta = "" if prev == 0 else f" ({(cur - prev) / prev * 100:+.0f}%)"
            print(f"  {name} · {kw}: {cur}건{delta} (앞주 {prev})")
            item = {"n": kw, "cur": cur, "prev": prev, "top": top}
            if err:
                item["err"] = err          # 실패는 화면에도 사실로 남긴다
            row["kw"].append(item)
        groups.append(row)

    plan = {
        "status": "live-news",
        "updated": datetime.date.today().isoformat(),
        "weekFrom": cur_from.isoformat(),
        "weekTo": cur_to.isoformat(),
        "calls": CALLS[0],
        "groups": groups,
    }
    if FAILED:
        plan["failed"] = [{"n": k, "why": w} for k, w in FAILED]
    return plan


def apply(plan, path=DASHBOARD):
    """dashboard.html 의 TREND_PLAN 을 통째로 갈아 끼운다."""
    s = open(path, encoding="utf-8").read()
    i = s.find("const TREND_PLAN")
    if i < 0:
        raise SystemExit("TREND_PLAN 앵커를 찾지 못했다 — 화면 구조가 바뀌었는지 확인할 것")
    b = s.index("=", i) + 1
    while s[b].isspace():
        b += 1
    d, k = 0, b
    while k < len(s):
        if s[k] in "[{":
            d += 1
        elif s[k] in "]}":
            d -= 1
            if d == 0:
                break
        k += 1
    body = json.dumps(plan, ensure_ascii=False, indent=1)
    out = s[:b] + body + s[k + 1:]
    open(path, "w", encoding="utf-8").write(out)
    return len(body)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    plan = build(arg)
    n = apply(plan)
    kw_n = sum(len(g["kw"]) for g in plan["groups"])
    print(f"\n[radar] TREND_PLAN 갱신 — {plan['weekFrom']}~{plan['weekTo']} · "
          f"{kw_n}키워드 · {plan['calls']}콜 · {n}바이트")
    if FAILED:
        print(f"[radar] 조회 실패 {len(FAILED)}건 — " +
              ", ".join(f"{k}({w[:40]})" for k, w in FAILED))
    try:
        import apiusage
        apiusage.sync_radar()
        print("[apiusage] 레이더 콜 동기화 완료")
    except Exception as e:
        print(f"[apiusage] 동기화 건너뜀 — {e}")
