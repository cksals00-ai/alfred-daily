# -*- coding: utf-8 -*-
"""아침뉴스 재현기 — 수집(네이버 뉴스 검색 API) → 클러스터링 → 편집 규칙으로 배열.
편집 규칙은 news.json 348일치에서 역산한 값이다.
"""
import json, re, os, urllib.request, urllib.parse, collections, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
from _paths import cred, PUBLIC  # noqa: E402

# ── 348일치에서 역산한 편집 규칙 ──────────────────────────────
TARGET_ITEMS = 16                      # 평균 16.5꼭지
SLOTS = [                              # (카테고리, 배정 꼭지수) — 위치가 곧 중요도
    ("정치·국회", 5),                   # 앞 1~3은 최근 60일 기준 사실상 100% 정치
    ("국제·안보", 3),
    ("경제·시장", 2),
    ("부동산",    1),
    ("사건·사고", 2),
    ("날씨·기후", 1),
    ("사회·생활", 1),
    ("문화·스포츠", 1),
]
SEEDS = {
    "정치·국회": ["대통령", "국회 본회의", "특검", "여야", "국무회의"],
    "국제·안보": ["트럼프", "이란", "중국 외교", "일본 총리", "우크라이나"],
    "경제·시장": ["코스피", "환율", "국제유가", "실적 발표", "반도체", "과징금"],
    "부동산":    ["아파트 매매", "부동산 세제", "전세"],
    "사건·사고": ["구속", "화재", "사고 사망"],
    "날씨·기후": ["폭염", "열대야", "호우", "태풍"],
    "사회·생활": ["청년 취업난", "응급실", "국민연금 개혁", "출산율"],
    "문화·스포츠": ["아시안게임 대표팀", "박스오피스", "프로야구 순위"],
}
# 카테고리 가드 — 검색어가 엉뚱한 맥락에 걸리는 것을 막는다(예: 씨앗 '태풍' → 드라마 '태풍상사').
# 뽑힌 기사의 제목이 이 중 하나를 포함해야 그 카테고리로 인정한다.
GUARD = {
    "정치·국회": r"(대통령|대통령실|국회|본회의|여야|민주당|국민의힘|개혁신당|특검|장관|총리|정부|의원|당대표|원내대표|법안|개정안|선관위|합수본|국정|청문회|예산)",
    "국제·안보": r"(트럼프|미국|美|중국|中|일본|日|러시아|러|우크라|이란|이스라엘|하마스|북한|北|유럽|EU|나토|정상회담|외교|지진|강진|총리|대통령)",
    "경제·시장": r"(코스피|코스닥|증시|뉴욕증시|나스닥|다우|환율|유가|금리|물가|실적|영업이익|매출|주가|공시|과징금|반도체|수출|무역|은행|국채)",
    "부동산":    r"(아파트|집값|전세|월세|분양|부동산|주택|재건축|매매|입주|공급)",
    "사건·사고": r"(구속|송치|검거|체포|영장|기소|화재|불|숨져|사망|사고|추락|붕괴|피의자|수사|경찰|검찰|법원|선고|징역)",
    "날씨·기후": r"(폭염|열대야|무더위|호우|장맛?비|장마|태풍(?!상사)|한파|가뭄|기상청|기온|소나기|미세먼지|폭우|폭설)",
    "사회·생활": r"(취업|일자리|연금|출산|저출생|고령|의료|응급|병원|의대|학교|교육|입시|복지|육아|주 ?4일|노동|임금|건강보험)",
    "문화·스포츠": r"(영화|박스오피스|관객|드라마|배우|가수|앨범|공연|전시|축제|영화제|야구|축구|배구|농구|골프|리그|대표팀|올림픽|우승|메달|감독)",
}
# 알프레드 축 — 재현물 위에 따로 태깅해서 대시보드가 뽑아 쓴다
MY_AXIS = ["여행", "호텔", "리조트", "레저", "항공", "숙박", "관광", "워터파크", "스키",
           "야놀자", "여기어때", "OTA", "국제유가", "환율", "폭염", "열대야", "내수", "소비심리", "숙박쿠폰"]

STOP = set("있다 했다 한다 대한 위해 관련 이날 오늘 우리 지난 대해 통해 밝혔다 라며 지난해 올해".split())


