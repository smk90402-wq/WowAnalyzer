---
name: 특성 패널 — WCL 최상위 100 분리 비주얼 트리
description: 표 형식 talent 패널을 WCL 스타일 비주얼 트리로 교체 (직업/전문화/영웅 + 장신구/장식)
type: project
---

**Current**: 특성 분포 패널이 표 (talent_table) — 사용자가 원한 게 아님.

**Target**: WCL "최상위 100 분리" 페이지 그대로 재현.
- **클래스 특성** 트리 (좌측)
- **전문화 특성** 트리 (우측)
- **영웅 특성** 트리 (가운데, 선택된 하나만)
- **장신구** 행 (하단, 슬롯 12-13 인기도)
- **장식됨** (장식)** 행 (하단, embellishment 인기도)

각 노드: 아이콘 + 픽률 % 오버레이, 핵심 (95%+) 핑크/주황, 분기 (40-70%) 컬러풀, 안 찍힘 (<5%) 회색.

**가용 데이터:**
- Blizzard `/data/wow/talent-tree/{class_tree_id}/playable-specialization/{spec_id}` → 풀 트리 구조:
  - class_talent_nodes (45) / spec_talent_nodes (69) / hero_talent_trees (3 영웅)
  - 각 노드: id, display_row, display_col, raw_position_x/y, ranks[].tooltip.spell.{id, name, description, cast_time, ...}, unlocks (연결선)
- 우리 cache_talents.json → 픽률 (이미 (rid:fid, char): [talent_ids] 형태)
- 우리 cache_gear.json → 장신구/장식 (slot 12-13 = trinkets, bonusIDs = embellishments)

**구현 단계:**
1. `fetch_talent_trees.py` — 5 target spec 의 트리 구조 한 번씩 fetch, 캐시 (`data/talent_trees.json`)
2. GUI 의 talent_table → QWebEngineView 로 교체 (HTML/SVG 렌더)
   - `position: absolute` + display_row/col → grid 셀
   - SVG 라인으로 unlocks 연결
   - 호버 시 한글 설명
3. 하단에 장신구 / 장식 행 (가장 빈도 높은 7~10개씩 아이콘 + %)
4. Hero talent 트리는 사용자가 본 spec 의 트리 한 번에 하나만 (Pack Leader / Sentinel 등 선택 가능?)

**왜 다음 turn**: 이번 turn 은 타임라인 개선 + 메모리만. 트리 비주얼은 ~몇백줄 HTML/CSS 코딩 필요.
