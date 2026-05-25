"""특성 트리 HTML 렌더 — gui.py 의 _build_tree_html 에서 Qt 의존성 제거.

Top100 aggregate 와 single-char "본인 픽" 모드 둘 다 지원.
"""
from __future__ import annotations

from app.timeline import _html_escape


TREE_CSS = """
body {
    background: #1a1614; color: #f5f0e8;
    font-family: 'Pretendard Variable', 'Pretendard', 'Segoe UI', sans-serif;
    font-size: 11px; margin: 0; padding: 0;
}
.tree-wrap { padding: 16px; }
.tree-row { display: flex; gap: 24px; align-items: flex-start; }
.tree-col { position: relative; flex: 0 0 auto; }
.tree-col h3 {
    margin: 0 0 12px 0;
    color: #a39c8e; font-size: 10px; font-weight: 500;
    letter-spacing: 0.08em; text-transform: uppercase;
    border-bottom: 1px solid #2c2521; padding-bottom: 8px;
}
.tree-canvas { position: relative; background: transparent; padding: 8px; }

.tnode {
    position: absolute; width: 36px; height: 36px;
    border: 2px solid transparent; border-radius: 6px; box-sizing: border-box;
    background: #15110f; transition: transform 100ms ease-out;
}
.tnode:hover { transform: scale(1.12); z-index: 9999; }
.tnode img { width: 100%; height: 100%; border-radius: 4px; display: block; }
.tnode.choice { border-radius: 50%; }
.tnode.choice img { border-radius: 50%; }
.tnode.t-essential { border-color: #d97757; box-shadow: 0 0 10px rgba(217, 119, 87, 0.45); }
.tnode.t-common { border-color: #d97757; }
.tnode.t-split { border-color: #6b6359; }
.tnode.t-niche { opacity: 0.78; }
.tnode.t-zero { opacity: 0.45; }

.tnode .pct {
    position: absolute; bottom: -4px; right: -4px;
    background: rgba(10, 8, 6, 0.9); color: #f5f0e8;
    font-size: 9px; font-weight: 600;
    padding: 1px 4px; border-radius: 8px; min-width: 14px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.5);
}
.tnode.t-essential .pct { background: rgba(217, 119, 87, 0.9); }
.tnode .ptsbadge {
    position: absolute; top: -5px; left: -5px;
    background: rgba(64, 36, 28, 0.95); color: #f5f0e8;
    font-size: 9px; font-weight: 600;
    padding: 1px 4px; border-radius: 7px; min-width: 14px; text-align: center;
    border: 1px solid rgba(217, 119, 87, 0.4);
}

.tnode .tip {
    display: none; position: absolute; bottom: 48px; left: -8px;
    background: #15110f; border: 1px solid #3a322c; border-radius: 8px;
    padding: 10px 12px; min-width: 280px; max-width: 400px;
    z-index: 99999; box-shadow: 0 8px 24px rgba(0,0,0,0.7);
    color: #f5f0e8; font-size: 11px; pointer-events: none;
    max-height: 70vh; overflow-y: auto;
}
.tnode:hover .tip { display: block; }
.tip .tname { color: #d97757; font-weight: 600; font-size: 12px; margin-bottom: 4px; }
.tip .tmeta { color: #c8a560; font-size: 10px; margin-bottom: 4px; }
.tip .tdist { font-size: 10px; margin-bottom: 6px; line-height: 1.4; padding-left: 6px; border-left: 2px solid #3a322c; }
.tip .tdesc { color: #c4bdaf; line-height: 1.5; }

body { overflow: visible !important; }
.tree-wrap { overflow: visible; padding-top: 24px; }
.tree-canvas, .tree-col, .tree-row { overflow: visible; }

.empty {
    color: #a39c8e; text-align: center; padding: 64px 24px;
    background: #221d1a; border: 1px dashed #3a322c; border-radius: 12px; margin: 16px;
}
"""


def _empty(msg: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{TREE_CSS}</style></head>"
            f"<body><div class='empty'>{_html_escape(msg)}</div></body></html>")


