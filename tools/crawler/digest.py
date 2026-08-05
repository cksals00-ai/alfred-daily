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
    "날씨·기후": r"(폭염|열대야|무더위|호우|장맛?비|장마|태풍(?!상사)|한파|가뭄|기상청|기온|소나기|미세먼지|폭우|폭설|온열질환|고수온|산불|이상기후|기후변화)",
    "사회·생활": r"(취업|일자리|연금|출산|저출생|고령|의료|응급|병원|의대|학교|교육|입시|복지|육아|주 ?4일|노동|임금|건강보험)",
    "문화·스포츠": r"(영화|박스오피스|관객|드라마|배우|가수|앨범|공연|전시|축제|영화제|야구|축구|배구|농구|골프|리그|대표팀|올림픽|우승|메달|감독)",
}
# 초점 — 슬롯이 넓어진 카테고리는 '그 사건 자체'를 다뤄야 한다.
# 씨앗어만 걸치고 실제로는 상품·마케팅인 기사('폭염에 아이스크러시 3종 선봬')를 막는다.
# 여기 없는 카테고리는 초점 검사를 하지 않는다.
FOCUS = {
    "날씨·기후": r"(기상청|경보|주의보|특보|열대야|태풍|호우|폭우|폭설|한파|가뭄|산불|"
                r"장마|\d+\s*도(?![가-힣])|기온|사망|환자|피해|이재민|실종|온열질환|고수온)",
}
# 알프레드 축 — 재현물 위에 따로 태깅해서 대시보드가 뽑아 쓴다
MY_AXIS = ["여행", "호텔", "리조트", "레저", "항공", "숙박", "관광", "워터파크", "스키",
           "야놀자", "여기어때", "OTA", "국제유가", "환율", "폭염", "열대야", "내수", "소비심리", "숙박쿠폰"]

STOP = set("있다 했다 한다 대한 위해 관련 이날 오늘 우리 지난 대해 통해 밝혔다 라며 지난해 올해".split())

# ── 탄력 배분 ────────────────────────────────────────────────
# 고정 슬롯은 '한 이슈가 그날 지면을 삼키는 날'을 구조적으로 못 따라간다.
# 8/5 원문은 17꼭지 중 8꼭지가 폭염·기후였는데 날씨 슬롯은 1이었다.
# 그래서 전날 원문의 카테고리 점유율을 읽어 다음 날 슬롯을 늘린다.
SHARE_TRIGGER = 1 / 3      # 한 카테고리가 전날 원문의 1/3을 넘으면 발동
BOOST_CAP = 5              # 늘릴 수 있는 상한
STRETCH = 1                # 발동일에 한해 총 꼭지수를 16 → 17까지 허용
DONORS = ["문화·스포츠", "사회·생활", "부동산"]   # 줄이는 순서(바닥 0)
# 동점일 때는 '넓은 카테고리'가 아니라 '좁은 카테고리'를 택한다.
# 정치·국회·사건·사고 가드는 사실상 모든 기사에 걸리는 포괄어라 동점 승자가 되면 안 된다.
SPECIFICITY = ["날씨·기후", "부동산", "경제·시장", "문화·스포츠",
               "사회·생활", "국제·안보", "사건·사고", "정치·국회"]


def classify(text):
    """원문 한 꼭지를 카테고리 하나로 배정한다. 가드 히트 종류 수 → 좁은 쪽 순."""
    best, score = None, 0
    for cat in SPECIFICITY:
        s = len(set(re.findall(GUARD[cat], text)))
        if s > score:                     # 동점이면 먼저 온(좁은) 카테고리가 이긴다
            best, score = cat, s
    return best


def wonmun_shares(path=None, before=None):
    """가장 최근 원문(정본) 하루치의 카테고리 점유율. 원문이 없으면 (None, {}, 0)."""
    path = path or os.path.join(PUBLIC, "news.json")
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None, {}, 0
    rows = [r for r in rows if r.get("src") == "원문"
            and (before is None or r["date"] < before)]
    if not rows:
        return None, {}, 0
    row = max(rows, key=lambda r: r["date"])
    items = [t.strip() for t in row["text"].split("■")[1:] if t.strip()]
    if not items:
        return row["date"], {}, 0
    cnt = collections.Counter(classify(t) for t in items)
    cnt.pop(None, None)
    n = len(items)
    return row["date"], {k: v / n for k, v in cnt.items()}, n


