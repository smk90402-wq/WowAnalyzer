---
name: 추측 fix 금지 — UI/CSS/DOM 버그는 실제 검사 후 수정
description: 사용자가 "여전히 안 됨" 하면 즉시 STOP. 가설 바꿔 또 코드 수정 금지. 실제 렌더링 inspect 필수.
type: feedback
---

**규칙**: UI / CSS / DOM / 시각적 버그 보고 받으면 **코드 추측 fix 시도 전 실제 렌더링 검사**가 필수.

**위반 패턴 (절대 하지 말 것):**
1. 사용자가 "X 가 안 보임" 보고
2. 코드 보고 가설 세움 (예: "데이터 누락일 듯") → 수정
3. 사용자가 "여전히 안 됨" 보고
4. 또 다른 가설 (예: "raw HTML 깨졌을 듯") → 수정
5. 사용자 "여전히 안 됨"
6. 또 다른 가설 → 수정
7. ... N 번 반복 후 사용자가 분노

**올바른 흐름:**
1. 사용자가 "X 가 안 보임" 보고
2. **즉시 inspect**:
   - 렌더링된 HTML 받아서 X 가 DOM 에 있는지 grep
   - 있으면 → CSS 문제 (display, overflow, z-index, opacity, position 등) 의심
     → 부모/자식 CSS 룰 grep + cross-reference (cast 는 보이는데 buff 만 안 보이면 둘의 CSS 차이 짚기)
   - 없으면 → 데이터/렌더링 로직 문제 → 코드 추적
3. 사용자가 한 번 더 "안 됨" 하면 **STOP. 새 가설로 또 코드 수정 금지.** 즉시 차원 바꿔서 inspect:
   - Chrome DevTools / 스크린샷 / JS 콘솔 probe / 직접 HTML 다운로드 후 브라우저 열기
4. 검사 데이터 확보 후에야 다음 fix.

**본 사례 (2026-05-26 — 5번의 헛수고):**
- 사용자: "버프 툴팁이 안 뜨네"
- 헛수고 1: description_ko fallback 추가 (데이터는 처음부터 있었음)
- 헛수고 2: spell_db enrich +252 entries (일부 누락이긴 했지만 본질 아님)
- 헛수고 3: raw HTML → plain text strip (nesting 멀쩡했음)
- 헛수고 4: clampTip JS 제거 (보조 가능성)
- 본질 (헛수고 5의 발견): `.buff { overflow: hidden }` 단 한 줄. `.tip` 이 buff 박스 밖 (bottom: 22px) 으로 확장돼서 잘렸음. `.cast` 에는 overflow:hidden 없어서 cast 만 보였음. **두 selector CSS 1줄 grep + 비교**로 바로 찾았어야 함.

**Why:** 사용자가 "이렇게 헤매지 말라고 룰 세팅 해놨다" 명시 (CLAUDE.md global 의 "Don't assume / Goal-Driven Execution" 룰). 추측 fix 가 누적되면 사용자 시간/내 빌드 시간/git history 다 낭비.

**How to apply:**
- 시각적 버그 → 첫 fix 시 가설 1개 + DOM inspect 결과 1개 명시
- 두 번째 "안 됨" 보고 → 가설 더 안 세움. inspect 만 함. inspect 결과 본 뒤에야 fix.
- 비슷한 element 가 동작하는 게 있으면 (예: cast 는 OK, buff 만 NG) → **두 element 의 CSS rule 1:1 diff** 가 첫 단계.
- CSS 키워드 grep 우선순위: `overflow`, `display`, `z-index`, `pointer-events`, `opacity`, `visibility`, `position`, `clip-path`, `transform`.
