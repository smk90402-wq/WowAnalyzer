"""타임라인 HTML 렌더 — gui.py 의 RotationTimeline 에서 Qt 의존성 제거 후 추출.

gui.py 는 그대로 유지 (마이그레이션 중 병행 운영). 추후 cutover 시 gui.py 폐기.
"""
from __future__ import annotations

import re
from collections import Counter

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_WHITESPACE_RE = re.compile(r"\s+")


def _html_escape(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _strip_html(s: str) -> str:
    if not s:
        return ""
    plain = _HTML_TAG_RE.sub(" ", s)
    return _HTML_WHITESPACE_RE.sub(" ", plain).strip()


# 증강 기원사 핵심기 — spell_db name_ko 가 mojibake 라 공식 한글명 override (Wowhead 검증)
EVOKER_KR = {
    395152: "칠흑의 힘", 409311: "예지", 410089: "예지",
    442204: "영겁의 숨결", 403631: "영겁의 숨결",
    357208: "불의 숨결", 382266: "불의 숨결",
    396286: "격변", 395160: "분출", 438588: "분출",
    361469: "살아있는 불꽃", 361509: "살아있는 불꽃",
    370553: "전세역전", 404977: "시간 도약", 362969: "하늘빛 일격",
    360827: "끓어오르는 비늘", 358267: "부양", 374227: "부양",
}


def _resolve_name(spell_id: int, spell_db: dict) -> tuple[str, str]:
    ov = EVOKER_KR.get(spell_id)
    if ov:
        return ov, ""
    meta = spell_db.get(str(spell_id), {})
    name_ko = (meta.get("name_ko") or "").strip()
    name_en = (meta.get("name_en") or "").strip()
    if name_ko and name_en:
        return name_ko, name_en
    if name_ko:
        return name_ko, ""
    if name_en:
        return name_en, ""
    return f"미상 #{spell_id}", ""


def _compute_buff_intervals(events: list) -> tuple[list, dict]:
    out: list = []
    open_buffs: dict[int, int] = {}
    for ev in events:
        if len(ev) < 3:
            continue
        ts = int(ev[0]); sid = int(ev[1]); kind = ev[2]
        if kind == "applybuff":
            open_buffs[sid] = ts
        elif kind == "removebuff":
            start = open_buffs.pop(sid, None)
            if start is not None:
                out.append((sid, start, ts))
    return out, open_buffs


TIMELINE_CSS = """
body {
    background: #1a1614; color: #f5f0e8;
    font-family: 'Pretendard Variable', 'Pretendard', 'Segoe UI', sans-serif;
    font-size: 11px; margin: 0; padding: 0;
    --pps: 160;
}
body.horizontal { overflow-x: auto; overflow-y: auto; padding-top: 0; --cast-offset: 0px; }
body.vertical   { overflow-x: visible; overflow-y: auto; padding-left: 0; --cast-offset: 0px; }
body.hide-buffs .buffs, body.hide-buffs .buff-label { display: none !important; }
body.horizontal .pos-t { left: calc(var(--cast-offset, 0px) + var(--t) * var(--pps) * 1px); }
body.vertical   .pos-t { top:  calc(var(--t) * var(--pps) * 1px); }
body.horizontal .size-w { width:  max(8px, calc(var(--w) * var(--pps) * 1px)); }
body.vertical   .size-w { height: max(8px, calc(var(--w) * var(--pps) * 1px)); }
body.horizontal .span-d { width:  calc(var(--cast-offset, 0px) + var(--d) * var(--pps) * 1px); }
body.vertical   .span-d { height: calc(var(--d) * var(--pps) * 1px); }
.wrap { padding: 4px 8px; }
.empty { color: #a39c8e; text-align: center; padding: 80px 16px;
    background: #221d1a; border: 1px dashed #3a322c; border-radius: 6px; }
.hdr { color: #d97757; font-size: 11px; font-weight: 600;
    margin-bottom: 2px; padding-bottom: 2px; border-bottom: 1px solid #3a322c; }
.timeline { position: relative; }
.lane-label { color: #a39c8e; font-size: 10px; padding: 1px 6px;
    background: #221d1a; border-radius: 3px; margin: 4px 0 2px 0; display: inline-block; }
.tick { position: absolute; color: transparent; }
.horizontal .axis  { position: relative; height: 20px; border-bottom: 1px solid #4a4039; margin-bottom: 2px; }
.horizontal .tick.label { color: #a39c8e; font-size: 10px; width: auto; background: none;
    padding-left: 4px; line-height: 20px; top: 0; height: 20px; }
.vertical .axis  { position: absolute; left: 0; top: 0; width: 32px; border-right: 1px solid #3a322c; }
.vertical .tick.label { left: 0; width: 22px; height: auto; background: none;
    color: #a39c8e; font-size: 10px; text-align: right; padding-right: 4px; }
.grid { position: absolute; top: 0; left: 0; right: 0; bottom: 0; pointer-events: none; z-index: 0; }
.horizontal .gline { position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(245, 240, 232, 0.15); }
.vertical .gline { position: absolute; left: 0; right: 0; height: 1px; background: rgba(245, 240, 232, 0.15); }
.casts, .buffs { position: relative; }
.horizontal .casts { height: 32px; margin-bottom: 4px; }
.horizontal .buffs { background: rgba(31, 26, 23, 0.45); border-radius: 4px; padding: 4px 0; }
.vertical .lanes { position: absolute; left: 36px; top: 0; right: 0; }
.vertical .lanes-buffs { left: auto; right: 0; }
.cast { position: absolute; width: 28px; height: 28px; z-index: 2; }
.cast img { width: 28px; height: 28px; display: block;
    border: 1px solid #4a4039; border-radius: 4px; box-sizing: border-box;
    position: relative; z-index: 2; }
.cast:hover img { border-color: #d97757; }
.cast:hover { z-index: 10; }
.horizontal .cast-bar { position: absolute; top: 4px; left: 14px; height: 20px;
    width: calc(var(--d) * var(--pps) * 1px);
    background: linear-gradient(to right, rgba(217,119,87,0.55) 0%, rgba(217,119,87,0.25) 60%, rgba(217,119,87,0.10) 100%);
    border-radius: 0 3px 3px 0; z-index: 1; pointer-events: none; }
.buff { position: absolute; padding: 0;
    background: #3a322c; border: 1px solid #4a4039; color: #f5f0e8;
    border-radius: 3px; font-size: 11px; box-sizing: border-box; }
/* overflow: hidden 제거 — .tip 이 .buff 박스 밖 (bottom: 22px) 으로 확장되는데
   클리핑되어 안 보였음. label .blbl 은 자체 ellipsis 가지므로 .buff 의
   overflow:hidden 없어도 OK. */
.buff:hover { border-color: #d97757; z-index: 5; }
.horizontal .buff { height: 24px; line-height: 24px; }
.vertical .buff { width: 28px; }
.buff img.bicon { width: 20px; height: 20px; vertical-align: middle; border-radius: 3px; }
.horizontal .buff img.bicon { float: left; margin: 1px 5px 0 1px; }
.vertical .buff img.bicon { display: block; margin: 1px auto; }
.buff .blbl { display: inline-block; vertical-align: middle;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.horizontal .buff .blbl { max-width: calc(100% - 30px); }
.vertical .buff .blbl { display: none; }
.tip { display: none; position: absolute; background: #15110f; color: #f5f0e8;
    border: 1px solid #4a4039; border-radius: 6px; padding: 10px 12px;
    min-width: 280px; max-width: 460px; box-shadow: 0 8px 24px rgba(0,0,0,0.6);
    z-index: 99999; pointer-events: none; font-size: 11px;
    max-height: 60vh; overflow-y: auto; }
.cast:hover .tip, .buff:hover .tip { display: block; }
.horizontal .cast .tip { bottom: 34px; left: -8px; }
.horizontal .buff .tip { bottom: 22px; left: 0; }
.vertical .cast .tip { left: 34px; top: -8px; }
.vertical .buff .tip { left: 28px; top: 0; }
.tip .tname { color: #d97757; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.tip .ten { color: #a39c8e; font-style: italic; font-size: 10px; margin-bottom: 6px; }
.tip .tbody table { font-size: 11px; }
html { overflow: visible; }
.wrap, .timeline, .casts, .buffs, .lanes { overflow: visible; }
"""


ZOOM_JS = """
(function() {
  // Drag perf 핵심: window.scrollTo (layout reflow) 가 아니라
  // .timeline 에 transform: translate3d 적용 (GPU compositor 만).
  // body 는 overflow:hidden — 스크롤바 대신 드래그로 panning.
  const DEFAULT_PPS = 160;
  const MIN_PPS = 16;
  const MAX_PPS = 1200;
  let pps = DEFAULT_PPS;
  let panX = 0, panY = 0;
  const body = document.body;
  const isV = body.classList.contains('vertical');
  const tl = document.querySelector('.timeline');
  if (!tl) return;

  body.style.overflowX = 'hidden';  // 세로는 native 스크롤 허용 (버프 잘림 방지)
  tl.style.transformOrigin = '0 0';
  tl.style.willChange = 'transform';

  // 비교 탭 같이 2개 timeline 이 parent 에 있으면 부모가 가운데에서 sync.
  // applying = true 일 때는 broadcast skip → loop 방지.
  let applying = false;
  function broadcast() {
    if (applying) return;
    try { parent.postMessage({type: 'tlsync', pps, panX, panY}, '*'); }
    catch (_) { /* no parent or cross-origin */ }
  }

  function applyTransform() {
    tl.style.transform = 'translate3d(' + (-panX) + 'px,' + (-panY) + 'px,0)';
  }
  applyTransform();

  function applyPps(newPps, anchor) {
    const oldPps = pps;
    pps = Math.max(MIN_PPS, Math.min(MAX_PPS, newPps));
    // 앵커 (커서) 의 화면 위치 고정 → 줌인/줌아웃 시 그 시점이 그대로 머무름
    const cursorScreen = isV ? anchor.clientY : anchor.clientX;
    const curPan = isV ? panY : panX;
    const worldTime = (curPan + cursorScreen) / oldPps;
    body.style.setProperty('--pps', pps);
    const newScreen = worldTime * pps - cursorScreen;
    if (isV) panY = Math.max(0, newScreen);
    else     panX = Math.max(0, newScreen);
    applyTransform();
    broadcast();
  }

  // 부모로부터 sync 메시지 받음 → 로컬 적용 (broadcast 안 함)
  window.addEventListener('message', (e) => {
    const d = e.data;
    if (!d || d.type !== 'tlapply') return;
    applying = true;
    if (typeof d.pps === 'number') {
      pps = Math.max(MIN_PPS, Math.min(MAX_PPS, d.pps));
      body.style.setProperty('--pps', pps);
    }
    if (typeof d.panX === 'number') panX = Math.max(0, d.panX);
    if (typeof d.panY === 'number') panY = Math.max(0, d.panY);
    applyTransform();
    applying = false;
  });

  document.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.85 : 1.18;
    applyPps(pps * factor, e);
  }, { passive: false });

  document.addEventListener('dblclick', (e) => {
    if (e.target.closest('.cast') || e.target.closest('.buff')) return;
    applyPps(DEFAULT_PPS, e);
  });

  let dragging = false, dsx = 0, dsy = 0, dpanX = 0, dpanY = 0;
  let targetX = 0, targetY = 0, rafPending = false;
  body.style.cursor = 'grab';
  document.addEventListener('mousedown', (e) => {
    if (e.target.closest('.cast') || e.target.closest('.buff')) return;
    if (e.button !== 0) return;
    dragging = true;
    dsx = e.clientX; dsy = e.clientY;
    dpanX = panX; dpanY = panY;
    targetX = panX; targetY = panY;
    body.style.cursor = 'grabbing';
    e.preventDefault();
  });
  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    // 마우스 이동 방향 반대로 pan. 1:1 매핑 — translate3d 라서 충분히 빠름.
    targetX = Math.max(0, dpanX - (e.clientX - dsx));
    targetY = Math.max(0, dpanY - (e.clientY - dsy));
    if (!rafPending) {
      rafPending = true;
      requestAnimationFrame(() => {
        panX = targetX; panY = targetY;
        applyTransform();
        broadcast();
        rafPending = false;
      });
    }
  });
  const endDrag = () => { if (dragging) { dragging = false; body.style.cursor = 'grab'; } };
  ['mouseup', 'mouseleave'].forEach(ev => document.addEventListener(ev, endDrag));

  // ── 툴팁 Y 클램핑 — tip 이 iframe top 위로 잘리면 호스트 아래로 flip ──────
  // 첫/두번째 row 의 cast/buff 호버 시 tip 의 헤더(이름)가 보이지 않는 문제.
  // X 방향은 건드리지 않음 (이전 음수-left 계산 버그 회피).
  function flipTipIfClippedTop(e) {
    const host = e.target.closest('.cast, .buff');
    if (!host) return;
    const tip = host.querySelector(':scope > .tip');
    if (!tip) return;
    // 이전 상태 reset → CSS default 위치 (bottom: 22/34px) 로 layout
    tip.style.top = '';
    tip.style.bottom = '';
    const tipRect = tip.getBoundingClientRect();
    if (tipRect.height === 0) return;  // 아직 display:block 안 됨
    if (tipRect.top < 4) {
      // 위로 잘림 → 호스트 아래로 flip
      const hostRect = host.getBoundingClientRect();
      tip.style.bottom = 'auto';
      tip.style.top = (hostRect.height + 4) + 'px';
    }
  }
  document.addEventListener('mouseover', flipTipIfClippedTop, true);
})();
"""


def _cast_row_html(sid: int, lane_pos: int, t_rel: float, dur_s: float,
                   spell_db: dict, is_v: bool, flag_why: str = "") -> str:
    meta = spell_db.get(str(sid), {})
    icon = meta.get("icon") or ""
    # buff_html 과 동일 — wowhead raw HTML 의 nested <div> 가 outer 닫는
    # 버그 회피용으로 plain text 평문화 + escape.
    tip_body_raw = (meta.get("description_ko") or meta.get("tooltip_ko")
                    or meta.get("tooltip_en") or "")
    tip_body = _html_escape(_strip_html(tip_body_raw)) if tip_body_raw else ""
    # spell_db 에 미등록인 ID 는 placeholder ? 아이콘 — 빈 회색 박스 회피
    icon_url = (f"https://wow.zamimg.com/images/wow/icons/medium/{icon}"
                if icon
                else "https://wow.zamimg.com/images/wow/icons/medium/inv_misc_questionmark.jpg")
    title, sub = _resolve_name(sid, spell_db)
    time_str = f"t={t_rel:.3f}s"
    if dur_s > 0.05:
        time_str += f" · 시전 {dur_s*1000:.0f}ms"
    subtitle = (f'<div class="ten">{_html_escape(sub)} · {time_str}</div>'
                if sub else f'<div class="ten">{time_str}</div>')
    cross = f"left:{lane_pos}px" if is_v else f"top:{lane_pos}px"
    bar_html = ""
    if dur_s > 0.05:
        bar_html = f'<div class="cast-bar" style="--d:{dur_s:.4f}"></div>'
    flag_cls = " flagged" if flag_why else ""
    flag_style = (";outline:2px solid #ff5a5a;outline-offset:1px;border-radius:4px"
                  if flag_why else "")
    flag_tip = (f'<div class="tflag" style="color:#ff7a7a;font-weight:600;margin:2px 0">'
                f'⚠ {_html_escape(flag_why)}</div>' if flag_why else "")
    return (
        f'<div class="cast pos-t{flag_cls}" style="--t:{t_rel:.4f};{cross}{flag_style}">'
        f'{bar_html}'
        f'<img src="{icon_url}" alt="">'
        f'<div class="tip">'
        f'<div class="tname">{_html_escape(title)}</div>'
        f'{subtitle}'
        f'{flag_tip}'
        f'<div class="tbody">{tip_body}</div>'
        f'</div></div>'
    )


def _buff_html(sid: int, lane_pos: int, t_rel_start: float, dur_s: float,
               spell_db: dict, is_v: bool) -> str:
    meta = spell_db.get(str(sid), {})
    icon = meta.get("icon") or ""
    # spell_db 키 우선순위: description_ko (Blizzard/Wowhead enrich 본문) →
    # 호환용 tooltip_ko/en. cast 와 동일하게 HTML 평문화 — wowhead raw 의
    # 잘못된 nesting (<div class="q"></div>) 이 outer .tip 닫는 버그 회피.
    tip_body_raw = (meta.get("description_ko") or meta.get("tooltip_ko")
                    or meta.get("tooltip_en") or "")
    tip_body = _html_escape(_strip_html(tip_body_raw)) if tip_body_raw else ""
    icon_url = (f"https://wow.zamimg.com/images/wow/icons/medium/{icon}"
                if icon
                else "https://wow.zamimg.com/images/wow/icons/medium/inv_misc_questionmark.jpg")
    title, sub = _resolve_name(sid, spell_db)
    subtitle = (f'<div class="ten">{_html_escape(sub)} · 지속 {dur_s:.1f}s</div>'
                if sub else f'<div class="ten">지속 {dur_s:.1f}s</div>')
    cross = f"left:{lane_pos}px" if is_v else f"top:{lane_pos}px"
    return (
        f'<div class="buff pos-t size-w" '
        f'style="--t:{t_rel_start:.4f};--w:{dur_s:.4f};{cross}">'
        f'<img class="bicon" src="{icon_url}" alt="">'
        f'<span class="blbl">{_html_escape(title)}</span>'
        f'<div class="tip">'
        f'<div class="tname">{_html_escape(title)}</div>'
        f'{subtitle}'
        f'<div class="tbody">{tip_body}</div>'
        f'</div></div>'
    )


# 외부 캐스터 버프 중에서도 항상 표시할 spell ID (BL/Hero/TW + PI + 펫 BL + 드럼).
# self src 가 아닌 외부 버프는 기본 숨김, 이 목록에 있는 것만 통과.
SHOW_EXTERNAL_BUFFS = {
    10060,   # Power Infusion (사제 마력주입)
    2825,    # Bloodlust (호드 주술사 피의 욕망)
    32182,   # Heroism (얼라 주술사 영웅심)
    80353,   # Time Warp (마법사 시간 왜곡)
    264667,  # Primal Rage (사냥꾼 펫 원시의 분노)
    390386,  # Fury of the Aspects (기원사 측면의 격노)
    230935,  # Drums of Fury — 격노의 북
    178207,  # Drums of the Mountain — 산의 북
    256740,  # Drums of the Maelstrom — 폭풍 북
    309658,  # Drums of Deathly Ferocity — 죽음의 흉포한 북
    466904,  # Drums (Midnight 11.x 신규)
    80354,   # Temporal Displacement (TW 후 디버프)
    57723,   # Exhaustion (BL 후 디버프)
    57724,   # Sated (BL 후 디버프)
    264689,  # Fatigued (Primal Rage 후 디버프)
}


def render_html(*, char: str, casts: list, buffs: list, fight_window: list,
                spell_db: dict, char_source_id: int | None = None,
                orientation: str = "h", flag_casts: dict | None = None) -> str:
    """Full HTML document — 가로 (h) / 세로 (v) 타임라인.

    char_source_id 가 주어지면 외부 버프 필터링:
      - src == char_source_id (자기 자신이 시전한 버프) → 표시
      - src != char_source_id 이지만 SHOW_EXTERNAL_BUFFS 에 있는 spell → 표시
      - 그 외 (다른 클래스의 도트힐 등) → 숨김
    None 이면 필터링 안 함 (backward compat).
    또한 버프 record 가 옛 schema (length 3, src 없음) 면 필터링 skip.
    """
    if not fight_window or not casts:
        body = f"<div class='wrap'><div class='empty'>이 fight에 데이터 없음</div></div>"
        return _wrap_doc(body, "horizontal")

    is_v = (orientation == "v")
    start_ms = int(fight_window[0])
    end_ms = int(fight_window[1])
    duration_s = max((end_ms - start_ms) / 1000.0, 1.0)

    # 외부 버프 필터링 (char_source_id 와 buff record length 4 둘 다 있을 때만)
    if char_source_id is not None and buffs:
        sample = buffs[0]
        if isinstance(sample, list) and len(sample) >= 4:
            def _allow(ev):
                src = ev[3] if len(ev) > 3 else 0
                gid = ev[1]
                if src == char_source_id:
                    return True
                if gid in SHOW_EXTERNAL_BUFFS:
                    return True
                return False
            buffs = [e for e in buffs if _allow(e)]

    CAST_ROW_H = 32
    BUFF_LANE_PX = 26

    # ── 시전: begincast → cast 페어로 duration 인터벌 ─────────────────
    cast_intervals: list[tuple[int, int, int]] = []
    open_casts: dict[int, int] = {}
    for ev in casts:
        if len(ev) < 3:
            continue
        ts = int(ev[0]); sid = int(ev[1]); kind = ev[2]
        if kind == "begincast":
            open_casts[sid] = ts
        elif kind == "cast":
            begin_ts = open_casts.pop(sid, ts)
            if begin_ts > ts:
                begin_ts = ts
            cast_intervals.append((begin_ts, ts, sid))
    cast_intervals.sort()
    for sid, ts in open_casts.items():
        cast_intervals.append((ts, ts, sid))
    cast_intervals.sort()
    cast_intervals = [iv for iv in cast_intervals if iv[1] >= start_ms]

    # 스펠별 첫 시전 시각 — 시간순 lane 배정
    first_cast_ts: dict[int, int] = {}
    for s_ts, _e_ts, sid in cast_intervals:
        if sid not in first_cast_ts:
            first_cast_ts[sid] = s_ts

    def _cast_has_name(sid: int) -> bool:
        m = spell_db.get(str(sid), {})
        return bool(m.get("name_ko") or m.get("name_en"))

    cast_count = Counter(sid for _s, _e, sid in cast_intervals)
    cast_sids_sorted = sorted(
        first_cast_ts.keys(),
        key=lambda s: (0 if _cast_has_name(s) else 1, -cast_count[s], first_cast_ts[s]),
    )
    cast_lane: dict[int, int] = {sid: i for i, sid in enumerate(cast_sids_sorted)}
    casts_lane_span = max(len(cast_lane), 1) * CAST_ROW_H

    # ── 버프 lane 배정 (이름 있는 것만) ──────────────────────────────
    all_intervals, still_open = _compute_buff_intervals(buffs or [])
    for sid, t_start in still_open.items():
        all_intervals.append((sid, t_start, end_ms))

    def _has_name(sid: int) -> bool:
        m = spell_db.get(str(sid), {})
        return bool(m.get("name_ko") or m.get("name_en"))

    intervals = [iv for iv in all_intervals if _has_name(iv[0])]
    hidden_unknown_buffs = len(all_intervals) - len(intervals)

    buff_lane: dict[int, int] = {}
    sids_sorted = sorted(
        {sid for sid, _, _ in intervals},
        key=lambda s: -sum(e - st for ss, st, e in intervals if ss == s),
    )
    for s in sids_sorted:
        buff_lane[s] = len(buff_lane)
    buffs_lane_span = max(len(buff_lane), 1) * BUFF_LANE_PX + 8

    # ── HTML 빌드 ─────────────────────────────────────────────────────
    flag_casts = flag_casts or {}
    cast_html_parts: list[str] = []
    for s_ts, e_ts, sid in cast_intervals:
        t_rel = max((s_ts - start_ms) / 1000.0, 0)
        dur_s = max((e_ts - s_ts) / 1000.0, 0)
        lane_pos = cast_lane.get(sid, 0) * CAST_ROW_H
        why = flag_casts.get((sid, e_ts), "")
        cast_html_parts.append(_cast_row_html(sid, lane_pos, t_rel, dur_s, spell_db, is_v, why))

    buff_html_parts: list[str] = []
    for sid, t_start, t_end in intervals:
        t_rel_start = max((t_start - start_ms) / 1000.0, 0)
        dur_s = (t_end - t_start) / 1000.0
        lane_pos = buff_lane.get(sid, 0) * BUFF_LANE_PX
        buff_html_parts.append(_buff_html(sid, lane_pos, t_rel_start, dur_s, spell_db, is_v))

    grid_html: list[str] = []
    label_html: list[str] = []
    for s in range(0, int(duration_s) + 1):
        grid_html.append(f'<div class="gline pos-t" style="--t:{s}"></div>')
        label_html.append(f'<div class="tick label pos-t" style="--t:{s}">{s}s</div>')

    d_attr = f"--d:{duration_s:.3f}"
    if is_v:
        casts_style = f"width:{casts_lane_span}px"
        buffs_style = f"width:{buffs_lane_span}px"
        casts_left = 36
        buffs_left = 36 + casts_lane_span + 12
        body = f'''
        <div class="wrap">
            <div class="hdr">{_html_escape(char)} · fight {duration_s:.1f}s
                · 시전 {len(cast_intervals)}회 ({len(cast_lane)}개 스펠)
                · 버프 인터벌 {len(intervals)}개
                {f' (미상 {hidden_unknown_buffs}개 숨김)' if hidden_unknown_buffs else ''}
                · 휠=줌 · 드래그=이동 · 더블클릭=리셋</div>
            <div class="timeline span-d" style="{d_attr}">
                <div class="grid span-d">{"".join(grid_html)}</div>
                <div class="axis span-d">{"".join(label_html)}</div>
                <div class="casts lanes span-d" style="{casts_style};left:{casts_left}px">
                    {"".join(cast_html_parts)}
                </div>
                <div class="buffs lanes lanes-buffs span-d" style="{buffs_style};left:{buffs_left}px">
                    {"".join(buff_html_parts)}
                </div>
            </div>
        </div>'''
        return _wrap_doc(body, "vertical")
    else:
        casts_style = f"height:{casts_lane_span}px"
        buffs_style = f"height:{buffs_lane_span}px"
        body = f'''
        <div class="wrap">
            <div class="hdr">{_html_escape(char)} · fight {duration_s:.1f}s
                · 시전 {len(cast_intervals)}회 ({len(cast_lane)}개 스펠)
                · 버프 인터벌 {len(intervals)}개
                {f' (미상 {hidden_unknown_buffs}개 숨김)' if hidden_unknown_buffs else ''}
                · 휠=줌 · 드래그=이동 · 더블클릭=리셋</div>
            <div class="timeline span-d" style="{d_attr}">
                <div class="grid span-d">{"".join(grid_html)}</div>
                <div class="axis span-d">{"".join(label_html)}</div>
                <div class="casts span-d" style="{casts_style}">
                    {"".join(cast_html_parts)}
                </div>
                <span class="lane-label buff-label">버프</span>
                <div class="buffs span-d" style="{buffs_style}">
                    {"".join(buff_html_parts)}
                </div>
            </div>
        </div>'''
        return _wrap_doc(body, "horizontal")


def _wrap_doc(body: str, body_class: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{TIMELINE_CSS}</style></head>"
        f"<body class='{body_class}'>{body}"
        f"<script>{ZOOM_JS}</script>"
        "</body></html>"
    )
