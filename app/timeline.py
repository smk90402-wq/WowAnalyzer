"""타임라인 HTML 렌더 — gui.py 의 RotationTimeline 에서 Qt 의존성 제거 후 추출.

gui.py 는 그대로 유지 (마이그레이션 중 병행 운영). 추후 cutover 시 gui.py 폐기.
"""
from __future__ import annotations

import re

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


def _resolve_name(spell_id: int, spell_db: dict) -> tuple[str, str]:
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
body.horizontal { overflow-x: auto; overflow-y: visible; padding-top: 0; --cast-offset: 0px; }
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
.buff { position: absolute; padding: 0; overflow: hidden;
    background: #3a322c; border: 1px solid #4a4039; color: #f5f0e8;
    border-radius: 3px; font-size: 11px; box-sizing: border-box; }
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
  const DEFAULT_PPS = 160;
  const MIN_PPS = 16;
  const MAX_PPS = 1200;
  let pps = DEFAULT_PPS;
  const body = document.body;
  const isV = body.classList.contains('vertical');
  const scrollKey = isV ? 'scrollY' : 'scrollX';

  function applyPps(newPps, anchor) {
    const oldPps = pps;
    pps = Math.max(MIN_PPS, Math.min(MAX_PPS, newPps));
    const cursorScreen = isV ? anchor.clientY : anchor.clientX;
    const worldTime = (window[scrollKey] + cursorScreen) / oldPps;
    body.style.setProperty('--pps', pps);
    const newScreen = worldTime * pps - cursorScreen;
    if (isV) window.scrollTo(window.scrollX, newScreen);
    else     window.scrollTo(newScreen, window.scrollY);
  }

  document.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.85 : 1.18;
    applyPps(pps * factor, e);
  }, { passive: false });

  document.addEventListener('dblclick', (e) => {
    if (e.target.closest('.cast') || e.target.closest('.buff')) return;
    applyPps(DEFAULT_PPS, e);
  });

  let dragging = false, dsx = 0, dsy = 0, dscX = 0, dscY = 0;
  let targetSx = 0, targetSy = 0, rafPending = false;
  body.style.cursor = 'grab';
  document.addEventListener('mousedown', (e) => {
    if (e.target.closest('.cast') || e.target.closest('.buff')) return;
    if (e.button !== 0) return;
    dragging = true;
    dsx = e.clientX; dsy = e.clientY;
    dscX = window.scrollX; dscY = window.scrollY;
    body.style.cursor = 'grabbing';
    e.preventDefault();
  });
  const DRAG_SPEED = 2.4;
  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    targetSx = dscX - (e.clientX - dsx) * DRAG_SPEED;
    targetSy = dscY - (e.clientY - dsy) * DRAG_SPEED;
    if (!rafPending) {
      rafPending = true;
      requestAnimationFrame(() => {
        window.scrollTo(targetSx, targetSy);
        rafPending = false;
      });
    }
  });
  const endDrag = () => { if (dragging) { dragging = false; body.style.cursor = 'grab'; } };
  ['mouseup', 'mouseleave'].forEach(ev => document.addEventListener(ev, endDrag));
})();
"""


def _cast_row_html(sid: int, lane_pos: int, t_rel: float, dur_s: float,
                   spell_db: dict, is_v: bool) -> str:
    meta = spell_db.get(str(sid), {})
    icon = meta.get("icon") or ""
    tip_body = (meta.get("description_ko") or meta.get("tooltip_ko")
                or meta.get("tooltip_en") or "")
    tip_body_plain = _strip_html(tip_body) if tip_body else ""
    icon_url = (f"https://wow.zamimg.com/images/wow/icons/medium/{icon}"
                if icon else "")
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
    return (
        f'<div class="cast pos-t" style="--t:{t_rel:.4f};{cross}">'
        f'{bar_html}'
        f'<img src="{icon_url}" alt="">'
        f'<div class="tip">'
        f'<div class="tname">{_html_escape(title)}</div>'
        f'{subtitle}'
        f'<div class="tbody">{_html_escape(tip_body_plain)}</div>'
        f'</div></div>'
    )


def _buff_html(sid: int, lane_pos: int, t_rel_start: float, dur_s: float,
               spell_db: dict, is_v: bool) -> str:
    meta = spell_db.get(str(sid), {})
    icon = meta.get("icon") or ""
    tip_body = meta.get("tooltip_ko") or meta.get("tooltip_en") or ""
    icon_url = (f"https://wow.zamimg.com/images/wow/icons/medium/{icon}"
                if icon else "")
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


def render_html(*, char: str, casts: list, buffs: list, fight_window: list,
                spell_db: dict, orientation: str = "h") -> str:
    """Full HTML document — 가로 (h) / 세로 (v) 타임라인."""
    if not fight_window or not casts:
        body = f"<div class='wrap'><div class='empty'>이 fight에 데이터 없음</div></div>"
        return _wrap_doc(body, "horizontal")

    is_v = (orientation == "v")
    start_ms = int(fight_window[0])
    end_ms = int(fight_window[1])
    duration_s = max((end_ms - start_ms) / 1000.0, 1.0)

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

    cast_sids_sorted = sorted(
        first_cast_ts.keys(),
        key=lambda s: (0 if _cast_has_name(s) else 1, first_cast_ts[s], s),
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
    cast_html_parts: list[str] = []
    for s_ts, e_ts, sid in cast_intervals:
        t_rel = max((s_ts - start_ms) / 1000.0, 0)
        dur_s = max((e_ts - s_ts) / 1000.0, 0)
        lane_pos = cast_lane.get(sid, 0) * CAST_ROW_H
        cast_html_parts.append(_cast_row_html(sid, lane_pos, t_rel, dur_s, spell_db, is_v))

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
                · 휠=줌 · 더블클릭=리셋</div>
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
                · 휠=줌 · 더블클릭=리셋</div>
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