def _cred():
    return cred(".naver.json", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")


def search(q, display=30, sort="date"):
    """NAVER API HUB (네이버 클라우드 플랫폼) 뉴스 검색."""
    cid, csec = _cred()
    url = "https://naverapihub.apigw.ntruss.com/search/v1/news?" + urllib.parse.urlencode(
        {"query": q, "display": display, "sort": sort})
    req = urllib.request.Request(url, headers={
        "X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": csec})
    with urllib.request.urlopen(req, timeout=20) as f:
        return json.load(f).get("items", [])


def clean(s):
    s = re.sub(r"<[^>]+>", "", s)
    return (s.replace("&quot;", '"').replace("&amp;", "&")
             .replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'").strip())


def toks(s):
    return set(w for w in re.findall(r"[가-힣A-Za-z]{2,}", s) if w not in STOP)


def same_story(a, b):
    """자카드 대신 포함도 — 제목 길이가 달라도 고유명사가 겹치면 같은 사건."""
    inter = a & b
    if len(inter) < 2:
        return False
    return len(inter) / max(1, min(len(a), len(b))) >= 0.34


def cluster(items, thresh=None):
    """클러스터 크기 = 그날 그 사건의 보도량 = 중요도."""
    out = []
    for it in items:
        t = toks(it["title"] + " " + it["desc"][:60])
        for c in out:
            if same_story(t, c["toks"]):
                c["items"].append(it); c["toks"] |= t
                break
        else:
            out.append({"toks": t, "items": [it]})
    return sorted(out, key=lambda c: -len(c["items"]))


def kst_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).date().isoformat()


SKIP_TITLE = ("오늘의 주요일정", "주요일정", "인사]", "부고]", "포토]", "사진]", "카드뉴스", "오늘의 운세", "주요 뉴스")


def is_junk(it):
    return any(k in it["title"] for k in SKIP_TITLE)


CREDIT = re.compile(
    r"(\s*/\s*[가-힣A-Za-z0-9]{1,12}\s*$)"      # … /뉴스1  /연합뉴스
    r"|(\s*[\w.\-]+@[\w.\-]+\s*$)"               # … chocrystal@newsis.com
    r"|(\s*=?\s*[가-힣]{2,4}\s*기자\s*$)"        # … 홍길동 기자
    r"|(\s*\[사진[^\]]*\]\s*$)")


def _strip_credit(d):
    prev = None
    while prev != d:
        prev = d
        d = CREDIT.sub("", d).strip()
    return d


def is_caption(it):
    """사진 캡션 기사 제거 — 촬영일자·크레딧으로 끝나는 한 문장짜리 설명글."""
    d = _strip_credit(it["desc"])
    if re.search(r"20\d\d[.\-/]\s?\d{1,2}[.\-/]\s?\d{1,2}\.?$", d):
        return True
    if len(d) < 45:
        return True
    # 사진 설명 특유의 위치 지시 — "박지원(왼쪽) 의원이 … 듣고 있다"
    if re.search(r"\((왼쪽|오른쪽|가운데|왼쪽부터|오른쪽부터)[^)]*\)", d):
        return True
    # 문장이 하나뿐이고 '…하고 있다'로 끝나는 단문
    if d.count(".") <= 1 and re.search(r"[가-힣]고 있다[.…]*$", d):
        return True
    return False


def candidates(cat):
    """카테고리별 후보를 보도량 순으로 만든다. 보도량은 사진 캡션을 뺀 실기사 수."""
    pool = []
    for q in SEEDS[cat]:
        for it in search(q):
            it = {"title": clean(it["title"]), "desc": clean(it["description"]),
                  "link": it.get("originallink") or it["link"], "pub": it["pubDate"]}
            if is_junk(it):
                continue
            pool.append(it)
    out = []
    g = GUARD[cat]
    for c in cluster(pool):
        body = [x for x in c["items"] if not is_caption(x)]
        if not body:
            continue                      # 사진 촬영 이벤트뿐인 클러스터 — 사건이 아니다
        head = next((x for x in body if re.search(g, x["title"])), None)
        if head is None:
            continue                      # 씨앗이 엉뚱한 맥락에 걸린 클러스터
        out.append({
            "cat": cat, "weight": len(body),
            "toks": toks(head["title"] + " " + head["desc"][:60]),
            "title": head["title"], "desc": head["desc"], "link": head["link"],
            "mine": [k for k in MY_AXIS
                     if re.search(r"(?<![가-힣])" + re.escape(k), head["title"] + head["desc"])],
        })
    return sorted(out, key=lambda x: -x["weight"])


def build(date=None):
    date = date or kst_today()
    cands = {cat: candidates(cat) for cat, _ in SLOTS}
    picked, seen = [], set()

    def take(c):
        if c["title"] in seen:
            return False
        if any(same_story(c["toks"], p["toks"]) for p in picked):
            return False          # 다른 카테고리에서 이미 뽑힌 사건
        seen.add(c["title"]); picked.append(c)
        return True

    for cat, n in SLOTS:                       # 1차 — 배정된 슬롯을 채운다
        got = 0
        for c in cands[cat]:
            if got >= n:
                break
            if take(c):
                got += 1
    for cat, _ in SLOTS:                       # 2차 — 모자란 만큼 보도량 순으로 메운다
        for c in cands[cat]:
            if len(picked) >= TARGET_ITEMS:
                break
            take(c)

    out = picked[:TARGET_ITEMS]
    for i in out:
        i.pop("toks", None)
    return {"date": date, "items": out}


def to_text(d):
    dt = datetime.date.fromisoformat(d["date"])
    wd = "월화수목금토일"[dt.weekday()]
    head = f"📮 {dt.strftime('%y')}년 {dt.month}월 {dt.day}일 {wd}요일 간추린 아침뉴스입니다."
    body = "\n\n".join("■ " + i["title"] + ". " + i["desc"] for i in d["items"])
    return head + "\n\n" + body


ARCHIVE = os.path.join(PUBLIC, "digest.json")


def archive(d, path=ARCHIVE):
    """대시보드가 읽는 재현본 아카이브에 오늘치를 넣는다(같은 날짜는 덮어쓴다)."""
    try:
        cur = json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        cur = []
    cur = [x for x in cur if x["date"] != d["date"]] + [d]
    cur.sort(key=lambda x: x["date"])
    json.dump(cur, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return len(cur)


if __name__ == "__main__":
    d = build()
    json.dump(d, open(os.path.join(HERE, "digest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    n = archive(d)
    print(to_text(d))
    print(f"\n[archive] {d['date']} · 총 {n}일치 · {len(d['items'])}꼭지 · "
          f"알프레드 축 {sum(1 for i in d['items'] if i['mine'])}건")
