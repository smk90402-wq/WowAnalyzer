---
name: 매 답변마다 .exe 빌드
description: 모든 응답 끝에 PyInstaller로 LogAnalyze.exe (serve.py) 빌드
type: feedback
---

**규칙**: 매 답변(turn) 끝에 다음 명령으로 .exe 재빌드:

```
python -m PyInstaller --noconfirm --windowed --name LogAnalyze ^
  --add-data "app/static;app/static" ^
  --collect-submodules uvicorn --collect-submodules webview ^
  --hidden-import "uvicorn.loops.auto" ^
  --hidden-import "uvicorn.protocols.http.auto" ^
  --hidden-import "uvicorn.protocols.websockets.auto" ^
  --hidden-import "uvicorn.lifespan.on" ^
  serve.py
```

**2026-05-21 cutover**: PySide6 (gui.py) → web (serve.py + FastAPI + pywebview + app/static). 산출물 크기 930MB → ~36MB (1/25). `gui.py`, `themes.py` 폐기. 사용자가 명시적으로 Option B 선택 + Week 1~3 마이그레이션 완료.

**Why:** 사용자가 명시적으로 선택. 1~2분 추가 비용을 알면서도 "매 답변 돌려" 라고 확정. 본인이 만든 .exe 를 매번 즉시 더블클릭해서 테스트하고 싶어함.

**How to apply:**
- `serve.py` 가 진입점 (FastAPI 백엔드 + pywebview 윈도우). `app/main.py:app` 을 직접 import → frozen 에서 string lookup 회피.
- `data/` 폴더와 `.env` 는 .exe 옆에 외부로 (사용자가 caches 갱신 가능). bundle 안 들어감.
- `app/static/*` (HTML/CSS/JS) 는 --add-data 로 bundle (read-only).
- 첫 빌드 ~50초, 두 번째부터 캐시 (Analysis-00.toc) 로 ~20초.
- 빌드 실패해도 사용자에게 그대로 알리고, 마지막 정상 빌드 .exe 는 그대로 두기.
- 빌드 산출물: `dist/LogAnalyze/LogAnalyze.exe`. 사이즈 / 정상 기동 여부를 응답 끝에 한 줄로 보고.

**Permission Error 시:**
- `Get-Process LogAnalyze -ErrorAction SilentlyContinue | Stop-Process -Force` 후 재시도.
- [feedback_build_kill_exe](feedback_build_kill_exe.md) 참고.

**런타임 셋업 (사용자 PC 에서):**
- `dist/LogAnalyze/` 옆에 `data/` 폴더 + `.env` 필요.
- 처음 받을 때 mklink junction 으로 메인 프로젝트 `data/` 가리키게: `cmd /c mklink /J data ..\..\data` (dist/LogAnalyze 안에서)

**예외:**
- 사용자가 명시적으로 "이번 turn 은 빌드 스킵" 이라고 말하면 스킵
- 빌드가 5분 넘게 걸리는 비정상 상황은 한 번만 더 시도, 계속 실패하면 보고하고 다음 turn 으로 넘김
