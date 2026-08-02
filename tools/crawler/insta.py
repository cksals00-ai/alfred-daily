# -*- coding: utf-8 -*-
"""리아 인스타그램 수집기 — Meta Graph API → app/public/insta.json

토큰은 저장소 밖 ../.insta.json 에만 둔다. 공개 대시보드에는 절대 넣지 않는다.
  { "token": "<long-lived access token>", "ig_user_id": "<IG 비즈니스 계정 ID>" }

메타는 지표 이름을 자주 갈아치운다(impressions·plays 폐기 등). 그래서 지표를
'되는 것만 골라 쓰는' 방식으로 요청한다 — 묶어서 한 번 던져보고, 거절당하면
하나씩 따로 던져 살아남은 것만 취한다. 없는 지표는 없는 대로 두고, 절대
추정값으로 채우지 않는다.
"""
import json, os, statistics, urllib.request, urllib.parse, urllib.error, datetime, collections

HERE = os.path.dirname(os.path.abspath(__file__))
import sys; sys.path.insert(0, HERE)
from _paths import PUBLIC, _CANDIDATES  # noqa: E402


def _find_insta_cred():
    for d in _CANDIDATES:
        p = os.path.join(d, ".insta.json")
        if os.path.exists(p):
            return p
    return os.path.join(_CANDIDATES[0], ".insta.json")

CRED = _find_insta_cred()
ARCHIVE = os.path.join(PUBLIC, "insta.json")

VER = "v23.0"
BASE = "https://graph.facebook.com/" + VER
WINDOW = 30            # 사용자 인사이트는 한 번에 최대 30일
MEDIA_N = 60           # 최근 게시물 수

# 시계열형 — period=day, 날짜별 값이 배열로 온다
M_SERIES = ["reach", "follower_count", "profile_views", "impressions", "website_clicks"]
# 합계형 — metric_type=total_value, 기간 전체의 단일 값
M_TOTAL = ["views", "accounts_engaged", "total_interactions", "likes",
           "comments", "saves", "shares", "replies", "profile_links_taps"]
# 게시물별
M_MEDIA = ["reach", "views", "saved", "shares", "total_interactions",
           "likes", "comments", "impressions", "plays"]

WD = "월화수목금토일"


def cred():
    with open(CRED, encoding="utf-8") as f:
        c = json.load(f)
    return c["token"], str(c["ig_user_id"])


def get(path, token, **params):
    params["access_token"] = token
    url = BASE + "/" + path.lstrip("/") + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "alfred-daily/1.0"})
    with urllib.request.urlopen(req, timeout=25) as f:
        return json.load(f)


def insights(path, token, metrics, **base):
    """되는 지표만 골라 온다. 묶음 요청이 거절되면 하나씩 확인한다."""
    got = {}
    try:
        r = get(path + "/insights", token, metric=",".join(metrics), **base)
        for row in r.get("data", []):
            got[row["name"]] = row
        return got
    except urllib.error.HTTPError:
        pass
    for m in metrics:
        try:
            r = get(path + "/insights", token, metric=m, **base)
            for row in r.get("data", []):
                got[row["name"]] = row
        except urllib.error.HTTPError:
            continue          # 이 계정/이 버전에서 안 되는 지표 — 조용히 건너뛴다
    return got


def _total(row):
    """total_value 형식과 values 배열 형식을 모두 받아 하나의 수로."""
    if "total_value" in row and isinstance(row["total_value"], dict):
        return row["total_value"].get("value")
    vals = [v.get("value") for v in row.get("values", []) if isinstance(v.get("value"), (int, float))]
    return sum(vals) if vals else None


def account(token, uid):
    f = "username,name,followers_count,follows_count,media_count,profile_picture_url,biography"
    a = get(uid, token, fields=f)
    return {k: a.get(k) for k in
            ("username", "name", "followers_count", "follows_count", "media_count", "biography")}


def daily(token, uid, days=WINDOW):
    end = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    since = int((end - datetime.timedelta(days=days)).timestamp())
    until = int(end.timestamp())
    rows = insights(uid, token, M_SERIES, period="day", since=since, until=until)
    by = collections.defaultdict(dict)
    for name, row in rows.items():
        for v in row.get("values", []):
            d = (v.get("end_time") or "")[:10]
            if d and isinstance(v.get("value"), (int, float)):
                by[d][name] = v["value"]
    out = [dict(date=d, **vals) for d, vals in sorted(by.items())]

    tot = insights(uid, token, M_TOTAL, period="day",
                   metric_type="total_value", since=since, until=until)
    totals = {k: _total(v) for k, v in tot.items()}
    totals = {k: v for k, v in totals.items() if v is not None}
    return out, totals