def _node_html(node: dict, pick_pct: float, pt_breakdown: dict[int, float],
               denom: int, spell_db: dict,
               scale: float = 0.075, ox: float = 0, oy: float = 0) -> str:
    if not node.get("options"):
        return ""
    opt = node["options"][0]
    spell_id = opt.get("spell_id")
    name = opt.get("name") or f"#{node.get('id')}"
    if spell_id:
        meta = spell_db.get(str(spell_id), {})
        nm_ko = (meta.get("name_ko") or "").strip()
        if nm_ko:
            name = nm_ko
        desc_db = (meta.get("description_ko") or meta.get("tooltip_ko") or "").strip()
        desc = desc_db or (opt.get("desc") or "")
    else:
        desc = opt.get("desc") or ""
    max_rank = node.get("max_rank") or 1
    pick_pts = [k for k in pt_breakdown if k >= 1]
    if pick_pts:
        picked_sum = sum(k * pt_breakdown.get(k, 0) * denom / 100 for k in pick_pts)
        picked_n = sum(pt_breakdown.get(k, 0) * denom / 100 for k in pick_pts)
        avg_pts = picked_sum / picked_n if picked_n > 0 else 1.0
    else:
        avg_pts = 1.0

    icon_file = ""
    if spell_id:
        meta = spell_db.get(str(spell_id), {})
        icon_file = meta.get("icon") or ""
    icon_url = (f"https://wow.zamimg.com/images/wow/icons/medium/{icon_file}"
                if icon_file else "")

    rx = node.get("x") or 0
    ry = node.get("y") or 0
    left = int((rx - ox) * scale) + 24
    top = int((ry - oy) * scale) + 24

    if pick_pct >= 85:
        cls = "t-essential"
    elif pick_pct >= 50:
        cls = "t-common"
    elif pick_pct >= 25:
        cls = "t-split"
    elif pick_pct >= 5:
        cls = "t-niche"
    else:
        cls = "t-zero"
    if node.get("type") == "CHOICE":
        cls += " choice"

    pct_html = ""
    if pick_pct >= 5:
        pct_html = f'<div class="pct">{int(round(pick_pct))}</div>'
    pts_html = ""
    if max_rank > 1 and pick_pct >= 5:
        pts_html = f'<div class="ptsbadge">{avg_pts:.1f}</div>'

    tip_meta_lines = []
    if max_rank > 1:
        tip_meta_lines.append(
            f"<div class='tmeta'>전체 픽률 {int(round(pick_pct))}% · 평균 {avg_pts:.2f}/{max_rank} pts</div>"
        )
        dist_lines = []
        for k in sorted(pt_breakdown.keys()):
            pct_k = pt_breakdown.get(k, 0.0)
            if pct_k < 0.5:
                continue
            label = "0pt (안 찍음)" if k == 0 else f"{k}pt"
            color = "#6b6359" if k == 0 else ("#d97757" if k == max_rank else "#a39c8e")
            dist_lines.append(f"<div style='color:{color}'>{label}: {pct_k:.1f}%</div>")
        tip_meta_lines.append("<div class='tdist'>" + "".join(dist_lines) + "</div>")
    else:
        tip_meta_lines.append(
            f"<div class='tmeta'>픽률 {int(round(pick_pct))}% · 1포인트 노드</div>"
        )

    return (
        f'<div class="tnode {cls}" style="left:{left}px;top:{top}px">'
        f'<img src="{icon_url}" alt="">'
        f'{pct_html}{pts_html}'
        f'<div class="tip">'
        f'<div class="tname">{_html_escape(name)}</div>'
        f'{"".join(tip_meta_lines)}'
        f'<div class="tdesc">{desc[:1200]}</div>'
        f'</div></div>'
    )


