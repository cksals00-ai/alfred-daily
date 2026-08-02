# -*- coding: utf-8 -*-
"""레포 안에서 실행될 때의 경로·자격증명 해석.

예약작업은 매번 새 컨테이너에서 레포를 클론해 돌린다. 그래서 스크립트는 레포
안에 있어야 하고(=이 폴더), 자격증명은 레포 밖에서 와야 한다(레포는 공개다).
자격증명 우선순위: 환경변수 → 홈/작업폴더의 .json 파일. 어느 쪽도 없으면
추정하지 않고 예외를 낸다 — 0으로 채우거나 빈 결과를 정상으로 위장하지 않는다.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PUBLIC = os.path.join(REPO_ROOT, "app", "public")

_CANDIDATES = ["/home/claude/work", os.path.expanduser("~"), os.getcwd()]


def cred(name, env_id, env_secret):
    """name: '.naver.json' 같은 파일명. 반환: (client_id, client_secret)"""
    cid, csec = os.environ.get(env_id), os.environ.get(env_secret)
    if cid and csec:
        return cid, csec
    for d in _CANDIDATES:
        p = os.path.join(d, name)
        if os.path.exists(p):
            c = json.load(open(p, encoding="utf-8"))
            return c["client_id"], c["client_secret"]
    raise RuntimeError(
        f"자격증명 없음: {env_id}/{env_secret} 환경변수도, {name} 파일도 찾지 못했다. "
        f"찾아본 곳: {_CANDIDATES}")