def elastic_slots(base=None, path=None, before=None):
    """전날 원문 점유율로 슬롯을 재배분한다. 반환: (슬롯목록, 총꼭지수, 설명)."""
    base = base or SLOTS
    slots = [list(x) for x in base]
    idx = {c: i for i, (c, _) in enumerate(slots)}
    date, share, n = wonmun_shares(path, before)
    if not share:
        return [tuple(x) for x in slots], TARGET_ITEMS, "탄력 배분 미발동(기준 원문 없음)"

    cat, top = max(share.items(), key=lambda kv: kv[1])
    if top <= SHARE_TRIGGER or cat in DONORS:
        return ([tuple(x) for x in slots], TARGET_ITEMS,
                f"탄력 배분 미발동 — 기준 {date} 최대 {cat} {top:.0%} ≤ {SHARE_TRIGGER:.0%}")

    want = min(BOOST_CAP, max(slots[idx[cat]][1] + 1, round(top * TARGET_ITEMS)))
    need = need0 = want - slots[idx[cat]][1]
    gave = []
    for d in DONORS:                       # 알프레드가 지정한 기증 순서
        if need <= 0:
            break
        i = idx[d]
        cut = min(need, slots[i][1])
        if cut:
            slots[i][1] -= cut; need -= cut; gave.append(f"{d}−{cut}")
    total = TARGET_ITEMS
    if need > 0:                           # 기증분으로 모자라면 그날만 총량을 늘린다
        s = min(need, STRETCH)
        total += s; need -= s; gave.append(f"총량+{s}")
    slots[idx[cat]][1] += need0 - need      # 실제로 확보한 만큼만 늘린다
    assert sum(n for _, n in slots) == total, (slots, total)
    return ([tuple(x) for x in slots], total,
            f"탄력 배분 발동 — 기준 {date}({n}꼭지) {cat} {top:.0%} → "
            f"슬롯 {base[idx[cat]][1]}→{slots[idx[cat]][1]} ({', '.join(gave)})")


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


def stems(s):
    """조사를 떼어낸 제목 토큰. '태풍'과 '태풍도', '폭염'과 '극한폭염'을 잇는다.

    한국어는 조사가 붙어 같은 낱말이 다른 토큰이 된다. 뒤에서 한 글자(≥3자)·
    두 글자(≥5자)를 떼어 함께 넣고, 4자 이상은 앞 두 글자도 넣어 합성어를 잇는다.
    """
    k = set()
    for w in toks(s):
        k.add(w)
        if len(w) >= 3:
            k.add(w[:-1])
        if len(w) >= 5:
            k.add(w[:-2])
        if len(w) >= 4:
            k.add(w[-2:])          # 극한폭염 → 폭염
    return {x for x in k if len(x) >= 2}


def dup_title(a, b):
    """제목만으로 같은 사건인지 — 본문이 섞이면 겹침 비율이 희석돼 중복이 새어 나간다."""
    inter = a & b
    return len(inter) >= 3 and len(inter) / max(1, min(len(a), len(b))) >= 0.3


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


# 보도자료 — 슬롯을 넓히면 씨앗('폭염')에 기업 홍보물이 대량으로 걸린다.
# 8/6 드라이런에서 날씨 5칸 중 3칸이 LH·삼성전자·농협손보 홍보물이었다.
PR_ACT = re.compile(
    r"(캠페인|이벤트|공모전|간담회|업무협약|MOU|맞손|기부|후원|증정|무상|나눔|"
    r"출시|선보여|선보인|선봬|공개했?다|제시|실시|진행|돌입|박차|앞장|총력|비축|"
    r"사회공헌|ESG|브랜드|프로모션|할인|특가|런칭|체험단|서포터즈)")
PR_ACTOR = re.compile(
    r"(㈜|주식회사|[가-힣A-Za-z]+(전자|건설|생명|손보|화재|카드|은행|증권|제약|"
    r"백화점|면세점|모빌리티|텔레콤|바이오|엔터|호텔앤?리조트)|"
    r"^(LH|KT|SK|LG|GS|CJ|SPC|BGF|HD현대|포스코|현대차|기아|한화|롯데|신세계|농협|수협))")


def is_pr(it):
    """행위 주체가 기업·기관이고 동사가 홍보 동사면 보도자료로 본다."""
    t = it["title"]
    if not PR_ACT.search(t):
        return False
    return bool(PR_ACTOR.search(t))


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
            if is_junk(it) or is_pr(it):
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
        f = FOCUS.get(cat)
        if f and not re.search(f, head["title"]):
            continue                      # 씨앗어만 걸친 상품·마케팅 기사
        out.append({
            "cat": cat, "weight": len(body),
            "toks": toks(head["title"] + " " + head["desc"][:60]),
            "ttoks": stems(head["title"]),
            "title": head["title"], "desc": head["desc"], "link": head["link"],
            "mine": [k for k in MY_AXIS
                     if re.search(r"(?<![가-힣])" + re.escape(k), head["title"] + head["desc"])],
        })
    return sorted(out, key=lambda x: -x["weight"])


def build(date=None):
    date = date or kst_today()
    slots, target, why = elastic_slots(before=date)   # 전날 원문 기준 탄력 배분
    print("[slots] " + why + " · " +
          " ".join(f"{c}{n}" for c, n in slots) + f" = {target}")
    cands = {cat: candidates(cat) for cat, _ in slots}
    picked, seen = [], set()

    def take(c):
        if c["title"] in seen:
            return False
        if any(same_story(c["toks"], p["toks"]) or dup_title(c["ttoks"], p["ttoks"])
               for p in picked):
            return False          # 다른 카테고리에서 이미 뽑힌 사건
        seen.add(c["title"]); picked.append(c)
        return True

    for cat, n in slots:                       # 1차 — 배정된 슬롯을 채운다
        got = 0
        for c in cands[cat]:
            if got >= n:
                break
            if take(c):
                got += 1
    for cat, _ in slots:                       # 2차 — 모자란 만큼 보도량 순으로 메운다
        for c in cands[cat]:
            if len(picked) >= target:
                break
            take(c)

    out = picked[:target]
    for i in out:
        i.pop("toks", None); i.pop("ttoks", None)
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