def _bounds(nodes, scale: float = 0.075) -> tuple[int, int, int, int]:
    if not nodes:
        return (400, 400, 0, 0)
    xs = [(n.get("x") or 0) for n in nodes]
    ys = [(n.get("y") or 0) for n in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = int((max_x - min_x) * scale) + 80
    h = int((max_y - min_y) * scale) + 80
    return (w, h, min_x, min_y)


def render_html(tree_data: dict, pick_count: dict, pts_dist: dict,
                hero_picks: dict[str, int], denom: int,
                spell_db: dict, hero_filter: str | None = None) -> str:
    """class / spec / hero 트리 HTML.

    pick_count: {node_id: char_count_picked}
    pts_dist:   {node_id: {rank: char_count_at_rank}}
    hero_picks: {hero_name: char_count}
    denom: 총 char 수 (top100=100, 단일캐릭=1)
    """
    if not tree_data:
        return _empty("이 스펙은 아직 트리 데이터 없음 — fetch_talent_trees.py 실행 필요")

    def pct_of(node) -> float:
        nid = node.get("id")
        if nid is None:
            return 0
        return pick_count.get(int(nid), 0) / max(1, denom) * 100

    def breakdown_of(node) -> dict[int, float]:
        nid = node.get("id")
        max_rank = node.get("max_rank") or 1
        out: dict[int, float] = {k: 0.0 for k in range(0, max_rank + 1)}
        if nid is None:
            out[0] = 100.0
            return out
        d = pts_dist.get(int(nid), {})
        total_picked = sum(d.values())
        for k, n in d.items():
            if k > max_rank:
                k = max_rank
            out[k] = out.get(k, 0.0) + (n / denom * 100)
        out[0] = max(0.0, (denom - total_picked) / denom * 100)
        return out

    TREE_SCALE = 0.075
    class_nodes = tree_data.get("class") or []
    spec_nodes = tree_data.get("spec") or []
    cw, ch, cmx, cmy = _bounds(class_nodes, TREE_SCALE)
    sw, sh, smx, smy = _bounds(spec_nodes, TREE_SCALE)

    class_html = "".join(_node_html(n, pct_of(n), breakdown_of(n), denom, spell_db,
                                     scale=TREE_SCALE, ox=cmx, oy=cmy)
                         for n in class_nodes)
    spec_html = "".join(_node_html(n, pct_of(n), breakdown_of(n), denom, spell_db,
                                    scale=TREE_SCALE, ox=smx, oy=smy)
                        for n in spec_nodes)

    hero_dict = tree_data.get("hero") or {}
    hero_html = ""
    hero_w, hero_h = 240, 600
    hero_header_html = "영웅 특성 — (없음)"
    if hero_dict:
        if hero_picks and sum(hero_picks.values()) > 0:
            ranked = sorted(hero_picks.items(), key=lambda x: -x[1])
        else:
            ranked = [(hn, 0) for hn in hero_dict]
        chosen_name = (hero_filter if (hero_filter and hero_filter in hero_dict)
                       else ranked[0][0])
        hero_nodes = hero_dict[chosen_name].get("nodes") or []
        hw, hh, hmx, hmy = _bounds(hero_nodes, TREE_SCALE)
        hero_w, hero_h = hw, hh
        hero_html = "".join(_node_html(n, pct_of(n), breakdown_of(n), denom, spell_db,
                                        scale=TREE_SCALE, ox=hmx, oy=hmy)
                            for n in hero_nodes)
        pick_total = max(1, sum(hero_picks.values()) if hero_picks else 1)
        ranking_html = []
        for hn, cnt in ranked:
            pct = cnt / pick_total * 100 if hero_picks else 0
            color = "#d97757" if hn == chosen_name else "#a39c8e"
            weight = "600" if hn == chosen_name else "400"
            ranking_html.append(
                f"<span style='color:{color};font-weight:{weight}'>"
                f"{_html_escape(hn)} {pct:.0f}%</span>"
            )
        hero_header_html = "영웅 특성 — " + " · ".join(ranking_html)

    body = f"""
    <div class='tree-wrap'>
      <div class='tree-row'>
        <div class='tree-col'>
          <h3>직업 특성</h3>
          <div class='tree-canvas' style='width:{cw}px;height:{ch}px'>{class_html}</div>
        </div>
        <div class='tree-col'>
          <h3>{hero_header_html}</h3>
          <div class='tree-canvas' style='width:{hero_w}px;height:{hero_h}px'>{hero_html}</div>
        </div>
        <div class='tree-col'>
          <h3>전문화 특성</h3>
          <div class='tree-canvas' style='width:{sw}px;height:{sh}px'>{spec_html}</div>
        </div>
      </div>
    </div>"""
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{TREE_CSS}</style></head>"
            f"<body>{body}<script>{TREE_TIP_JS}</script></body></html>")


# 툴팁 클램핑 — timeline 의 clampTip 과 동일 로직. tnode 호버 시 tip 이
# iframe viewport 밖으로 나가면 반대편으로 flip. talent tree 는 가로로 3컬럼
# (직업/영웅/전문화) 이라 우측 컬럼 노드 호버 시 tip 이 오른쪽 잘리기 쉬움.
TREE_TIP_JS = """
(function() {
  function clampTip(e) {
    const host = e.target.closest('.tnode');
    if (!host) return;
    const tip = host.querySelector(':scope > .tip');
    if (!tip) return;
    tip.style.left = ''; tip.style.right = ''; tip.style.top = ''; tip.style.bottom = '';
    const tipRect = tip.getBoundingClientRect();
    const hostRect = host.getBoundingClientRect();
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    if (tipRect.right > vw - 4) {
      const overflow = tipRect.right - (vw - 4);
      tip.style.left = (-8 - overflow) + 'px';
    } else if (tipRect.left < 4) {
      tip.style.left = (4 - hostRect.left) + 'px';
    }
    if (tipRect.top < 4) {
      tip.style.bottom = 'auto';
      tip.style.top = (hostRect.height + 4) + 'px';
    } else if (tipRect.bottom > vh - 4) {
      tip.style.top = 'auto';
      tip.style.bottom = (hostRect.height + 4) + 'px';
    }
  }
  document.addEventListener('mouseover', clampTip, true);
})();
"""
