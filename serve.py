"""WowAnalyzer 신규 UI 진입점 — FastAPI + pywebview.

기존 LogAnalyze.exe (gui.py PySide6 빌드) 와 별도. 마이그레이션 끝나면
gui.py 폐기, 이 파일이 유일한 엔트리.

실행:
  python serve.py                    # GUI 윈도우 + 백엔드 동시
  python serve.py --api-only         # FastAPI 만 (개발 시 브라우저 devtools 용)
  python serve.py --port 9999        # 포트 변경
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import uvicorn

# frozen --windowed 에선 sys.stdout/stderr = None — uvicorn 로깅이 죽음.
# devnull 로 redirect 해서 logging 모듈이 정상 동작하도록.
if sys.stdout is None or sys.stderr is None:
    import io
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()

# stdout UTF-8 (Windows cp949 회피)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# frozen .exe — cwd 를 exe 옆으로 (.env / data/ lookup 정확하게)
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

# FastAPI 앱 직접 import — frozen 에서 string "app.main:app" 동적 로딩 실패 회피
from app.main import app as fastapi_app  # noqa: E402

# ── 디버그 로그 — .exe 옆 logs/ 에 시간별 파일 ──────────────────────────────
# 사용자가 문제 발생 시 첨부할 수 있도록. 최근 20개만 유지.
_BASE_DIR = (Path(sys.executable).parent
             if getattr(sys, "frozen", False)
             else Path(__file__).parent)
LOG_DIR = _BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
_LOG_PATH = LOG_DIR / f"wowanalyzer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# 오래된 로그 정리 (최근 20개만)
_existing = sorted(LOG_DIR.glob("wowanalyzer_*.log"))
for _old in _existing[:-20]:
    try: _old.unlink()
    except Exception: pass

_LOG_FMT = "%(asctime)s %(levelname)-5s %(name)-22s %(message)s"
_LOG_DATEFMT = "%H:%M:%S.%f"

# 파일 핸들러 + (dev 모드만) 콘솔 핸들러
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_root.handlers.clear()

_fh = logging.FileHandler(_LOG_PATH, encoding="utf-8")
_fh.setFormatter(logging.Formatter(_LOG_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
_root.addHandler(_fh)

if not getattr(sys, "frozen", False):
    # dev 모드 — 콘솔에도 출력
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(logging.Formatter(_LOG_FMT, datefmt="%H:%M:%S"))
    _root.addHandler(_sh)

# uvicorn 의 access/error 로거도 같은 파일 핸들러 받게
for _name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
    _lg = logging.getLogger(_name)
    _lg.handlers.clear()
    _lg.propagate = True  # root 로 전달 → 파일 핸들러 통해 기록
    _lg.setLevel(logging.INFO)

log = logging.getLogger("serve")
log.info("=" * 60)
log.info("WowAnalyzer 시작 — frozen=%s log=%s",
         getattr(sys, "frozen", False), _LOG_PATH.name)
log.info("base_dir=%s cwd=%s", _BASE_DIR, os.getcwd())
log.info("=" * 60)

DEFAULT_PORT = 9876  # 충돌 방지 — 다른 dev server 와 안 겹치는 포트


def _start_uvicorn(host: str, port: int) -> threading.Thread:
    """별도 데몬 스레드로 uvicorn 실행. pywebview 메인 스레드 가로채는 거 회피."""
    cfg = uvicorn.Config(fastapi_app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(cfg)

    t = threading.Thread(target=server.run, daemon=True, name="uvicorn")
    t.start()
    # 서버 준비될 때까지 polling (최대 5초)
    import urllib.request
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=0.2)
            log.info("FastAPI 준비 완료 (port %d)", port)
            return t
        except Exception:
            time.sleep(0.1)
    log.warning("FastAPI 5초 안에 응답 없음 — 그래도 계속")
    return t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1",
                    help="바인딩 주소. 0.0.0.0 = 사내망(LAN) 다른 PC 접속 허용")
    ap.add_argument("--api-only", action="store_true",
                    help="윈도우 안 띄움 — curl 로 /api/* 테스트할 때")
    args = ap.parse_args()

    if args.api_only:
        log.info("API only — pywebview 안 띄움. http://%s:%d/api/ping", args.host, args.port)
        uvicorn.run(fastapi_app, host=args.host, port=args.port, log_level="info")
        return

    # 백그라운드로 uvicorn → pywebview 메인 스레드
    _start_uvicorn(args.host, args.port)

    import webview
    log.info("pywebview 윈도우 열기")
    webview.create_window(
        "WoW 한밤 레이드 로그 분석기 (web)",
        url=f"http://127.0.0.1:{args.port}/",
        width=2200, height=1280,
        min_size=(1400, 860),
    )
    webview.start()  # 블로킹

    # 윈도우 종료 시 V2Data 캐시 명시적 flush — atexit 도 등록돼있지만
    # pywebview backend 가 os._exit 호출하면 atexit 못 잡는 경우 대비.
    # 모듈 변수 직접 접근 (from-import 는 import 시점 값 캡처돼서 잘못됨).
    try:
        from app import main as app_main
        if app_main._v2_inst is not None:
            log.info("종료 — V2 cache flush")
            app_main._v2_inst.flush()
    except Exception as e:
        log.warning("flush 실패: %s", e)


if __name__ == "__main__":
    # frozen --windowed 에선 stderr 가 안 보임. crash 시 traceback 을 파일로.
    try:
        main()
    except Exception:
        import traceback
        try:
            base = (os.path.dirname(sys.executable)
                    if getattr(sys, "frozen", False)
                    else os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(base, "crash.log"), "w", encoding="utf-8") as fh:
                fh.write(traceback.format_exc())
        except Exception:
            pass
        raise
