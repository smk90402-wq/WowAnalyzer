---
name: 매 응답 끝 자동 커밋 + push
description: 작업 끝날 때마다 git add → commit → push (사용자가 다른 PC 에서 pull 받아 이어서 작업)
type: feedback
---

작업 마무리 시점에 git add + commit + push 까지 자동으로 한다.

**Why:** 사용자가 여러 PC 에서 작업을 이어감. PC 간 sync 방법은 git pull 이라
응답 단위로 커밋 안 하면 다른 PC 에서 진척사항 못 받음. (2026-05-18 명시)

**How to apply:**
- 매 응답에서 코드/메모리/스크립트 변경이 있으면 응답 끝에 자동 커밋 + push
- 빌드 산출물 (`dist/`, `build/`, `*.spec`), 대용량 캐시 (`data/v2_cache_*.json`,
  `data/cache.db`), 사용자 설정 (`data/user_settings.json`) 은 .gitignore 에서 제외
- commit 메시지: 한국어 OK, "이번 응답에서 한 일" 요약 (제목 1줄 + 본문 2-3줄)
- 메시지 끝에 항상 `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` 포함
- push 는 `git push` (현재 브랜치 origin 으로) — 실패 시 사용자에게 알리고 멈춤
- 메모리 파일 (`memory/`) 도 같이 커밋해야 다른 PC 의 Claude 도 같은 컨텍스트 갖춤
- 빌드 안 깨지는 정도의 변경만 커밋 — py_compile 실패하면 커밋 보류하고 사용자에게 알림
- 단순 조회/탐색만 한 응답 (코드 변경 없음) 은 커밋 안 함
