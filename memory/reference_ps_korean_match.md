---
name: ps-korean-match-pitfall
description: PowerShell 5.1 Invoke-WebRequest는 한글 응답을 잘못 디코드 — frozen exe 검증 시 한글 -match가 가짜 음성
metadata:
  type: reference
---

frozen exe API 검증 때 PowerShell 5.1 `Invoke-WebRequest`의 `.Content`는 charset 미명시 응답을
ISO-8859-1로 디코드해서 **한글 `-match`가 항상 False**(가짜 음성)가 난다. 2026-06-11 "윈드러너
화살통" 매칭 실패로 확인 — 실제 데이터는 정상이었음.

**How to apply:** frozen exe 응답 검증은 ① ASCII 마커(`"2,010"` 같은 숫자)로 매칭하거나
② python `urllib...read().decode('utf-8')`로 확인. Invoke-RestMethod(JSON 파싱)는 괜찮음.
