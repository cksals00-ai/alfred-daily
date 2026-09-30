"""맥 호스트 파이프라인 신선도 체크 — AI 없이 GitHub 커밋 날짜만 본다.

Claude 예약 「Competitor crawling」·「Rm fcst booking update」(로컬 폴더 확인 전용)를 대체한다.
맥 launchd 잡이 크롤·빌드 후 공개 저장소에 푸시하므로, 해당 파일의 마지막 커밋 시각이
기준 시간보다 오래됐으면 파이프라인이 멈춘 것으로 판정한다.

종료 코드: 0 정상, 1 이상(stale 또는 조회 실패). 결과 요약은 stdout과 $GITHUB_STEP_SUMMARY에 남긴다.
"""
import datetime as dt
import json
import os
import sys
import urllib.request

OWNER = "cksals00-ai"

# (이름, 저장소, 경로(None이면 저장소 전체), 허용 시간)
CHECKS = [
    ("Daily Booking 반영", "gs_daily_trend_news_public_temp", "data/daily_booking.json", 72),
    ("RM FCST 반영", "gs_daily_trend_news_public_temp", "data/rm_fcst.json", 96),
    ("경쟁사 분석 반영", "gs_daily_trend_news_public_temp", "docs/data/competitor_analysis.json", 48),
    ("경쟁사 크롤러 커밋", "sono-competitor-crawler", None, 48),
]


def last_commit(repo, path):
    url = f"https://api.github.com/repos/{OWNER}/{repo}/commits?per_page=1"
    if path:
        url += f"&path={path}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    if not data:
        raise RuntimeError("커밋 없음")
    return dt.datetime.fromisoformat(data[0]["commit"]["committer"]["date"].replace("Z", "+00:00"))


def main():
    now = dt.datetime.now(dt.timezone.utc)
    kst = dt.timezone(dt.timedelta(hours=9))
    lines, bad = [], 0
    for name, repo, path, max_h in CHECKS:
        try:
            ts = last_commit(repo, path)
            age_h = (now - ts).total_seconds() / 3600
            ok = age_h <= max_h
            mark = "✅" if ok else "⚠️"
            lines.append(f"{mark} {name}: 마지막 {ts.astimezone(kst):%m/%d %H:%M} KST ({age_h:.0f}시간 전, 기준 {max_h}시간)")
        except Exception as e:  # 조회 실패도 이상으로 본다
            ok = False
            lines.append(f"⚠️ {name}: 조회 실패 ({e})")
        bad += not ok

    header = "✅ 호스트 파이프라인 정상" if not bad else f"⚠️ PROBLEM {bad}건 — 맥에서 ./scripts/host_daily_crawl.sh 또는 ./daily_update.sh 수동 실행 확인"
    report = "\n".join([header, *lines])
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report.replace("\n", "  \n") + "\n")
    with open("/tmp/freshness_report.md", "w", encoding="utf-8") as f:
        f.write(report + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
