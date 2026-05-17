---
name: 매 답변마다 .exe 빌드
description: 모든 응답 끝에 PyInstaller로 LogAnalyze.exe 빌드 (확인 후 결정)
type: feedback
---

**규칙**: 매 답변(turn) 끝에 `pyinstaller --noconfirm --windowed --name LogAnalyze --collect-submodules PySide6 gui.py` 로 .exe 재빌드한다.

**Why:** 사용자가 명시적으로 선택. 1~2분 추가 비용을 알면서도 "매 답변 돌려" 라고 확정. 본인이 만든 .exe 를 매번 즉시 더블클릭해서 테스트하고 싶어함.

**How to apply:**
- gui.py 만 살짝 바뀐 경우도 빌드 — PyInstaller 가 분석 캐시(Analysis-00.toc) 써서 두 번째부터는 **약 7초**로 떨어짐 (첫 빌드는 ~70초)
- 단순 메모/문서/메모리만 갱신한 turn 이라도 빌드 (사용자가 일관성 원함)
- 빌드 실패해도 사용자에게 그대로 알리고, 마지막 정상 빌드 .exe 는 그대로 두기 (덮어쓰기 실패 = 이전 버전 유지)
- 빌드 명령은 [build.bat](../build.bat) 이 들고 있음 — Bash 도구로 `& build.bat` 또는 직접 pyinstaller 호출 가능
- 빌드 산출물: `dist/LogAnalyze/LogAnalyze.exe`. 사이즈 / 정상 기동 여부를 응답 끝에 한 줄로 보고
- 빌드 끝나면 `dist/LogAnalyze/LogAnalyze.exe` 가 OneDrive 동기화 대상이라 자주 변경 = 동기화 트래픽 부담. 알면서 진행.

**예외:**
- 사용자가 명시적으로 "이번 turn 은 빌드 스킵" 이라고 말하면 스킵
- 빌드가 5분 넘게 걸리는 비정상 상황은 한 번만 더 시도, 계속 실패하면 보고하고 다음 turn 으로 넘김
