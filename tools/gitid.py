# -*- coding: utf-8 -*-
"""커밋 작성자를 레포 쪽에서 강제한다.

예약작업 프롬프트에는 「커밋 전에 git config user.email noreply@anthropic.com 을 걸어라」가
적혀 있다. 그런데 프롬프트 지시는 지켜질 때도 있고 아닐 때도 있다 — 2026-07-31(b3af2b8)과
2026-08-09(95a3155) 두 번은 지켜지지 않아 `Higgsfield Agent <agent@higgsfield.ai>` 로
커밋이 올라갔고 GitHub 에서 Unverified 로 표시됐다.

지시를 더 크게 적는 대신 **실행되게** 만든다. 예약작업이 반드시 부르는 스크립트들이
시작할 때 이 모듈을 부르면, 그 컨테이너의 레포에는 커밋 전에 항상 올바른 작성자가 걸린다.
프롬프트를 고칠 필요도, 거기 든 자격증명을 옮길 필요도 없다.

사용:
    from gitid import ensure          # tools/ 가 sys.path 에 있을 때
    ensure()
    python3 tools/gitid.py           # 단독 실행도 된다
"""
import os
import subprocess
import sys

EMAIL = "noreply@anthropic.com"
NAME = "Claude"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _get(key, cwd):
    r = subprocess.run(["git", "config", "--get", key],
                       cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip()


def ensure(cwd=None, verbose=True):
    """레포의 user.email/user.name 을 올바르게 맞춘다. 이미 맞으면 아무것도 안 한다.

    git 이 없거나 레포가 아니면 조용히 넘어간다 — 이 함수 때문에 수집이 죽으면 안 된다.
    반환값: True(설정을 걸었거나 이미 맞음) / False(못 걸었음).
    """
    cwd = cwd or REPO_ROOT
    try:
        if not os.path.isdir(os.path.join(cwd, ".git")):
            if verbose:
                print(f"[gitid] {cwd} 는 git 레포가 아니다 — 건너뜀")
            return False
        cur_e, cur_n = _get("user.email", cwd), _get("user.name", cwd)
        if cur_e == EMAIL and cur_n == NAME:
            return True
        subprocess.run(["git", "config", "user.email", EMAIL], cwd=cwd, check=True)
        subprocess.run(["git", "config", "user.name", NAME], cwd=cwd, check=True)
        if verbose:
            was = f"{cur_n or '(없음)'} <{cur_e or '(없음)'}>"
            print(f"[gitid] 커밋 작성자 설정: {was} → {NAME} <{EMAIL}>")
        return True
    except Exception as e:                      # git 미설치·권한 등
        if verbose:
            print(f"[gitid] 설정 실패 — {e}")
        return False


if __name__ == "__main__":
    ok = ensure()
    print(f"[gitid] user.email={_get('user.email', REPO_ROOT)} "
          f"user.name={_get('user.name', REPO_ROOT)}")
    sys.exit(0 if ok else 1)
