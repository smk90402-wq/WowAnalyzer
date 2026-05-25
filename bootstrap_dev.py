"""다른 PC 에서 clone/pull 후 한 번 실행하는 셋업 스크립트.

수행:
  1) git lfs install + git lfs pull  (data/v2_cache_*.json LFS 파일 받기)
  2) pip install -r requirements.txt
  3) .env 없으면 .env.example 복사 + 키 채우기 안내
  4) dist/LogAnalyze 있으면 data junction + .env 복사 (Windows 한정)

사용:
    python bootstrap_dev.py

문제 시:
  - "git lfs" 명령 없음 → https://git-lfs.com 에서 설치 후 다시 실행
  - .env 키 모름 → 메인 PC 의 keys_local.txt 옮기거나 .env 통째로 복사
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()


def run(cmd: list[str], **kw) -> int:
    """명령 실행 — stdout/stderr 그대로 노출."""
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT, **kw)


def step(n: int, total: int, msg: str) -> None:
    print(f"\n{'='*60}\n[{n}/{total}] {msg}\n{'='*60}")


def check_git_lfs() -> bool:
    try:
        r = subprocess.run(["git", "lfs", "version"], cwd=ROOT,
                           capture_output=True, text=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def setup_lfs() -> None:
    step(1, 4, "Git LFS — v2_cache_*.json (380MB+) 받기")
    if not check_git_lfs():
        print("!! git lfs 명령 없음.")
        print("   https://git-lfs.com 에서 설치 후 다시 실행하세요.")
        print("   (Windows: 'winget install GitHub.GitLFS' 또는 인스톨러)")
        sys.exit(1)
    run(["git", "lfs", "install"])
    print("\nLFS 파일 다운로드 — 대용량 (380MB+) 이라 수~십 분 소요 가능...")
    rc = run(["git", "lfs", "pull"])
    if rc != 0:
        print("!! git lfs pull 실패 — 네트워크 확인 후 재시도")
        sys.exit(1)


def install_deps() -> None:
    step(2, 4, "Python 의존성 설치 (requirements.txt)")
    rc = run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    if rc != 0:
        print("!! pip install 실패")
        sys.exit(1)


def setup_env() -> None:
    step(3, 4, ".env 키 파일")
    env = ROOT / ".env"
    example = ROOT / ".env.example"
    if env.exists():
        print(f"   .env 이미 존재 — skip")
        return
    if not example.exists():
        print("!! .env.example 없음 — 수동으로 .env 만드세요")
        return
    shutil.copy(example, env)
    print(f"   .env.example → .env 복사 완료.")
    print(f"   {env} 열어서 4개 키 (WCL_V2_*, BLIZZARD_*) 채워주세요.")
    print(f"   메인 PC 에 keys_local.txt 있으면 거기서 그대로 복붙.")


def setup_dist_links() -> None:
    step(4, 4, "dist/LogAnalyze 데이터/환경 링크 (있을 때만)")
    dist = ROOT / "dist" / "LogAnalyze"
    if not dist.exists():
        print("   dist/LogAnalyze 없음 — 빌드 안 됐으면 건너뜀.")
        print("   빌드 시: python build_exe.py  (또는 build.bat)")
        return
    # data junction
    data_link = dist / "data"
    data_target = ROOT / "data"
    if not data_link.exists() and data_target.exists():
        if os.name == "nt":
            # Windows junction
            rc = run(["cmd", "/c", "mklink", "/J",
                      str(data_link), str(data_target)])
            if rc != 0:
                print(f"!! junction 생성 실패 — 수동: cd dist\\LogAnalyze && "
                      f"mklink /J data ..\\..\\data")
        else:
            # POSIX symlink
            data_link.symlink_to(data_target)
            print(f"   {data_link} → {data_target} symlink 생성")
    else:
        print(f"   data link 이미 존재 또는 source 없음 — skip")
    # .env 복사
    dist_env = dist / ".env"
    src_env = ROOT / ".env"
    if not dist_env.exists() and src_env.exists():
        shutil.copy(src_env, dist_env)
        print(f"   .env → dist/LogAnalyze/.env 복사 완료")
    else:
        print(f"   dist .env 이미 존재 또는 source 없음 — skip")


def main() -> None:
    print(f"WowAnalyzer dev bootstrap @ {ROOT}\n")
    setup_lfs()
    install_deps()
    setup_env()
    setup_dist_links()
    print(f"\n{'='*60}\n셋업 완료.\n{'='*60}")
    print("다음 단계:")
    print("  - 코드 실행: python serve.py")
    print("  - .exe 빌드:  python build_exe.py  (또는 build.bat)")
    print("  - 빌드된 거 실행: run.bat  또는  dist\\LogAnalyze\\LogAnalyze.exe")


if __name__ == "__main__":
    main()
