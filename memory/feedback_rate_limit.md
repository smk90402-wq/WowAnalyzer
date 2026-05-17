---
name: API rate limit — wait, don't throttle
description: WCL 429 맞으면 그대로 기다려야 함. 처리량을 일부러 낮추지 말 것.
type: feedback
---

WCL API 의 429 (rate limit) 가 떴을 때 — 심지어 Retry-After 가 1시간이라도 — 그냥 기다린다. 다음 중 어떤 것도 하지 말 것:

- SLEEP 상수를 더 늘려서 429를 피하려고 시도 (= 평소 처리량 떨어짐)
- 백그라운드 job 을 죽이고 다른 작업으로 갈아끼우려고 시도
- 키를 회전시키자고 제안 (앞서 user 가 명시적으로 회수 안 한다고 했음 — [user_profile.md](user_profile.md))
- 페치를 분할/직렬화해서 "안전하게" 하자고 제안

**Why:** 사용자가 명시적으로 "그 속도 느려지지않게해, 리미트 걸릴거같으면 그냥 기다려" 라고 지시. 처리량 우선, 리밋은 그냥 견딘다.

**How to apply:**
- 새 fetch 스크립트 작성 시 SLEEP 은 기존 0.35s 그대로 (enrich_pi/enrich_talents/fetch_casts 와 일치)
- 429 슬립이 얼마든 그대로 두고 진행률만 사용자에게 보고
- 같은 키를 쓰는 다른 fetch 가 진행 중이면 새 fetch 는 코드만 짜놓고 실행은 보류 — 동시 실행해서 양쪽 다 느려지게 하면 안 됨
- WCL 과 다른 호스트(WoWhead 등) 작업은 자유롭게 병렬 OK
