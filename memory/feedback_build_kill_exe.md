---
name: 빌드 실패 시 LogAnalyze.exe 강제 종료
description: PyInstaller 빌드가 PermissionError 로 실패하면 sleep/재시도 금지. 즉시 LogAnalyze.exe 강제 종료 후 재빌드.
type: feedback
---

PyInstaller 가 `dist/LogAnalyze/` 안에 파일 쓰는데 LogAnalyze.exe (또는 _internal/*.pyd) 가
실행 중이면 `PermissionError: [WinError 5] 액세스가 거부되었습니다` 발생.

**행동 (2026-05-21 명시):**

1. 빌드 출력에 `PermissionError` + `LogAnalyze` 또는 `_internal` 패턴 보이면 즉시:
   ```
   taskkill /F /IM LogAnalyze.exe
   ```
   PowerShell 환경에서:
   ```
   Get-Process LogAnalyze -ErrorAction SilentlyContinue | Stop-Process -Force
   ```
2. 그 다음 PyInstaller 명령 그대로 재시도.

**금지:**
- `Start-Sleep` 후 재시도 (시간 낭비)
- 사용자에게 "닫아주세요" 부탁
- 빌드 포기하고 다음 응답에서 하자고 미루기

**Why:** 사용자가 분석기 실행 중 상태에서 추가 작업 요청하는 게 일반적 패턴.
재시도 대기는 무의미하고, 어차피 빌드된 새 .exe 가 필요함. 강제 종료 후 재빌드가
가장 빠르고 사용자 워크플로우와도 맞음.