def demographics(token, uid):
    out = {}
    for bd in ("age", "gender", "country", "city"):
        try:
            r = get(uid + "/insights", token, metric="follower_demographics",
                    period="lifetime", metric_type="total_value",
                    breakdown=bd, timeframe="this_month", access_token=token)
        except urllib.error.HTTPError:
            continue
        for row in r.get("data", []):
            res = (row.get("total_value") or {}).get("breakdowns") or []
            for b in res:
                out[bd] = {"/".join(x.get("dimension_values", [])): x.get("value")
                           for x in b.get("results", [])}
    return out


def media(token, uid, n=MEDIA_N):
    f = ("id,caption,media_type,media_product_type,permalink,timestamp,"
         "like_count,comments_count,thumbnail_url,media_url")
    items = get(uid + "/media", token, fields=f, limit=n).get("data", [])
    out = []
    for m in items:
        ins = insights(m["id"], token, M_MEDIA)
        vals = {k: _total(v) for k, v in ins.items()}
        vals = {k: v for k, v in vals.items() if v is not None}
        ts = m.get("timestamp", "")
        try:
            dt = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
            dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
            iso, wd, hr = dt.date().isoformat(), dt.weekday(), dt.hour
        except ValueError:
            iso, wd, hr = "", None, None
        cap = (m.get("caption") or "").strip().replace("\n", " ")
        out.append({
            "id": m["id"], "date": iso, "wd": wd, "hr": hr,
            "type": m.get("media_product_type") or m.get("media_type"),
            "permalink": m.get("permalink"),
            "caption": cap[:110],
            "like": m.get("like_count"), "comment": m.get("comments_count"),
            **vals,
        })
    return out


def _med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 1) if xs else None


def derive(acct, days, totals, posts):
    """대시보드가 그대로 읽을 수 있게 파생 지표까지 파이썬에서 만든다."""
    fc = [d.get("follower_count") for d in days if d.get("follower_count") is not None]
    reach = [d.get("reach") for d in days if d.get("reach") is not None]
    followers = acct.get("followers_count")

    fmt = collections.defaultdict(list)
    for p in posts:
        if p.get("reach") is not None:
            fmt[p["type"] or "기타"].append(p)
    formats = sorted(
        [{"type": k,
          "n": len(v),
          "reach": _med([x.get("reach") for x in v]),
          "saved": _med([x.get("saved") for x in v]),
          "inter": _med([x.get("total_interactions") for x in v])}
         for k, v in fmt.items()],
        key=lambda x: -(x["reach"] or 0))

    slot = collections.defaultdict(list)
    for p in posts:
        if p.get("wd") is not None and p.get("reach") is not None:
            slot[(p["wd"], p["hr"] // 3)].append(p["reach"])
    heat = [{"wd": k[0], "blk": k[1], "n": len(v), "reach": _med(v)}
            for k, v in sorted(slot.items())]

    top = sorted([p for p in posts if p.get("reach") is not None],
                 key=lambda p: -p["reach"])[:8]

    return {
        "followers": followers,
        "net30": sum(fc) if fc else None,
        "reach30": sum(reach) if reach else None,
        "reachRate": (round(sum(reach) / len(reach) / followers * 100, 1)
                      if reach and followers else None),
        "posts30": len([p for p in posts if p["date"] and p["date"] >=
                        (datetime.date.today() - datetime.timedelta(days=30)).isoformat()]),
        "formats": formats, "heat": heat, "top": top, "totals": totals,
    }


def build():
    token, uid = cred()
    acct = account(token, uid)
    days, totals = daily(token, uid)
    posts = media(token, uid)
    demo = demographics(token, uid)
    now = (datetime.datetime.utcnow() + datetime.timedelta(hours=9))
    return {
        "asOf": now.strftime("%Y-%m-%d %H:%M"),
        "account": acct,
        "daily": days,
        "media": posts,
        "demo": demo,
        "sum": derive(acct, days, totals, posts),
        "have": sorted(set().union(*[set(d) for d in days]) - {"date"}) if days else [],
    }


if __name__ == "__main__":
    if not os.path.exists(CRED):
        raise SystemExit("[insta] 자격증명 없음 — ../.insta.json 에 token / ig_user_id 를 넣어라.")
    d = build()
    with open(ARCHIVE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    s = d["sum"]
    print(f"[insta] {d['asOf']} · @{d['account'].get('username')} · "
          f"팔로워 {s['followers']} (30일 {s['net30']:+d})" if s.get("net30") is not None
          else f"[insta] {d['asOf']} · @{d['account'].get('username')}")
    print(f"  일자료 {len(d['daily'])}일 · 게시물 {len(d['media'])}건 · "
          f"수집된 지표 {', '.join(d['have']) or '없음'}")
