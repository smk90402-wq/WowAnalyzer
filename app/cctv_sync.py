"""캡처 폴더(E:\\cctv)가 없는 PC용 R2 폴백 동기화.

scripts/cctv_push*.ps1 이 올린 r2:wowanalyzer-cctv 를 data/cctv_r2/ 로 미러링:
  - cctv/  : 캡처 json (목록용 — 작아서 동기 다운로드)
  - logs/  : WoWCombatLog*.txt (리플레이 재생용 — 수백 MB라 백그라운드 스레드)
영상(mp4)은 GB급이라 자동으로 받지 않음 — 목록에 '영상 없음'으로 표시됨.
rclone 미설치/미설정이면 조용히 아무것도 안 함 (기존 동작 유지).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# frozen(PyInstaller exe)에서는 __file__ 이 _internal 안을 가리킴 — repo 표준 패턴 (replay_map 참고)
if getattr(sys, "frozen", False):
    DATA = Path(sys.executable).parent / "data"
else:
    DATA = Path(__file__).resolve().parent.parent / "data"
MIRROR = DATA / "cctv_r2"
REMOTE = "r2:wowanalyzer-cctv"
_TTL_S = 600

_last_sync = 0.0
_logs_thread: threading.Thread | None = None

# 창모드(PyInstaller --windowed) 앱에서 stdin 핸들이 무효라 subprocess 가 죽는 함정 —
# 모든 rclone 호출에 stdin=DEVNULL + 콘솔창 억제 플래그를 강제.
_RUN_KW: dict = {"stdin": subprocess.DEVNULL}
if os.name == "nt":
    _RUN_KW["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def invalidate() -> None:
    """미러/원격 목록 캐시 무효화 — UI 새로고침에서 강제 재동기화."""
    global _last_sync, _remote_files
    _last_sync = 0.0
    _remote_files = None


def _rclone() -> str | None:
    from shutil import which
    exe = which("rclone")
    if exe:
        return exe
    cand = (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
            / "Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe"
            / "rclone-v1.74.4-windows-amd64/rclone.exe")
    return str(cand) if cand.exists() else None


def available() -> bool:
    conf = Path(os.environ.get("APPDATA", "")) / "rclone" / "rclone.conf"
    return conf.exists() and _rclone() is not None


def _copy(src: str, dst: Path, *args: str, timeout: int = 900) -> bool:
    exe = _rclone()
    if not exe:
        return False
    dst.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([exe, "copy", src, str(dst), "--update", *args],
                           capture_output=True, timeout=timeout, **_RUN_KW)
        return r.returncode == 0
    except Exception:
        return False


def _sync_logs_bg() -> None:
    _copy(f"{REMOTE}/logs", MIRROR / "logs")


def ensure_mirror() -> Path:
    """미러 최신화(TTL 10분) 후 캡처 디렉터리 반환. 로그는 백그라운드로 내려받음."""
    global _last_sync, _logs_thread
    now = time.monotonic()
    if available() and (now - _last_sync > _TTL_S):
        _last_sync = now
        # 캡처 json 만 동기(작음) — 목록이 바로 뜨게
        _copy(f"{REMOTE}/cctv", MIRROR / "cctv", "--include", "*.json", timeout=120)
        # 전투로그는 백그라운드 (첫 재생 전까지 내려오면 됨)
        if _logs_thread is None or not _logs_thread.is_alive():
            _logs_thread = threading.Thread(target=_sync_logs_bg, daemon=True)
            _logs_thread.start()
    return MIRROR / "cctv"


def mirror_log_dir() -> Path:
    return MIRROR / "logs"


_remote_files: tuple[float, list[str]] | None = None


def remote_files() -> list[str]:
    """r2:…/cctv 파일 목록 (10분 캐시) — 원격 영상 존재 확인용. 실패 시 []."""
    global _remote_files
    now = time.monotonic()
    if _remote_files and now - _remote_files[0] < _TTL_S:
        return _remote_files[1]
    exe = _rclone()
    if not exe or not available():
        return []
    try:
        r = subprocess.run([exe, "lsf", f"{REMOTE}/cctv"],
                           capture_output=True, timeout=60, **_RUN_KW)
        if r.returncode != 0:
            return []          # 실패는 캐시하지 않음 — 다음 호출에서 재시도
        names = r.stdout.decode("utf-8", "replace").splitlines()
    except Exception:
        return []
    _remote_files = (now, names)
    return names


def presign(name: str, expire: str = "6h") -> str | None:
    """cctv/<name> 의 presigned GET URL — 브라우저가 R2에서 직접 스트리밍(구간 요청)."""
    exe = _rclone()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "link", f"{REMOTE}/cctv/{name}", "--expire", expire],
                           capture_output=True, timeout=30, **_RUN_KW)
        url = r.stdout.decode("utf-8", "replace").strip()
        return url if r.returncode == 0 and url.startswith("http") else None
    except Exception:
        return None
