"""WoW 한밤 레이드 로그 분석기 GUI.

PySide6 (Qt6) 기반 — Qt6 RHI 백엔드가 D3D11을 직접 써서 위젯 렌더는 GPU.
QtWebEngine(=Chromium)도 합쳐서 띄울 때 GPU 래스터/제로카피 활성화.

지금은 스켈레톤:
  - 영웅/신화 탭
  - 보스 목록
  - 직업/전문화 트리
  - 결과 패널 (다음 단계에서 채움: 캐스트 타임라인 + WoWhead 위젯)
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

# QtWebEngine GPU 풀 가속 (메인윈도 생성 전에 세팅해야 효과 있음)
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    " ".join([
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--enable-features=VaapiVideoDecoder,CanvasOopRasterization",
        "--ignore-gpu-blocklist",
    ]),
)
# Qt6 RHI 백엔드 명시 (Windows = D3D11)
os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")


# ─────────────────────────────────────────────────────────────────────────────
# 로깅 (다른 임포트 전에 세팅 — startup crash도 잡히도록)

def _runtime_dir() -> Path:
    """PyInstaller 번들이면 .exe 옆, 아니면 스크립트 옆."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


LOG_PATH = _runtime_dir() / "gui.log"
_log_fmt = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"

# Windows 콘솔이 cp949 라 유니코드 못 찍을 때 그냥 replace
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format=_log_fmt,
    handlers=[
        RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("gui")


def _excepthook(exc_type, exc_value, exc_tb):
    """잡히지 않은 예외도 로그에 남기고 그대로 흘림."""
    log.critical("UNCAUGHT EXCEPTION\n%s",
                 "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook
log.info("=== gui.py start  frozen=%s  log=%s ===",
         getattr(sys, "frozen", False), LOG_PATH)

import json

from themes import THEMES, build_qss, DEFAULT_THEME_ID, Theme

from PySide6.QtCore import Qt, QUrl, QSize, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QPalette, QPixmap
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ─────────────────────────────────────────────────────────────────────────────
# 도메인 데이터 (zone 46 = 한밤 첫 레이드)

# Blizzard 공식 ko_KR 매핑 (journal-encounter API 확인됨)
# WCL "zone 46 / VS DR MQD" = 3개 던전 묶음:
#   공허첨탑 (Voidspire, 6보스) · 쿠엘다나스 진격로 (March on Quel'Danas, 2보스) · 꿈의 균열 (Dreamrift, 1보스)
BOSSES: list[tuple[int, str, str]] = [
    (3176, "Imperator Averzian",          "전제군주 아베르지안"),
    (3177, "Vorasius",                    "보라시우스"),
    (3178, "Vaelgor & Ezzorak",           "바엘고어와 에조라크"),
    (3179, "Fallen-King Salhadaar",       "몰락한 왕 살라다르"),
    (3180, "Lightblinded Vanguard",       "빛에 눈이 먼 선봉대"),
    (3181, "Crown of the Cosmos",         "우주의 왕관"),
    (3182, "Belo'ren, Child of Al'ar",    "알라르의 자손 벨로렌"),
    (3306, "Chimaerus, the Undreamt God", "꿈결을 벗어난 신 카이메루스"),
    (3183, "Midnight Falls",              "한밤의 도래"),
]

CLASSES: dict[str, list[str]] = {
    "Death Knight": ["Frost", "Unholy"],
    "Demon Hunter": ["Devourer", "Havoc"],
    "Druid":        ["Balance", "Feral"],
    "Evoker":       ["Augmentation", "Devastation"],
    "Hunter":       ["Beast Mastery", "Marksmanship", "Survival"],
    "Mage":         ["Arcane", "Fire", "Frost"],
    "Monk":         ["Windwalker"],
    "Paladin":      ["Retribution"],
    "Priest":       ["Shadow"],
    "Rogue":        ["Assassination", "Outlaw", "Subtlety"],
    "Shaman":       ["Elemental", "Enhancement"],
    "Warlock":      ["Affliction", "Demonology", "Destruction"],
    "Warrior":      ["Arms", "Fury"],
}

CLASS_KR: dict[str, str] = {
    "Death Knight": "죽음의 기사", "Demon Hunter": "악마사냥꾼",
    "Druid":        "드루이드",   "Evoker":       "기원사",
    "Hunter":       "사냥꾼",     "Mage":         "마법사",
    "Monk":         "수도사",     "Paladin":      "성기사",
    "Priest":       "사제",       "Rogue":        "도적",
    "Shaman":       "주술사",     "Warlock":      "흑마법사",
    "Warrior":      "전사",
}

SPEC_KR: dict[str, str] = {
    "Frost": "냉기", "Unholy": "부정",
    "Devourer": "포식자", "Havoc": "파멸",
    "Balance": "조화", "Feral": "야성",
    "Augmentation": "증강", "Devastation": "황폐",
    "Beast Mastery": "야수", "Marksmanship": "사격", "Survival": "생존",
    "Arcane": "비전", "Fire": "화염",
    "Windwalker": "풍운",
    "Retribution": "징벌",
    "Shadow": "암흑",
    "Assassination": "암살", "Outlaw": "무법", "Subtlety": "잠행",
    "Elemental": "정기", "Enhancement": "고양",
    "Affliction": "고통", "Demonology": "악마", "Destruction": "파괴",
    "Arms": "무기", "Fury": "분노",
}

# ─────────────────────────────────────────────────────────────────────────────
# 데이터 로더 — lazy, 전역 1회

_data: dict[str, object] = {}


def _data_dir() -> Path | None:
    """data/ 디렉토리 위치 찾기 — 개발(.py)/번들(.exe) 양쪽 지원."""
    candidates = [
        _runtime_dir() / "data",                    # script 옆
        _runtime_dir().parent / "data",             # .exe 의 한 단계 위
        _runtime_dir().parent.parent / "data",      # dist/LogAnalyze/ 의 두 단계 위 (개발 트리)
        Path.cwd() / "data",
    ]
    for c in candidates:
        if (c / "rankings_with_talents.csv").exists():
            return c.resolve()
    return None


DATA_DIR = _data_dir()
log.info("DATA_DIR = %s", DATA_DIR)


def _load_csv(filename: str):
    if not DATA_DIR:
        return None
    key = f"csv:{filename}"
    if key in _data:
        return _data[key]
    import pandas as pd
    try:
        df = pd.read_csv(DATA_DIR / filename, low_memory=False)
        df["report_id"] = df.get("report_id", "").astype(str) if "report_id" in df.columns else df.get("report_id")
        if "fight_id" in df.columns:
            df["fight_id"] = df["fight_id"].astype(int)
        _data[key] = df
        log.info("loaded CSV %s: %d rows", filename, len(df))
        return df
    except Exception as e:
        log.exception("CSV load failed: %s", filename)
        return None


ICON_CACHE_DIR = (DATA_DIR / "icons") if DATA_DIR else (_runtime_dir() / "icon_cache")
_icon_cache: dict[str, QIcon] = {}


def _icon_for(icon_filename: str) -> QIcon | None:
    """zamimg 에서 아이콘 파일을 받아 캐시. 동기 — 첫 호출 ~수백ms, 이후 즉시."""
    if not icon_filename:
        return None
    if icon_filename in _icon_cache:
        return _icon_cache[icon_filename]
    cache_path = ICON_CACHE_DIR / icon_filename
    if not cache_path.exists():
        ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import requests
            url = f"https://wow.zamimg.com/images/wow/icons/medium/{icon_filename}"
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                cache_path.write_bytes(r.content)
            else:
                log.warning("icon %s -> HTTP %d", icon_filename, r.status_code)
        except Exception:
            log.exception("icon fetch fail: %s", icon_filename)
            return None
    if not cache_path.exists():
        return None
    pm = QPixmap(str(cache_path))
    if pm.isNull():
        return None
    icon = QIcon(pm)
    _icon_cache[icon_filename] = icon
    return icon


def _build_tooltip(spell_meta: dict) -> str:
    """spell meta → Qt rich-text 툴팁 (한글 + 영문 + 설명)."""
    name_ko = spell_meta.get("name_ko") or ""
    name_en = spell_meta.get("name_en") or ""
    # description_ko (Blizzard) 우선, 없으면 tooltip_ko (Wowhead HTML)
    body = spell_meta.get("description_ko") or spell_meta.get("tooltip_ko") or ""
    title = name_ko or name_en or "(이름 없음)"
    subtitle = f" <span style='color:#a39c8e;font-size:9pt'>({name_en})</span>" if name_ko and name_en else ""
    return (
        f"<html><body>"
        f"<div style='max-width:480px'>"
        f"<div style='color:#d97757;font-size:11pt;font-weight:600;margin-bottom:4px'>{title}{subtitle}</div>"
        f"<div style='color:#f5f0e8'>{body}</div>"
        f"</div></body></html>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# V2 cache 직접 접근 — V2Data 의 dict 를 그대로 lookup (cache.db 안 씀)

# V2Data 싱글톤 — v2_cache_*.json dict 를 직접 들고 lookup. cache.db 안 씀.
# 첫 호출 시 4개 JSON (~150MB) 로드 — 3-5초 freeze. 이후 dict O(1).
_v2: object | None = None


def _v2_data():
    """V2Data 싱글톤 lazy init. 실패하면 None (.env 키 없음 / V2Data 로드 실패).

    DATA_DIR 을 명시적으로 넘겨야 frozen .exe 에서도 진짜 data/ 폴더를 본다.
    (wcl_v2_data 의 `Path(__file__).parent` 는 _internal/ 로 resolve 됨)
    """
    global _v2
    if _v2 is not None:
        return _v2
    try:
        from wcl_v2_data import V2Data
        v2 = V2Data(data_dir=DATA_DIR)
        log.info("V2Data loaded from %s: meta=%d pfight=%d events=%d damage=%d",
                 v2.data_dir, len(v2.meta), len(v2.pfight), len(v2.events), len(v2.damage))
        _v2 = v2
    except Exception:
        log.exception("V2Data init fail")
    return _v2


def db_casts(rid: str, fid: int, sid: int) -> list[tuple]:
    """[(ts, spell_id, type), ...] — V2 cache events 직접 lookup."""
    v2 = _v2_data()
    if v2 is None:
        return []
    ev = v2.events.get(f"{rid}:{fid}:{sid}")
    if not isinstance(ev, dict):
        return []
    out = []
    for e in ev.get("casts") or []:
        if not isinstance(e, list) or len(e) < 2:
            continue
        try:
            ts = int(e[0]); sp = int(e[1])
        except (TypeError, ValueError):
            continue
        tp = e[2] if len(e) > 2 else "cast"
        out.append((ts, sp, tp))
    return out


def db_buffs(rid: str, fid: int, sid: int) -> list[tuple]:
    """[(ts, spell_id, type[, stack]), ...] — V2 cache events 직접 lookup."""
    v2 = _v2_data()
    if v2 is None:
        return []
    ev = v2.events.get(f"{rid}:{fid}:{sid}")
    if not isinstance(ev, dict):
        return []
    out = []
    for e in ev.get("buffs") or []:
        if not isinstance(e, list) or len(e) < 2:
            continue
        try:
            ts = int(e[0]); sp = int(e[1])
        except (TypeError, ValueError):
            continue
        rec = [ts, sp, e[2] if len(e) > 2 else ""]
        if len(e) > 3 and e[3] is not None:
            rec.append(e[3])
        out.append(tuple(rec))
    return out


def db_source_id(rid: str, char_name: str) -> int | None:
    """meta.actors 우선, 없으면 pfight 의 sourceID fallback."""
    v2 = _v2_data()
    if v2 is None:
        return None
    meta = v2.meta.get(rid)
    if isinstance(meta, dict):
        actors = meta.get("actors") or {}
        sid = actors.get(char_name)
        if isinstance(sid, int):
            return sid
    # fallback: pfight 의 sourceID — player_fight() 가 fetch 시 채워둠
    prefix = f"{rid}:"
    suffix = f":{char_name}"
    for key, pf in v2.pfight.items():
        if key.startswith(prefix) and key.endswith(suffix) and isinstance(pf, dict):
            sid = pf.get("sourceID")
            if isinstance(sid, int):
                return sid
    return None


def db_fight_window(rid: str, fid: int) -> list | None:
    """[start_ms, end_ms] — V2 cache meta 의 fights 에서 lookup."""
    v2 = _v2_data()
    if v2 is None:
        return None
    meta = v2.meta.get(rid)
    if not isinstance(meta, dict):
        return None
    for f in meta.get("fights") or []:
        if f.get("id") == fid:
            start, end = f.get("startTime"), f.get("endTime")
            if start is None or end is None:
                return None
            try:
                return [int(start), int(end)]
            except (TypeError, ValueError):
                return None
    return None


def db_damage(rid: str, fid: int, sid: int) -> list[dict]:
    """[{guid, name, icon, total}, ...] — V2 cache damage 직접 lookup."""
    v2 = _v2_data()
    if v2 is None:
        return []
    entries = v2.damage.get(f"{rid}:{fid}:{sid}")
    if not isinstance(entries, list):
        return []
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        gid = e.get("guid")
        if not isinstance(gid, int):
            continue
        out.append({
            "guid": gid,
            "name": e.get("name") or "",
            "icon": e.get("icon") or "",
            "total": int(e.get("total") or 0),
        })
    return out


def db_talent_counts_for_ranks(
    rid_fid_char: list[tuple[str, int, str]],
) -> tuple[dict[int, int], dict[int, dict[int, int]], int]:
    """(rid, fid, char) → (picks_by_tid, pts_dist_by_tid, matched_chars).

    pts_dist[tid] = {1: n_1pt, 2: n_2pt, ...} — 포인트별 픽 카운트.
    matched - sum(pts_dist[tid].values()) = "0pt (안 찍은) " 카운트.
    옛 cache 엔트리 (talent_points 없음) 는 1pt 로 간주.
    """
    v2 = _v2_data()
    if v2 is None or not rid_fid_char:
        return {}, {}, 0
    counts: dict[int, int] = {}
    dist: dict[int, dict[int, int]] = {}
    matched = 0
    for rid, fid, char in rid_fid_char:
        pf = v2.pfight.get(f"{rid}:{fid}:{char}")
        if not isinstance(pf, dict):
            continue
        talents = pf.get("talents") or []
        if not talents:
            continue
        matched += 1
        points = pf.get("talent_points") or {}
        for tid in talents:
            if not isinstance(tid, int):
                continue
            pts = points.get(str(tid)) if isinstance(points, dict) else None
            if not isinstance(pts, int) or pts < 1:
                pts = 1
            counts[tid] = counts.get(tid, 0) + 1
            d = dist.setdefault(tid, {})
            d[pts] = d.get(pts, 0) + 1
    return counts, dist, matched


def db_node_picks_for_ranks(
    rid_fid_char: list[tuple[str, int, str]],
) -> tuple[dict[int, int], dict[int, dict[int, int]], int]:
    """node_id 기반 픽 카운트 — Blizzard tree 와 매칭되는 유일한 키.

    WCL combatantInfo.talentTree[].nodeID ↔ Blizzard talent-tree node.id.
    같은 node 가 N 회 등장 = rank N 으로 찍음.

    returns: (picks_by_node, rank_dist_by_node, matched_chars)
    """
    v2 = _v2_data()
    if v2 is None or not rid_fid_char:
        return {}, {}, 0
    from collections import Counter
    counts: dict[int, int] = {}
    rank_dist: dict[int, dict[int, int]] = {}
    matched = 0
    for rid, fid, char in rid_fid_char:
        pf = v2.pfight.get(f"{rid}:{fid}:{char}")
        if not isinstance(pf, dict):
            continue
        nodes = pf.get("nodes") or []
        if not nodes:
            continue
        matched += 1
        per_node = Counter(int(n) for n in nodes if isinstance(n, int))
        for nid, rk in per_node.items():
            counts[nid] = counts.get(nid, 0) + 1
            d = rank_dist.setdefault(nid, {})
            d[rk] = d.get(rk, 0) + 1
    return counts, rank_dist, matched


def hero_tree_picks(tree_data: dict, rid_fid_char: list[tuple[str, int, str]]) -> dict[str, int]:
    """각 영웅 트리별로 몇 명이 골랐는지. 한 캐릭 = 한 영웅 트리 (가장 매칭 많은 거)."""
    v2 = _v2_data()
    if v2 is None or not tree_data:
        return {}
    hero_dict = tree_data.get("hero") or {}
    hero_tids: dict[str, set[int]] = {}
    for hn, hd in hero_dict.items():
        tids: set[int] = set()
        for n in hd.get("nodes") or []:
            for opt in n.get("options") or []:
                tid = opt.get("talent_id")
                if isinstance(tid, int):
                    tids.add(tid)
        hero_tids[hn] = tids
    picks: dict[str, int] = {hn: 0 for hn in hero_dict}
    for rid, fid, char in rid_fid_char:
        pf = v2.pfight.get(f"{rid}:{fid}:{char}")
        if not isinstance(pf, dict):
            continue
        talents = set(t for t in (pf.get("talents") or []) if isinstance(t, int))
        if not talents:
            continue
        best_hn = None
        best_n = 0
        for hn, tids in hero_tids.items():
            n = len(talents & tids)
            if n > best_n:
                best_n = n
                best_hn = hn
        if best_hn:
            picks[best_hn] += 1
    return picks


def _load_json(filename: str) -> dict:
    if not DATA_DIR:
        return {}
    key = f"json:{filename}"
    if key in _data:
        return _data[key]  # type: ignore
    p = DATA_DIR / filename
    if not p.exists():
        log.warning("missing JSON: %s", p)
        _data[key] = {}
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        _data[key] = obj
        log.info("loaded JSON %s: %d keys", filename, len(obj))
        return obj
    except Exception:
        log.exception("JSON load failed: %s", filename)
        _data[key] = {}
        return {}


# 클래스별 컬러 (공식 와우 클래스 컬러 hex)
CLASS_COLOR: dict[str, str] = {
    "Death Knight": "#C41E3A", "Demon Hunter": "#A330C9",
    "Druid":        "#FF7C0A", "Evoker":       "#33937F",
    "Hunter":       "#AAD372", "Mage":         "#3FC7EB",
    "Monk":         "#00FF98", "Paladin":      "#F48CBA",
    "Priest":       "#FFFFFF", "Rogue":        "#FFF468",
    "Shaman":       "#0070DD", "Warlock":      "#8788EE",
    "Warrior":      "#C69B6D",
}


# ─────────────────────────────────────────────────────────────────────────────
# 테마 시스템 (4종, 사용자 선택 + 디스크 저장)

def _settings_path() -> Path:
    """user_settings.json 위치 — data/ 가 있으면 거기, 아니면 runtime dir."""
    if DATA_DIR:
        return DATA_DIR / "user_settings.json"
    return _runtime_dir() / "user_settings.json"


def _load_theme_id() -> str:
    p = _settings_path()
    if not p.exists():
        return DEFAULT_THEME_ID
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        tid = d.get("theme")
        if isinstance(tid, str) and tid in THEMES:
            return tid
    except Exception:
        log.exception("user_settings load fail")
    return DEFAULT_THEME_ID


def _save_theme_id(tid: str) -> None:
    p = _settings_path()
    try:
        d: dict = {}
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8")) or {}
        d["theme"] = tid
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("theme saved: %s", tid)
    except Exception:
        log.exception("user_settings save fail")


def apply_theme(app: QApplication, theme: Theme) -> None:
    """Fusion + 테마별 QSS + QPalette 적용. 런타임 전환에도 동일하게 호출."""
    app.setStyle("Fusion")
    app.setStyleSheet(build_qss(theme))
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(theme.bg))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(theme.text))
    pal.setColor(QPalette.ColorRole.Base,            QColor(theme.surface))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(theme.surface_alt))
    pal.setColor(QPalette.ColorRole.Text,            QColor(theme.text))
    pal.setColor(QPalette.ColorRole.Button,          QColor(theme.surface_alt))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(theme.text))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(theme.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.bg))
    pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor(theme.surface))
    pal.setColor(QPalette.ColorRole.ToolTipText,     QColor(theme.text))
    app.setPalette(pal)
    log.info("theme applied: %s (%s)", theme.id, theme.name_kr)


# ─────────────────────────────────────────────────────────────────────────────
# 패널 위젯

def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def vbox_panel(title: str, content: QWidget) -> QWidget:
    """제목 + 본문이 묶인 세로 패널."""
    wrap = QWidget()
    layout = QVBoxLayout(wrap)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(section_label(title))
    layout.addWidget(content, 1)
    return wrap


# ─────────────────────────────────────────────────────────────────────────────
# 가로 타임라인 (HTML/CSS, QWebEngineView 위에)

TIMELINE_CSS = """
body {
    background: #1a1614;
    color: #f5f0e8;
    font-family: 'Pretendard Variable', 'Pretendard', 'Segoe UI', sans-serif;
    font-size: 11px;
    margin: 0;
    padding: 0;
    --pps: 160;   /* px per second, JS wheel 로 변경 */
}
body.horizontal { overflow-x: auto; overflow-y: visible; padding-top: 240px; --cast-offset: 180px; }
body.vertical   { overflow-x: visible; overflow-y: auto; padding-left: 240px; --cast-offset: 0px; }
/* 버프 lane 토글 — ComparisonTab 의 체크박스에서 JS 로 hide-buffs 클래스 토글 */
body.hide-buffs .buffs, body.hide-buffs .buff-label { display: none !important; }
/* 시간 → 픽셀 매핑 — 좌측 cast-offset (라벨 영역) + 초 * pps */
body.horizontal .pos-t { left: calc(var(--cast-offset, 0px) + var(--t) * var(--pps) * 1px); }
body.vertical   .pos-t { top:  calc(var(--t) * var(--pps) * 1px); }
body.horizontal .size-w { width:  max(8px, calc(var(--w) * var(--pps) * 1px)); }
body.vertical   .size-w { height: max(8px, calc(var(--w) * var(--pps) * 1px)); }
body.horizontal .span-d { width:  calc(var(--cast-offset, 0px) + var(--d) * var(--pps) * 1px); }
body.vertical   .span-d { height: calc(var(--d) * var(--pps) * 1px); }
.wrap { padding: 12px 14px; }
.empty {
    color: #a39c8e; text-align: center; padding: 80px 16px;
    background: #221d1a; border: 1px dashed #3a322c; border-radius: 6px;
}
.hdr {
    color: #d97757; font-size: 12px; font-weight: 600;
    margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #3a322c;
}
.timeline { position: relative; }
.lane-label {
    color: #a39c8e; font-size: 10px; padding: 2px 6px;
    background: #221d1a; border-radius: 3px; margin: 8px 0 4px 0;
    display: inline-block;
}

/* === 시간 축 ====================================================== */
.tick { position: absolute; color: transparent; }
.horizontal .axis  { position: relative; height: 26px; border-bottom: 1px solid #4a4039; margin-bottom: 8px; }
.horizontal .tick.label { color: #a39c8e; font-size: 10px; width: auto; background: none; padding-left: 4px; line-height: 26px; top: 0; height: 26px; }

.vertical .axis  { position: absolute; left: 0; top: 0; width: 32px; border-right: 1px solid #3a322c; }
.vertical .tick.label {
    left: 0; width: 22px; height: auto; background: none;
    color: #a39c8e; font-size: 10px; text-align: right; padding-right: 4px;
}

/* === 그리드 — 1초 간격 minor + 5초 간격 major, 시전/버프 영역까지 내려감 === */
.grid { position: absolute; top: 0; left: 0; right: 0; bottom: 0; pointer-events: none; z-index: 0; }
/* 모든 초 선 동일 색/투명도 (0s, 1s, 5s 구분 없음) */
.horizontal .gline { position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(245, 240, 232, 0.15); }
.vertical .gline { position: absolute; left: 0; right: 0; height: 1px; background: rgba(245, 240, 232, 0.15); }

/* === 시전 / 버프 lane 컨테이너 ==================================== */
.casts, .buffs { position: relative; }
.horizontal .casts { height: 32px; margin-bottom: 8px; }
/* 버프 lane 배경 투명 — 그리드 선 가리지 않게. 살짝 어둠 톤만 (반투명) */
.horizontal .buffs { background: rgba(31, 26, 23, 0.45); border-radius: 4px; padding: 4px 0; }
.vertical  .lanes  { position: absolute; left: 36px; top: 0; right: 0; }
.vertical  .lanes-buffs { left: auto; right: 0; }

/* === 캐스트 아이콘 + duration bar (WCL 스타일 per-spell 행) ============= */
.cast {
    position: absolute;
    width: 28px; height: 28px;
    z-index: 2;
}
.cast img {
    width: 28px; height: 28px; display: block;
    border: 1px solid #4a4039; border-radius: 4px; box-sizing: border-box;
    position: relative; z-index: 2;
}
.cast:hover img { border-color: #d97757; }
.cast:hover { z-index: 10; }
/* duration bar — 아이콘 시작점부터 cast 완료 시점까지 늘어남 */
.horizontal .cast-bar {
    position: absolute; top: 4px; left: 14px;
    height: 20px; width: calc(var(--d) * var(--pps) * 1px);
    background: linear-gradient(to right,
        rgba(217,119,87,0.55) 0%, rgba(217,119,87,0.25) 60%, rgba(217,119,87,0.10) 100%);
    border-radius: 0 3px 3px 0;
    z-index: 1; pointer-events: none;
}

/* 스펠 행 좌측 라벨 (아이콘 + 이름 + 시전 횟수) — pos-t 가 아니라 left: 0 고정 */
.cast-row-label {
    position: absolute; left: 0;
    width: 172px; height: 28px;
    background: rgba(26, 22, 20, 0.94);
    border-right: 1px solid #3a322c;
    padding: 0 8px;
    display: flex; align-items: center; gap: 6px;
    font-size: 11px; color: #f5f0e8;
    z-index: 4;
    overflow: hidden;
    pointer-events: none;
}
.cast-row-label img { width: 22px; height: 22px; border-radius: 3px; flex: 0 0 22px; }
.cast-row-label .rname {
    flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    color: #f5f0e8;
}
/* === 버프 막대 + 아이콘 (24px 막대) ================================ */
.buff {
    position: absolute; padding: 0; overflow: hidden;
    background: #3a322c; border: 1px solid #4a4039;
    color: #f5f0e8; border-radius: 3px;
    font-size: 11px; box-sizing: border-box;
}
.buff:hover { border-color: #d97757; z-index: 5; }
.horizontal .buff { height: 24px; line-height: 24px; }
.vertical  .buff { width: 28px; }
.buff img.bicon {
    width: 20px; height: 20px;
    vertical-align: middle; border-radius: 3px;
}
.horizontal .buff img.bicon { float: left; margin: 1px 5px 0 1px; }
.vertical  .buff img.bicon { display: block; margin: 1px auto; }
.buff .blbl {
    display: inline-block; vertical-align: middle;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.horizontal .buff .blbl { max-width: calc(100% - 30px); }
.vertical  .buff .blbl { display: none; }

/* === 툴팁 (캐스트 / 버프 공용) ==================================== */
.tip {
    display: none; position: absolute;
    background: #15110f; color: #f5f0e8;
    border: 1px solid #4a4039; border-radius: 6px;
    padding: 10px 12px; min-width: 280px; max-width: 460px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.6);
    z-index: 99999; pointer-events: none;
    font-size: 11px;
    max-height: 60vh; overflow-y: auto;
}
.cast:hover .tip, .buff:hover .tip { display: block; }
.horizontal .cast .tip { bottom: 34px; left: -8px; }
.horizontal .buff .tip { bottom: 22px; left: 0; }
.vertical  .cast .tip { left: 34px; top: -8px; }
.vertical  .buff .tip { left: 28px; top: 0; }
.tip .tname { color: #d97757; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.tip .ten { color: #a39c8e; font-style: italic; font-size: 10px; margin-bottom: 6px; }
.tip .tbody table { font-size: 11px; }
/* 모든 stacking 컨테이너 overflow: visible — tooltip 잘림 방지 */
html { overflow: visible; }
.wrap, .timeline, .casts, .buffs, .lanes { overflow: visible; }
"""


def _compute_buff_intervals(events: list) -> list[tuple[int, int, int]]:
    """버프 이벤트들에서 (spell_id, t_start_ms, t_end_ms) 리스트 추출.

    applybuff <-> removebuff 페어. refreshbuff 는 무시 (연장만 됨).
    fight 끝까지 닫히지 않은 건 호출자가 fight_end 로 처리해도 됨.
    """
    out: list[tuple[int, int, int]] = []
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
        # refreshbuff: 이미 떠있는 버프 연장 — 시작/끝 변경 안 함
    return out, open_buffs


def _html_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


class RotationTimeline(QWebEngineView):
    """랭킹 행 1개에 대한 가로 타임라인 (시전 아이콘 + 버프 바)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self._buffs_visible: bool = True  # ComparisonTab 체크박스로 토글됨
        self.set_empty("랭킹에서 캐릭터 클릭")

    def set_buffs_visible(self, visible: bool) -> None:
        """버프 lane 표시/숨김 — 재렌더 없이 JS 로 body class 토글 + 상태 저장."""
        self._buffs_visible = bool(visible)
        # 현재 페이지에 즉시 적용 (다음 렌더에서는 _wrap 의 body_class 가 처리)
        js = ("document.body && document.body.classList."
              + ("remove" if visible else "add")
              + "('hide-buffs');")
        self.page().runJavaScript(js)

    # ── 공용 ─────────────────────────────────────────────────────────────
    def set_empty(self, text: str) -> None:
        body = f"<div class='wrap'><div class='empty'>{_html_escape(text)}</div></div>"
        self.setHtml(self._wrap(body, "horizontal"))

    def _wrap(self, body: str, body_class: str) -> str:
        zoom_js = """
        <script>
        (function() {
          // 시간축만 줌 — body 의 --pps 만 변경, 아이콘은 그대로
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
            // anchor (마우스 좌표) 가 화면에서 같은 시간을 가리키도록 scroll 보정
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

          // 클릭 드래그 패닝
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
          // 드래그 가속 — 마우스 1px → 화면 2.4px 이동 (느린 체감 보정)
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
          const endDrag = () => {
            if (dragging) { dragging = false; body.style.cursor = 'grab'; }
          };
          ['mouseup', 'mouseleave'].forEach(ev =>
            document.addEventListener(ev, endDrag)
          );
        })();
        </script>
        """
        # 버프 숨김 상태면 body class 에 hide-buffs 추가 (재렌더 후에도 유지)
        if not self._buffs_visible:
            body_class = body_class + " hide-buffs"
        return ("<!doctype html><html><head><meta charset='utf-8'><style>"
                + TIMELINE_CSS + "</style></head>"
                + f"<body class='{body_class}'>" + body + zoom_js + "</body></html>")

    # ── 메인 렌더 ─────────────────────────────────────────────────────────
    def render_fight(self, *, char: str, cast_events: list, buff_events: list,
                     fight_window: list, spell_db: dict,
                     orientation: str = "h") -> None:
        if not fight_window or not cast_events:
            self.set_empty("이 fight에 데이터 없음")
            return

        is_v = (orientation == "v")
        start_ms = int(fight_window[0])
        end_ms = int(fight_window[1])
        duration_s = max((end_ms - start_ms) / 1000.0, 1.0)

        ICON_PX = 40
        # DEFAULT_PPS = 기본 시간축 스케일. JS wheel 이 런타임에 var(--pps) 만 변경.
        DEFAULT_PPS = 160.0
        BUFF_LANE_PX = 26
        ICON_TIME = ICON_PX / DEFAULT_PPS  # 아이콘이 차지하는 "기본" 시간 (= 0.25s)

        CAST_ROW_H = 32   # 스펠 행 높이
        CAST_LABEL_W = 180  # 좌측 스펠명/아이콘 라벨 영역

        # ── 시전: begincast → cast 페어로 duration 인터벌 만들기 ──────────────
        # 이벤트: [ts, spell_id, type='begincast'|'cast']
        cast_intervals: list[tuple[int, int, int]] = []  # (start_ts, end_ts, sid)
        open_casts: dict[int, int] = {}  # sid → begincast_ts (instant 면 cast 직전 begincast 없음)
        for ev in cast_events:
            if len(ev) < 3:
                continue
            ts = int(ev[0]); sid = int(ev[1]); kind = ev[2]
            if kind == "begincast":
                open_casts[sid] = ts
            elif kind == "cast":
                begin_ts = open_casts.pop(sid, ts)
                if begin_ts > ts:
                    begin_ts = ts  # 이상한 페어 방어
                cast_intervals.append((begin_ts, ts, sid))
        cast_intervals.sort()

        # 미완료 begincast (다음 cast 매칭 안 됨) — 그냥 instant 로 처리
        for sid, ts in open_casts.items():
            cast_intervals.append((ts, ts, sid))
        cast_intervals.sort()

        # 시간 윈도우 안쪽만
        cast_intervals = [iv for iv in cast_intervals if iv[1] >= start_ms]

        # 스펠별 첫 시전 시각 — 시간순 lane 배정 (이름 있는 거 우선, 그 다음 첫 시전 빠른 순)
        # 카운트 기반 정렬은 제거 — 사용자 요청: "시전 횟수 별로 파싱하는건 중요하지않다"
        first_cast_ts: dict[int, int] = {}
        for start_ts, _end_ts, sid in cast_intervals:
            if sid not in first_cast_ts:
                first_cast_ts[sid] = start_ts

        def _cast_has_name(sid: int) -> bool:
            m = spell_db.get(str(sid), {})
            return bool(m.get("name_ko") or m.get("name_en"))

        cast_sids_sorted = sorted(
            first_cast_ts.keys(),
            key=lambda s: (0 if _cast_has_name(s) else 1, first_cast_ts[s], s),
        )
        cast_lane: dict[int, int] = {sid: i for i, sid in enumerate(cast_sids_sorted)}
        casts_lane_span = max(len(cast_lane), 1) * CAST_ROW_H

        # ── 버프: lane 배정 — 이름 있는 버프만 ────────────────────────────
        all_intervals, still_open = _compute_buff_intervals(buff_events or [])
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

        # ── HTML 빌드 — 모든 시간 좌표는 CSS var(--t) / var(--w) / var(--d) ──
        cast_html: list[str] = []
        for start_ts, end_ts, sid in cast_intervals:
            t_rel = max((start_ts - start_ms) / 1000.0, 0)
            dur_s = max((end_ts - start_ts) / 1000.0, 0)
            lane_pos = cast_lane.get(sid, 0) * CAST_ROW_H
            cast_html.append(
                self._cast_row_html(sid, lane_pos, t_rel, dur_s, spell_db, is_v)
            )

        # 좌측 스펠 라벨 (스펠 아이콘 + 이름) — 한 행 당 하나. 카운트 표시는 제거.
        cast_label_html: list[str] = []
        for sid in cast_sids_sorted:
            meta = spell_db.get(str(sid), {})
            icon = meta.get("icon") or ""
            name = meta.get("name_ko") or meta.get("name_en") or f"#{sid}"
            lane_pos = cast_lane[sid] * CAST_ROW_H
            icon_html = (
                f"<img src='https://wow.zamimg.com/images/wow/icons/medium/{icon}'>"
                if icon else "<span class='no-icon'></span>"
            )
            cast_label_html.append(
                f'<div class="cast-row-label" style="top:{lane_pos}px">'
                f'{icon_html}'
                f'<span class="rname">{_html_escape(name)}</span>'
                f'</div>'
            )

        buff_html: list[str] = []
        for sid, t_start, t_end in intervals:
            t_rel_start = max((t_start - start_ms) / 1000.0, 0)
            dur_s = (t_end - t_start) / 1000.0
            lane_pos = buff_lane.get(sid, 0) * BUFF_LANE_PX
            buff_html.append(self._buff_html(sid, lane_pos, t_rel_start, dur_s, spell_db, is_v))

        # grid lines + labels — 매 초마다 동일 스타일
        grid_html: list[str] = []
        label_html: list[str] = []
        for s in range(0, int(duration_s) + 1):
            grid_html.append(f'<div class="gline pos-t" style="--t:{s}"></div>')
            label_html.append(f'<div class="tick label pos-t" style="--t:{s}">{s}s</div>')

        # 컨테이너 — span-d 클래스 + --d 변수 (duration 초)
        d_attr = f"--d:{duration_s:.3f}"
        if is_v:
            timeline_style = f"{d_attr}"
            axis_style = "span-d"
            casts_style = f"width:{casts_lane_span}px"
            buffs_style = f"width:{buffs_lane_span}px"
            casts_left = 36
            buffs_left = 36 + casts_lane_span + 12
        else:
            timeline_style = f"{d_attr}"
            axis_style = "span-d"
            casts_style = f"height:{casts_lane_span}px"
            buffs_style = f"height:{buffs_lane_span}px"
            casts_left = 0
            buffs_left = 0

        if is_v:
            body = f'''
            <div class="wrap">
                <div class="hdr">{_html_escape(char)} · fight {duration_s:.1f}s
                    · 시전 {len(cast_intervals)}회 ({len(cast_lane)}개 스펠)
                    · 버프 인터벌 {len(intervals)}개
                    {f' (미상 {hidden_unknown_buffs}개 숨김)' if hidden_unknown_buffs else ''}
                    · 휠=줌 · 더블클릭=리셋</div>
                <div class="timeline span-d" style="{timeline_style}">
                    <div class="grid span-d">{"".join(grid_html)}</div>
                    <div class="axis {axis_style} span-d">{"".join(label_html)}</div>
                    <div class="casts lanes span-d" style="{casts_style};left:{casts_left}px">
                        {"".join(cast_html)}
                        {"".join(cast_label_html)}
                    </div>
                    <div class="buffs lanes lanes-buffs span-d" style="{buffs_style};left:{buffs_left}px">
                        {"".join(buff_html)}
                    </div>
                </div>
            </div>
            '''
            body_class = "vertical"
        else:
            body = f'''
            <div class="wrap">
                <div class="hdr">{_html_escape(char)} · fight {duration_s:.1f}s
                    · 시전 {len(cast_intervals)}회 ({len(cast_lane)}개 스펠)
                    · 버프 인터벌 {len(intervals)}개
                    {f' (미상 {hidden_unknown_buffs}개 숨김)' if hidden_unknown_buffs else ''}
                    · 휠=줌 · 더블클릭=리셋</div>
                <div class="timeline span-d" style="{timeline_style}">
                    <div class="grid span-d">{"".join(grid_html)}</div>
                    <div class="axis {axis_style} span-d">{"".join(label_html)}</div>
                    <span class="lane-label">시전 (스펠별 행)</span>
                    <div class="casts span-d" style="{casts_style}">
                        {"".join(cast_html)}
                        {"".join(cast_label_html)}
                    </div>
                    <span class="lane-label buff-label">버프</span>
                    <div class="buffs span-d" style="{buffs_style}">
                        {"".join(buff_html)}
                    </div>
                </div>
            </div>
            '''
            body_class = "horizontal"
        self.setHtml(self._wrap(body, body_class))

    @staticmethod
    def _cast_row_html(sid: int, lane_pos: int, t_rel: float, dur_s: float,
                       spell_db: dict, is_v: bool) -> str:
        """스펠별 행에 들어가는 단일 cast event — 아이콘 + (cast time 있으면) duration bar."""
        meta = spell_db.get(str(sid), {})
        icon = meta.get("icon") or ""
        tip_body = (meta.get("description_ko") or meta.get("tooltip_ko")
                    or meta.get("tooltip_en") or "")
        # Wowhead raw HTML 평문화
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
        # cast time 있으면 duration bar (아이콘 뒤로 늘어남)
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

    @staticmethod
    def _buff_html(sid: int, lane_pos: int, t_rel_start: float, dur_s: float,
                   spell_db: dict, is_v: bool) -> str:
        meta = spell_db.get(str(sid), {})
        icon = meta.get("icon") or ""
        tip_body = meta.get("tooltip_ko") or meta.get("tooltip_en") or ""
        icon_url = (f"https://wow.zamimg.com/images/wow/icons/medium/{icon}"
                    if icon else "")
        title, sub = _resolve_name(sid, spell_db)
        label = title
        subtitle = (f'<div class="ten">{_html_escape(sub)} · 지속 {dur_s:.1f}s</div>'
                    if sub else f'<div class="ten">지속 {dur_s:.1f}s</div>')
        # --t = 시작 시간 (초), --w = 지속 시간 (초). CSS 가 폭/위치 계산.
        cross = f"left:{lane_pos}px" if is_v else f"top:{lane_pos}px"
        return (
            f'<div class="buff pos-t size-w" '
            f'style="--t:{t_rel_start:.4f};--w:{dur_s:.4f};{cross}">'
            f'<img class="bicon" src="{icon_url}" alt="">'
            f'<span class="blbl">{_html_escape(label)}</span>'
            f'<div class="tip">'
            f'<div class="tname">{_html_escape(title)}</div>'
            f'{subtitle}'
            f'<div class="tbody">{tip_body}</div>'
            f'</div></div>'
        )


def _make_spell_item(spell_id: int, label_text: str, spell_db: dict,
                     icon_fallback: str = "") -> QTableWidgetItem:
    """스펠 셀: 아이콘 + 한글/영문 + 툴팁. spell_db 없으면 icon_fallback 사용."""
    meta = spell_db.get(str(spell_id), {})
    item = QTableWidgetItem(label_text)
    item.setData(Qt.ItemDataRole.UserRole, spell_id)
    icon_file = meta.get("icon") or icon_fallback
    icon = _icon_for(icon_file) if icon_file else None
    if icon:
        item.setIcon(icon)
    if meta:
        item.setToolTip(_build_tooltip(meta))
    elif icon_fallback or label_text:
        item.setToolTip(
            f"<html><body>"
            f"<div style='max-width:320px'>"
            f"<div style='color:#d97757;font-weight:600;font-size:11pt'>{_html_escape(label_text)}</div>"
            f"<div style='color:#6b6359;font-size:9pt;margin-top:4px'>#{spell_id} · spell_db 캐시 없음</div>"
            f"</div></body></html>"
        )
    return item


# ── 아이템 한글 lookup + 툴팁 ──────────────────────────────────────────────

_ITEM_QUALITY_COLOR: dict[str, str] = {
    "POOR":      "#9d9d9d",
    "COMMON":    "#ffffff",
    "UNCOMMON":  "#1eff00",
    "RARE":      "#0070dd",
    "EPIC":      "#a335ee",
    "LEGENDARY": "#ff8000",
    "ARTIFACT":  "#e6cc80",
    "HEIRLOOM":  "#00ccff",
}


def _build_item_tooltip(item_id: int, meta: dict, gear_entry: dict | None = None) -> str:
    """아이템 호버 툴팁 HTML — 한글명 + ilvl + 등급 + (선택) 보너스/장식."""
    name = meta.get("name_ko") or f"#{item_id}"
    ilvl = meta.get("ilvl")
    if gear_entry and isinstance(gear_entry.get("ilvl"), int):
        ilvl = gear_entry["ilvl"]  # 실제 착용 ilvl (업그레이드 반영) 우선
    quality = (meta.get("quality") or "").upper()
    color = _ITEM_QUALITY_COLOR.get(quality, "#f5f0e8")
    bonus_html = ""
    if gear_entry and gear_entry.get("bonus"):
        bonus_ids = gear_entry["bonus"][:6]
        more = "" if len(gear_entry["bonus"]) <= 6 else f" +{len(gear_entry['bonus'])-6}"
        bonus_html = (
            f"<div style='color:#6b6359;font-size:8.5pt;margin-top:4px'>"
            f"bonus: {', '.join(str(b) for b in bonus_ids)}{more}</div>"
        )
    # Qt rich-text auto-detect: starts with '<' → 자동 HTML 모드. <html> wrapper 불필요.
    return (
        f"<p style='color:{color};margin:0;font-size:11pt;font-weight:600'>{_html_escape(name)}</p>"
        f"<p style='color:#a39c8e;margin:4px 0 0 0;font-size:9pt'>"
        f"아이템 레벨 {ilvl if ilvl is not None else '?'} &middot; {quality or '일반'}</p>"
        f"<p style='color:#6b6359;margin:2px 0 0 0;font-size:8pt'>#{item_id}</p>"
        f"{bonus_html}"
    )


def _make_item_item(item_id: int, item_db: dict,
                    gear_entry: dict | None = None) -> QTableWidgetItem:
    """아이템 셀: 아이콘 + 한글명 + 등급 컬러 + 툴팁."""
    meta = item_db.get(str(item_id), {})
    name = meta.get("name_ko") or f"item #{item_id}"
    cell = QTableWidgetItem(name)
    cell.setData(Qt.ItemDataRole.UserRole, item_id)
    quality = (meta.get("quality") or "").upper()
    color = _ITEM_QUALITY_COLOR.get(quality)
    if color:
        cell.setForeground(QColor(color))
    icon_file = meta.get("icon") or ""
    if icon_file:
        ic = _icon_for(icon_file)
        if ic:
            cell.setIcon(ic)
    cell.setToolTip(_build_item_tooltip(item_id, meta, gear_entry))
    return cell


# ─────────────────────────────────────────────────────────────────────────────
# 비주얼 트리 HTML 생성

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

/* === 노드 — 픽률 ramp =================================================== */
.tnode {
    position: absolute; width: 36px; height: 36px;
    border: 2px solid transparent; border-radius: 6px; box-sizing: border-box;
    background: #15110f;
    transition: transform 100ms ease-out;
}
.tnode:hover { transform: scale(1.12); z-index: 9999; }
.tnode img { width: 100%; height: 100%; border-radius: 4px; display: block; }
.tnode.choice { border-radius: 50%; }
.tnode.choice img { border-radius: 50%; }

.tnode.t-essential {
    border-color: #d97757;
    box-shadow: 0 0 10px rgba(217, 119, 87, 0.45);
}
.tnode.t-common { border-color: #d97757; }
.tnode.t-split { border-color: #6b6359; }
.tnode.t-niche { opacity: 0.78; }
.tnode.t-zero { opacity: 0.45; }

/* 픽률 배지 — 우하단, 정수% */
.tnode .pct {
    position: absolute; bottom: -4px; right: -4px;
    background: rgba(10, 8, 6, 0.9); color: #f5f0e8;
    font-size: 9px; font-weight: 600;
    padding: 1px 4px; border-radius: 8px; min-width: 14px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.5);
}
.tnode.t-essential .pct { background: rgba(217, 119, 87, 0.9); }

/* 평균 포인트 배지 — 좌상단, 2-rank 노드 전용 */
.tnode .ptsbadge {
    position: absolute; top: -5px; left: -5px;
    background: rgba(64, 36, 28, 0.95); color: #f5f0e8;
    font-size: 9px; font-weight: 600;
    padding: 1px 4px; border-radius: 7px; min-width: 14px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.5);
    border: 1px solid rgba(217, 119, 87, 0.4);
}

/* 호버 툴팁 — z-index 충분히 높게, 부모 stacking context 위로 */
.tnode .tip {
    display: none; position: absolute; bottom: 48px; left: -8px;
    background: #15110f; border: 1px solid #3a322c; border-radius: 8px;
    padding: 10px 12px; min-width: 280px; max-width: 400px;
    z-index: 99999; box-shadow: 0 8px 24px rgba(0,0,0,0.7);
    color: #f5f0e8; font-size: 11px; pointer-events: none;
    /* 화면 끝에서 잘릴 때 자동 반대편으로 — 가능한 한 */
    max-height: 70vh; overflow-y: auto;
}
/* 컨테이너에서도 tooltip 잘림 막기 */
.tnode .tip table { font-size: 11px; color: #c4bdaf; line-height: 1.4; }
.tnode .tip a { color: #d97757; text-decoration: none; }
.tnode .tip .q0 { color: #9d9d9d; }
.tnode .tip .whtt-name { color: #d97757; font-weight: 600; }
.tnode:hover .tip { display: block; }
.tip .tname { color: #d97757; font-weight: 600; font-size: 12px; margin-bottom: 4px; letter-spacing: -0.01em; }
.tip .tmeta { color: #c8a560; font-size: 10px; margin-bottom: 4px; letter-spacing: 0.01em; }
.tip .tdist { font-size: 10px; margin-bottom: 6px; line-height: 1.4; padding-left: 6px; border-left: 2px solid #3a322c; }
.tip .tdesc { color: #c4bdaf; line-height: 1.5; }

/* 모든 stacking context 에 overflow: visible — tooltip 잘림 방지 */
body { overflow: visible !important; }
.tree-wrap { overflow: visible; padding-top: 24px; }
.tree-canvas { position: relative; overflow: visible; }
.tree-col { overflow: visible; }
.tree-row { overflow: visible; }

.empty {
    color: #a39c8e; text-align: center; padding: 64px 24px;
    background: #221d1a; border: 1px dashed #3a322c; border-radius: 12px; margin: 16px;
}
"""


def _tree_empty_html(msg: str = "보스 + 전문화 선택 시 트리 표시") -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{TREE_CSS}</style></head>"
            f"<body><div class='empty'>{_html_escape(msg)}</div></body></html>")


def _node_html(node: dict, pick_pct: float, pt_breakdown: dict[int, float],
               denom: int, spell_db: dict,
               scale: float = 0.075, ox: float = 0, oy: float = 0) -> str:
    """단일 노드 HTML — 위치 + 아이콘 + 픽률 + 평균포인트 배지 + 호버 툴팁.

    pt_breakdown: {0: pct_0pt, 1: pct_1pt, 2: pct_2pt}
    denom: top100 분모 (보통 100)
    """
    if not node.get("options"):
        return ""
    opt = node["options"][0]
    spell_id = opt.get("spell_id")
    name = opt.get("name") or f"#{node.get('id')}"
    # 한글 이름 + description spell_db 에서 우선 (Wowhead enrich 결과)
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
    # avg pts (수확자들 평균만)
    pick_pts = [k for k in pt_breakdown if k >= 1]
    if pick_pts:
        picked_sum = sum(k * pt_breakdown.get(k, 0) * denom / 100 for k in pick_pts)
        picked_n = sum(pt_breakdown.get(k, 0) * denom / 100 for k in pick_pts)
        avg_pts = picked_sum / picked_n if picked_n > 0 else 1.0
    else:
        avg_pts = 1.0

    # 아이콘 — spell_db
    icon_file = ""
    if spell_id:
        meta = spell_db.get(str(spell_id), {})
        icon_file = meta.get("icon") or ""
    icon_url = (f"https://wow.zamimg.com/images/wow/icons/medium/{icon_file}"
                if icon_file else "")

    # raw_position 기반 — display_col 의 sparse gap 회피
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

    # 툴팁 메타: 0/1/2 pt 분포
    tip_meta_lines = []
    if max_rank > 1:
        tip_meta_lines.append(
            f"<div class='tmeta'>전체 픽률 {int(round(pick_pct))}% · 평균 {avg_pts:.2f}/{max_rank} pts</div>"
        )
        # 0pt / 1pt / 2pt breakdown
        dist_lines = []
        for k in sorted(pt_breakdown.keys()):
            pct_k = pt_breakdown.get(k, 0.0)
            if pct_k < 0.5:
                continue
            label = "0pt (안 찍음)" if k == 0 else f"{k}pt"
            color = "#6b6359" if k == 0 else ("#d97757" if k == max_rank else "#a39c8e")
            dist_lines.append(
                f"<div style='color:{color}'>{label}: {pct_k:.1f}%</div>"
            )
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
        # desc 는 WoWhead HTML (tooltip_ko) 일 수 있어서 raw 로 — 다른 곳도 그렇게 함
        f'<div class="tdesc">{desc[:1200]}</div>'
        f'</div></div>'
    )


def _build_tree_html(tree_data: dict, pick_count: dict, pts_dist: dict,
                     hero_picks: dict[str, int], denom: int,
                     spell_db: dict, hero_filter: str | None = None) -> str:
    """class / spec / hero 트리 HTML.

    pts_dist: {tid: {1: n_1pt, 2: n_2pt}}
    hero_picks: {hero_name: char count}
    denom: total chars (보통 100)
    """
    if not tree_data:
        return _tree_empty_html("이 스펙은 아직 트리 데이터 없음 — fetch_talent_trees.py 실행 필요")

    # 매칭 키: node.id (Blizzard) == WCL nodeID. options.talent_id 는 다른 ID 체계라 못 씀.
    def pct_of(node) -> float:
        nid = node.get("id")
        if nid is None:
            return 0
        return pick_count.get(int(nid), 0) / max(1, denom) * 100

    def breakdown_of(node) -> dict[int, float]:
        """{0: pct_0pt, 1: pct_1pt, 2: pct_2pt}  (in %)."""
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

    # raw_position 기반 컴팩트 레이아웃 — display_col 의 sparse gap 회피
    TREE_SCALE = 0.075  # raw 9000 → 675px 정도
    def tree_bounds(nodes):
        if not nodes:
            return (400, 400, 0, 0)
        xs = [(n.get("x") or 0) for n in nodes]
        ys = [(n.get("y") or 0) for n in nodes]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # padding 40px + 아이콘 폭 36px
        w = int((max_x - min_x) * TREE_SCALE) + 80
        h = int((max_y - min_y) * TREE_SCALE) + 80
        return (w, h, min_x, min_y)

    class_nodes = tree_data.get("class") or []
    spec_nodes = tree_data.get("spec") or []
    cw, ch, cmx, cmy = tree_bounds(class_nodes)
    sw, sh, smx, smy = tree_bounds(spec_nodes)

    class_html = "".join(_node_html(n, pct_of(n), breakdown_of(n), denom, spell_db,
                                     scale=TREE_SCALE, ox=cmx, oy=cmy)
                         for n in class_nodes)
    spec_html = "".join(_node_html(n, pct_of(n), breakdown_of(n), denom, spell_db,
                                    scale=TREE_SCALE, ox=smx, oy=smy)
                        for n in spec_nodes)

    # 영웅 트리: 가장 많이 뽑힌 거 (hero_picks 기준)
    hero_dict = tree_data.get("hero") or {}
    hero_html = ""
    hero_w, hero_h = 240, 600
    hero_header_html = "영웅 특성 — (없음)"
    if hero_dict:
        if hero_picks and sum(hero_picks.values()) > 0:
            ranked = sorted(hero_picks.items(), key=lambda x: -x[1])
        else:
            ranked = [(hn, 0) for hn in hero_dict]
        chosen_name = hero_filter if (hero_filter and hero_filter in hero_dict) else ranked[0][0]
        hero_nodes = hero_dict[chosen_name].get("nodes") or []
        hw, hh, hmx, hmy = tree_bounds(hero_nodes)
        hero_w, hero_h = hw, hh
        hero_html = "".join(_node_html(n, pct_of(n), breakdown_of(n), denom, spell_db,
                                        scale=TREE_SCALE, ox=hmx, oy=hmy)
                            for n in hero_nodes)
        # 헤더에 모든 영웅트리 선택률 표시
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
    </div>
    """
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{TREE_CSS}</style></head>"
            f"<body>{body}</body></html>")


def _load_tree_lut() -> dict[tuple[str, str, int], str]:
    """talent_tree_classification.csv → {(class, spec, talent_id): tree_label}."""
    key = "tree_lut"
    if key in _data:
        return _data[key]  # type: ignore
    if not DATA_DIR:
        _data[key] = {}
        return {}
    p = DATA_DIR / "talent_tree_classification.csv"
    if not p.exists():
        log.warning("missing %s", p.name)
        _data[key] = {}
        return {}
    import pandas as pd
    try:
        df = pd.read_csv(p)
        lut = {(r["class"], r["spec"], int(r["talent_id"])): r["tree"]
               for _, r in df.iterrows()}
        _data[key] = lut
        log.info("loaded tree lut: %d entries", len(lut))
        return lut
    except Exception:
        log.exception("tree lut load failed")
        _data[key] = {}
        return {}


def _resolve_name(spell_id: int, spell_db: dict) -> tuple[str, str]:
    """(라벨, 보조라벨) — 한글 있으면 한글 / 영문, 영문만 있으면 영문, 둘 다 없으면 '미상 #ID'."""
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


# ── 캐릭터 빌드 패널 헬퍼들 ──────────────────────────────────────────────────

SLOT_KR: dict[int, str] = {
    0: "머리",     1: "목",       2: "어깨",
    4: "가슴",     5: "허리",     6: "다리",     7: "발",
    8: "손목",     9: "손",
    10: "반지 1",  11: "반지 2",
    12: "장신구 1", 13: "장신구 2",
    14: "망토",
    15: "주무기",  16: "보조무기",
    17: "원거리",
}

STAT_KR: dict[str, str] = {
    "Item Level": "장비레벨",
    "Stamina":    "체력",
    "Strength":   "힘",
    "Agility":    "민첩성",
    "Intellect":  "지능",
    "Crit":       "극대화",
    "Haste":      "가속",
    "Mastery":    "특화",
    "Versatility": "유연",
    "Leech":      "흡혈",
    "Avoidance":  "회피",
    "Speed":      "이동속도",
}

# Midnight 11.x 레벨 80 기준 rating → % 변환 (pre-DR, 추정치)
# 출처: WoW 커뮤니티 데이터마이닝 — 정확한 값은 패치별로 변하고 DR 적용 시 더 줄어듦
RATING_PER_PCT: dict[str, float] = {
    "Crit":        35.0,
    "Haste":       33.0,
    "Mastery":     35.0,    # 실제는 spec multiplier 적용 (예: BM Hunter ×1.4)
    "Versatility": 40.0,
    "Leech":       25.0,
    "Avoidance":   20.0,
    "Speed":       30.0,
}


_HTML_TAG_RE = __import__("re").compile(r"<[^>]+>")
_HTML_WHITESPACE_RE = __import__("re").compile(r"\s+")


def _strip_html(s: str) -> str:
    """HTML 태그 다 제거 + 공백 정리. Wowhead tooltip 평문화."""
    if not s:
        return ""
    plain = _HTML_TAG_RE.sub(" ", s)
    return _HTML_WHITESPACE_RE.sub(" ", plain).strip()


# 사전 버프 카테고리 필터 — 음식/영약/오일/숫돌/증강 만 통과
CONSUMABLE_KEYWORDS = (
    # 음식 (food)
    "잘 먹음", "음식", "Well Fed", "Food",
    # 영약 (flask)
    "영약", "Flask", "Phial",
    # 오일 (weapon enchant — oil)
    "기름", "오일", "Oil",
    # 숫돌 (weapon enchant — stone)
    "숫돌", "Whetstone", "Sharpening", "Stone",
    # 증강 (augment rune)
    "증강", "Augment", "마법 룬", "마법룬", "고대의 룬", "Rune",
)


def _is_consumable_name(name_ko: str, name_en: str = "") -> bool:
    """이름에 소비템 키워드 포함되면 True (대소문자 무시)."""
    blob = (name_ko or "") + " " + (name_en or "")
    blob_lower = blob.lower()
    return any(kw.lower() in blob_lower for kw in CONSUMABLE_KEYWORDS)


def _resolve_buff(sp: int, spell_db: dict, buff_db: dict) -> tuple[str, str, str]:
    """(name, icon_file, description) — spell_db 우선, 없으면 buff_db_en. HTML strip."""
    primary, _sub = _resolve_name(sp, spell_db)
    sd_entry = spell_db.get(str(sp), {}) or {}
    icon = sd_entry.get("icon") or ""
    raw_desc = (sd_entry.get("description_ko") or sd_entry.get("tooltip_ko") or "").strip()
    desc = _strip_html(raw_desc)  # Wowhead tooltip HTML 평문화
    if primary.startswith("미상 #"):
        meta = buff_db.get(str(sp)) or buff_db.get(sp)
        if isinstance(meta, dict):
            primary = meta.get("name") or primary
            icon = icon or meta.get("icon") or ""
    return primary, icon, desc


def _pre_fight_buffs(rid: str, fid: int, sid: int | None, spell_db: dict) -> list[dict]:
    """전투 시작 후 0~5초 사이 활성 (apply*) buff 들.

    참고: 진짜 음식/영약/오일/숫돌은 pre-pull (fight.startTime 이전) 에 걸려있어서
    V2 events 쿼리 (startTime=fight.startTime) 결과엔 안 들어옴. 여기 잡히는 건
    fight 시작 직후 in-combat 버프 (사냥꾼 Barbed Shot, 힐러 Atonement 등).
    소비템 전용 쿼리는 별도 작업 필요 (TODO).
    """
    v2 = _v2_data()
    if v2 is None or sid is None:
        return []
    ev = v2.events.get(f"{rid}:{fid}:{sid}")
    if not isinstance(ev, dict):
        return []
    window = db_fight_window(rid, fid)
    if not window:
        return []
    start_ms = window[0]
    pre_max = start_ms + 5000
    buff_db = _load_json("buff_db_en.json")
    seen: set[int] = set()
    out: list[dict] = []
    for e in ev.get("buffs") or []:
        if not isinstance(e, list) or len(e) < 3:
            continue
        try:
            ts = int(e[0]); sp = int(e[1])
        except (TypeError, ValueError):
            continue
        tp = e[2] if isinstance(e[2], str) else ""
        if not tp.startswith("apply"):
            continue
        if not (start_ms <= ts <= pre_max):
            continue
        if sp in seen:
            continue
        seen.add(sp)
        name, icon, desc = _resolve_buff(sp, spell_db, buff_db)
        out.append({"spell_id": sp, "name": name, "icon": icon, "description": desc})
    return out


def _enrich_buff_list(spell_ids: list[int], spell_db: dict) -> list[dict]:
    """[spell_id, ...] (또는 [{spell_id: ...}]) → [{spell_id, name, icon, description}]."""
    buff_db = _load_json("buff_db_en.json")
    out: list[dict] = []
    seen: set[int] = set()
    for entry in spell_ids:
        sp = entry["spell_id"] if isinstance(entry, dict) else entry
        if not isinstance(sp, int) or sp in seen:
            continue
        seen.add(sp)
        name, icon, desc = _resolve_buff(sp, spell_db, buff_db)
        out.append({"spell_id": sp, "name": name, "icon": icon, "description": desc})
    return out


def _build_info_empty_html(msg: str = "랭킹 행 클릭 시 빌드 표시") -> str:
    return (
        f"<html><body style='background:#1a1614;color:#a39c8e;"
        f"font-family:Pretendard Variable,Segoe UI,sans-serif;font-size:10pt;"
        f"padding:32px;text-align:center'>"
        f"<p>{_html_escape(msg)}</p></body></html>"
    )


def _build_info_html(char: str, pre_pull_buffs: list[dict], in_combat_buffs: list[dict],
                     stats: dict | None, gear: list[dict],
                     prepull_loading: bool = False) -> str:
    """오른쪽 패널 HTML — 캐릭터명 + 사전 버프 + 전투 시작 버프 + 총 스탯."""
    style = (
        "background:#1a1614;color:#f5f0e8;font-family:'Pretendard Variable',"
        "'Segoe UI',sans-serif;font-size:9.5pt;padding:12px 16px;line-height:1.55"
    )

    # 1. 캐릭터 헤더
    avg_ilvl = ""
    if stats and isinstance(stats.get("Item Level"), int):
        avg_ilvl = f"<span style='color:#c8a560'>· ilvl {stats['Item Level']}</span>"
    elif gear:
        ilvls = [g.get("ilvl") for g in gear if isinstance(g.get("ilvl"), int)]
        if ilvls:
            avg = sum(ilvls) / len(ilvls)
            avg_ilvl = f"<span style='color:#a39c8e'>· 평균 ilvl {avg:.1f}</span>"

    parts = [
        f"<div style='font-size:11pt;font-weight:600;color:#d97757;"
        f"margin-bottom:8px'>{_html_escape(char)} {avg_ilvl}</div>"
    ]

    def _buff_block(b: dict) -> str:
        icon_html = ""
        if b.get("icon"):
            icon_html = (
                f"<img src='https://wow.zamimg.com/images/wow/icons/medium/{b['icon']}' "
                f"style='width:24px;height:24px;border-radius:4px;vertical-align:middle;margin-right:6px'>"
            )
        desc = (b.get("description") or "").strip()
        desc_short = desc[:120] + "…" if len(desc) > 120 else desc
        html = (
            f"<div style='margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #2c2521'>"
            f"<div>{icon_html}"
            f"<span style='color:#f5f0e8;font-weight:600'>{_html_escape(b['name'])}</span>"
            f" <span style='color:#6b6359;font-size:8.5pt'>#{b['spell_id']}</span></div>"
        )
        if desc_short:
            html += (
                f"<div style='color:#a39c8e;font-size:9pt;margin-top:2px;padding-left:30px'>"
                f"{_html_escape(desc_short)}</div>"
            )
        html += "</div>"
        return html

    # 2. 사전 버프 — 음식/영약/오일/숫돌/증강만 필터링
    consumables = [b for b in (pre_pull_buffs or []) if _is_consumable_name(b.get("name", ""))]
    total_prepull = len(pre_pull_buffs or [])
    filter_note = ""
    if total_prepull > 0:
        filter_note = (
            f" <span style='color:#6b6359;font-weight:400;font-size:8.5pt;text-transform:none;"
            f"letter-spacing:0'>· 표시 {len(consumables)} / 전체 {total_prepull} (소비템 카테고리만)</span>"
        )
    parts.append(
        "<div style='color:#c8a560;font-size:9pt;font-weight:600;"
        "letter-spacing:0.04em;text-transform:uppercase;"
        f"margin-top:10px;margin-bottom:6px'>사전 버프 (음식·영약·오일·숫돌·증강){filter_note}</div>"
    )
    if prepull_loading:
        parts.append(
            "<div style='color:#a39c8e;font-style:italic'>pre-pull 버프 가져오는 중… (수초)</div>"
        )
    elif consumables:
        for b in consumables:
            parts.append(_buff_block(b))
    elif total_prepull > 0:
        parts.append(
            f"<div style='color:#6b6359'>이 캐릭은 소비템 사용 흔적 없음 "
            f"(pre-pull buff {total_prepull}개 중 음식/영약/오일/숫돌/증강 0개)</div>"
        )
    else:
        parts.append(
            "<div style='color:#6b6359'>(pre-pull 캐시 없음 또는 데이터 미수신)</div>"
        )

    # 3. 전투 시작 시 활성 (in-combat)
    parts.append(
        "<div style='color:#c8a560;font-size:9pt;font-weight:600;"
        "letter-spacing:0.04em;text-transform:uppercase;"
        "margin-top:14px;margin-bottom:6px'>전투 시작 시 활성 (in-combat, 첫 5초)</div>"
    )
    if in_combat_buffs:
        for b in in_combat_buffs:
            parts.append(_buff_block(b))
    else:
        parts.append(
            "<div style='color:#6b6359'>(events 캐시 없음 — primary 5스펙만 backfill)</div>"
        )

    # 3. 총 스탯
    parts.append(
        "<div style='color:#c8a560;font-size:9pt;font-weight:600;"
        "letter-spacing:0.04em;text-transform:uppercase;"
        "margin-top:14px;margin-bottom:6px'>총 스탯 (rating · %추정)</div>"
    )
    if stats:
        parts.append("<table style='border-collapse:collapse'>")
        prio = ["Item Level", "Stamina", "Strength", "Agility", "Intellect",
                "Crit", "Haste", "Mastery", "Versatility",
                "Leech", "Avoidance", "Speed"]
        for k in prio:
            if k not in stats:
                continue
            v = stats[k]
            if not isinstance(v, int):
                continue
            kr = STAT_KR.get(k, k)
            extra = ""
            if k in RATING_PER_PCT and v > 0:
                pct = v / RATING_PER_PCT[k]
                note = ""
                if k == "Mastery":
                    note = " <span style='color:#6b6359;font-size:8.5pt'>×spec배율</span>"
                extra = (
                    f" <span style='color:#a39c8e'>→ +{pct:.1f}%</span>{note}"
                )
            parts.append(
                f"<tr><td style='color:#a39c8e;padding:2px 12px 2px 0'>{kr}</td>"
                f"<td style='text-align:right;padding:2px 0;color:#f5f0e8'>{v:,}</td>"
                f"<td style='padding:2px 0 2px 4px'>{extra}</td></tr>"
            )
        parts.append("</table>")
        parts.append(
            "<div style='color:#6b6359;font-size:8.5pt;margin-top:6px;line-height:1.4'>"
            "※ % 는 rating 기여 추정치 (Midnight 11.x 기준 1%=35-40 rating, pre-DR).<br>"
            "실제 게임 표시값은 ① 기본 스탯 (1차 → 2차 자동 변환) ② DR 적용으로 차이 있음.<br>"
            "Mastery 는 spec 마다 effect 배율 다름 (예: 악마 ×1.8, 야수 ×1.4)."
            "</div>"
        )
    else:
        parts.append(
            "<div style='color:#6b6359'>(stats 없음 — wcl_v2_data 업데이트 후 "
            "새 backfill 분부터 수집됨)</div>"
        )

    body = "".join(parts)
    return f"<html><body style='{style}'>{body}</body></html>"


# ─────────────────────────────────────────────────────────────────────────────
# 로딩 오버레이 — 무거운 click 작업 동안 위에 띄움

class FullCharFetchThread(QThread):
    """캐시에 없는 (rid, fid, char) 의 pfight + events + prepull 일괄 V2 페치.

    임의 로그 분석 모드에서 backfill 없는 캐릭 클릭 시 사용.
    완료 시 _on_ranking_row_changed 재호출로 정상 렌더 흐름 트리거.
    """

    finished_ok = Signal(dict)  # {rid, fid, char, ok}

    def __init__(self, rid: str, fid: int, char: str, v2, parent=None) -> None:
        super().__init__(parent)
        self.rid = rid
        self.fid = fid
        self.char = char
        self.v2 = v2

    def run(self) -> None:
        if self.v2 is None:
            self.finished_ok.emit({
                "rid": self.rid, "fid": self.fid, "char": self.char, "ok": False,
            })
            return
        try:
            self.v2.player_fight(self.rid, self.fid, self.char)
            self.v2.events_for(self.rid, self.fid, self.char)
            self.v2.pre_pull_buffs(self.rid, self.fid, self.char)
        except Exception:
            log.exception("FullCharFetchThread fetch fail")
        try:
            self.v2.flush()
        except Exception:
            pass
        self.finished_ok.emit({
            "rid": self.rid, "fid": self.fid, "char": self.char, "ok": True,
        })


class StatsFetchThread(QThread):
    """캐시된 pfight 에 stats 가 없을 때 (옛날 fetch) 강제 refetch.

    cache 의 (rid:fid:char) 키 무효화 후 player_fight() 호출 → 새 데이터에 stats 포함.
    """

    finished_ok = Signal(dict)  # {rid, fid, char, pf}

    def __init__(self, rid: str, fid: int, char: str, v2, parent=None) -> None:
        super().__init__(parent)
        self.rid = rid
        self.fid = fid
        self.char = char
        self.v2 = v2

    def run(self) -> None:
        if self.v2 is None:
            self.finished_ok.emit({"rid": self.rid, "fid": self.fid, "char": self.char, "pf": None})
            return
        try:
            key = f"{self.rid}:{self.fid}:{self.char}"
            self.v2.pfight.pop(key, None)  # 무효화 → player_fight 가 새로 fetch
            pf = self.v2.player_fight(self.rid, self.fid, self.char)
            self.v2.flush()
        except Exception:
            log.exception("StatsFetchThread fail")
            pf = None
        self.finished_ok.emit({
            "rid": self.rid, "fid": self.fid, "char": self.char, "pf": pf,
        })


class PrepullFetchThread(QThread):
    """단일 캐릭터의 pre-pull buff (음식/영약/오일/숫돌 등) on-demand 페치.

    V2 events 쿼리에 startTime = fight.start - 600s 줘서 사전 발동된 buff 들도 잡음.
    main thread V2Data 싱글톤 공유 — prepull dict in-place 업데이트.
    """

    finished_ok = Signal(dict)  # {"rid": ..., "fid": ..., "char": ..., "buffs": [...]}

    def __init__(self, rid: str, fid: int, char: str, v2, parent=None) -> None:
        super().__init__(parent)
        self.rid = rid
        self.fid = fid
        self.char = char
        self.v2 = v2

    def run(self) -> None:
        if self.v2 is None:
            self.finished_ok.emit({"rid": self.rid, "fid": self.fid, "char": self.char,
                                    "buffs": None})
            return
        try:
            buffs = self.v2.pre_pull_buffs(self.rid, self.fid, self.char)
        except Exception:
            log.exception("PrepullFetchThread fetch fail")
            buffs = None
        try:
            self.v2.flush()
        except Exception:
            log.exception("V2Data flush after prepull fetch fail")
        self.finished_ok.emit({
            "rid": self.rid, "fid": self.fid, "char": self.char, "buffs": buffs,
        })


class DamageFetchThread(QThread):
    """백그라운드에서 V2 damage_table 을 ThreadPoolExecutor(4) 로 병렬 페치.

    main thread 의 V2Data 싱글톤을 공유 — dict 업데이트가 in-place 라
    main thread 가 즉시 새 데이터 보임. GIL 덕에 dict 쓰기 원자적 (worst case
    동일 키 중복 페치 ~1).
    """

    finished_ok = Signal(object)  # emits V2Data | None

    def __init__(self, need_fetch: list[tuple[str, int, str]], v2, parent=None) -> None:
        super().__init__(parent)
        self.need_fetch = need_fetch
        self.v2 = v2  # shared V2Data 인스턴스

    def run(self) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        if self.v2 is None:
            self.finished_ok.emit(None)
            return

        try:
            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = [
                    ex.submit(self.v2.damage_table, rid, fid, char)
                    for rid, fid, char in self.need_fetch
                ]
                for fut in as_completed(futures):
                    try:
                        fut.result()
                    except Exception as e:
                        log.warning("damage_table worker err: %s", e)
        except Exception:
            log.exception("DamageFetchThread executor fail")

        try:
            self.v2.flush()
        except Exception:
            log.exception("V2Data flush fail")
        self.finished_ok.emit(self.v2)


class LoadingOverlay(QWidget):
    """반투명 박스 + 텍스트. 부모 위젯을 가득 채우고 raise_() 로 위에."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)
        self.label = QLabel("로딩 중…", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(
            "QLabel { color:#d97757; font-size:13pt; font-weight:600; "
            "background-color: rgba(30,31,36,210); "
            "border: 1px solid #4a4039; border-radius: 8px; padding: 24px 32px; }"
        )
        self.label.adjustSize()
        self.hide()

    def resizeEvent(self, event) -> None:
        if self.parent():
            self.setGeometry(self.parentWidget().rect())
        self.label.move(
            (self.width() - self.label.width()) // 2,
            (self.height() - self.label.height()) // 2,
        )
        super().resizeEvent(event)

    def show_with(self, text: str = "로딩 중…") -> None:
        self.label.setText(text)
        self.label.adjustSize()
        if self.parent():
            self.setGeometry(self.parentWidget().rect())
        self.label.move(
            (self.width() - self.label.width()) // 2,
            (self.height() - self.label.height()) // 2,
        )
        self.show()
        self.raise_()
        QApplication.processEvents()


def _center_cell(text) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
    return it


class RankingPanel(QWidget):
    """4분할: 랭킹 ▏자주 쓰는 시전 ▏특성 ▏딜사이클 (랭킹 행 클릭 시)."""

    def __init__(self, parent=None, csv_filename: str = "rankings_with_talents.csv") -> None:
        super().__init__(parent)
        self.encounter_id: int | None = None
        self.encounter_name: str | None = None
        self.class_en: str | None = None
        self.spec_en: str | None = None
        self._csv_filename = csv_filename
        self._current_df = None
        self._damage_thread: DamageFetchThread | None = None
        self._damage_request_token: int = 0
        self._prepull_thread: PrepullFetchThread | None = None
        self._prepull_request_token: int = 0
        self._stats_thread: StatsFetchThread | None = None
        self._stats_request_token: int = 0
        self._full_char_thread: FullCharFetchThread | None = None
        self._full_char_request_token: int = 0
        self._last_build_render: dict | None = None  # {rid, fid, char, gear, in_combat, stats}
        # 비교 분석 탭에서 등록하는 hook (build 렌더 끝나면 자기 자신 전달)
        self._on_build_rendered_hook = None  # callable(panel) | None
        self._build()

    # ── UI 빌드 ──────────────────────────────────────────────────────────
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)

        self.header = QLabel("← 보스와 전문화를 골라봐")
        self.header.setObjectName("pageHeader")
        outer.addWidget(self.header)

        # 메인: 위(랭킹+시전) ↑↓ 아래(탭: 특성 / 딜사이클)
        main_split = QSplitter(Qt.Orientation.Vertical)
        outer.addWidget(main_split, 1)

        # ── 위: 랭킹 ▏자주 쓰는 시전
        top_split = QSplitter(Qt.Orientation.Horizontal)

        self.ranking_table = QTableWidget()
        self.ranking_table.setColumnCount(5)
        self.ranking_table.setHorizontalHeaderLabels(["#", "캐릭터", "서버", "DPS", "ilvl"])
        self.ranking_table.verticalHeader().setVisible(False)
        self.ranking_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ranking_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ranking_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ranking_table.setAlternatingRowColors(True)
        rh = self.ranking_table.horizontalHeader()
        rh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        rh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        rh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        rh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        rh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.ranking_table.itemSelectionChanged.connect(self._on_ranking_row_changed)
        # 우클릭 → 비교 분석 좌/우 추가
        self.ranking_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ranking_table.customContextMenuRequested.connect(self._on_ranking_context_menu)
        top_split.addWidget(vbox_panel("랭킹 (top 100)", self.ranking_table))
        # 랭킹 셀이 짧지 않게 — 다음 spell_table 보다 3배 넓게

        self.spell_table = QTableWidget()
        self.spell_table.setColumnCount(3)
        self.spell_table.setHorizontalHeaderLabels(["스킬", "딜 비중", "합산 데미지"])
        self.spell_table.verticalHeader().setVisible(False)
        self.spell_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.spell_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.spell_table.setAlternatingRowColors(True)
        self.spell_table.setIconSize(QSize(24, 24))
        sh = self.spell_table.horizontalHeader()
        sh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        sh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        sh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        top_split.addWidget(vbox_panel("딜 비중 TOP10 (top 20 합산)", self.spell_table))

        top_split.setStretchFactor(0, 3)
        top_split.setStretchFactor(1, 1)
        main_split.addWidget(top_split)

        # ── 아래: 탭 (특성 / 딜사이클)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setDocumentMode(True)

        # 탭 1: 특성 + 빌드 (상: 트리, 하 좌: 장비, 하 우: 버프+스탯)
        # 비주얼 트리 (QWebEngineView) — top100 픽률 + 평균 포인트 오버레이
        self.tree_view = QWebEngineView()
        self.tree_view.setMinimumHeight(360)
        self.tree_view.setHtml(_tree_empty_html())

        # 장비 테이블 (선택한 캐릭터의 17개 슬롯)
        self.gear_table = QTableWidget()
        self.gear_table.setColumnCount(5)
        self.gear_table.setHorizontalHeaderLabels(["슬롯", "아이템", "ilvl", "마부", "보석"])
        self.gear_table.verticalHeader().setVisible(False)
        self.gear_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.gear_table.setAlternatingRowColors(True)
        self.gear_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        gh = self.gear_table.horizontalHeader()
        gh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        gh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        gh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        gh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        gh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        # 버프 + 스탯 (HTML rich text)
        self.build_info = QTextBrowser()
        self.build_info.setOpenExternalLinks(True)
        self.build_info.setHtml(_build_info_empty_html())

        talent_wrap = QWidget()
        tw_v = QVBoxLayout(talent_wrap)
        tw_v.setContentsMargins(0, 0, 0, 0)
        tw_v.setSpacing(6)
        sp = QSplitter(Qt.Orientation.Vertical)
        sp.addWidget(vbox_panel("특성 트리 (top100 픽률 + 평균 포인트)", self.tree_view))
        side_sp = QSplitter(Qt.Orientation.Horizontal)
        side_sp.addWidget(vbox_panel("장비 (랭킹 행 클릭)", self.gear_table))
        side_sp.addWidget(vbox_panel("버프 (전투 시작 시) + 스탯", self.build_info))
        side_sp.setStretchFactor(0, 3)
        side_sp.setStretchFactor(1, 2)
        sp.addWidget(side_sp)
        sp.setStretchFactor(0, 3)
        sp.setStretchFactor(1, 2)
        tw_v.addWidget(sp, 1)
        self.detail_tabs.addTab(talent_wrap, "특성 + 빌드")

        # 탭 2: 딜사이클 (header 행 + timeline)
        timeline_wrap = QWidget()
        tw_layout = QVBoxLayout(timeline_wrap)
        tw_layout.setContentsMargins(0, 0, 0, 0)
        tw_layout.setSpacing(6)
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.addWidget(section_label("딜사이클 (랭킹 행 클릭)"))
        head_row.addStretch()
        self.orient_btn = QPushButton("세로 모드")
        self.orient_btn.setCheckable(True)
        self.orient_btn.setFixedHeight(26)
        self.orient_btn.toggled.connect(self._on_orient_toggled)
        head_row.addWidget(self.orient_btn)
        tw_layout.addLayout(head_row)
        self.rotation_timeline = RotationTimeline()
        self._timeline_layout = tw_layout  # detach 용 참조
        self._timeline_tab_widget = timeline_wrap  # 비교 모드에서 hide
        tw_layout.addWidget(self.rotation_timeline, 1)
        self.detail_tabs.addTab(timeline_wrap, "딜사이클")

        main_split.addWidget(self.detail_tabs)
        main_split.setStretchFactor(0, 1)
        main_split.setStretchFactor(1, 2)  # 탭 영역 더 크게

        self._orientation = "h"
        self._last_rotation_args: dict | None = None

        # 로딩 오버레이 — 전체 패널 위에
        self.loader = LoadingOverlay(self)

    def detach_rotation_timeline(self) -> "RotationTimeline":
        """비교 모드 — rotation_timeline 위젯을 패널 밖으로 빼서 반환.

        - tw_layout 에서 제거 + 딜사이클 탭 자체를 숨김
        - render_fight 호출은 그대로 동작 (위젯 참조 유지)
        - 호출자가 새 부모에 addWidget 해야 함
        """
        self._timeline_layout.removeWidget(self.rotation_timeline)
        idx = self.detail_tabs.indexOf(self._timeline_tab_widget)
        if idx >= 0:
            self.detail_tabs.removeTab(idx)
        return self.rotation_timeline

    # ── 필터 변경 ─────────────────────────────────────────────────────────
    def set_filter(self, encounter_id, encounter_name, class_en, spec_en) -> None:
        self.encounter_id = encounter_id
        self.encounter_name = encounter_name
        self.class_en = class_en
        self.spec_en = spec_en
        self._refresh()

    def _refresh(self) -> None:
        self.rotation_timeline.set_empty("랭킹에서 캐릭터 클릭")
        self.gear_table.setRowCount(0)
        self.build_info.setHtml(_build_info_empty_html())
        if not all([self.encounter_id, self.class_en, self.spec_en]):
            self.header.setText("← 보스와 전문화를 골라봐")
            self.ranking_table.setRowCount(0)
            self.spell_table.setRowCount(0)
            self._current_df = None
            return

        self.loader.show_with("랭킹 / 시전 / 특성 불러오는 중…")
        try:
            rankings = _load_csv(self._csv_filename)
            if rankings is None:
                self.header.setText(f"data/{self._csv_filename} 를 못 찾음")
                return

            df = rankings[
                (rankings["encounter_id"] == self.encounter_id)
                & (rankings["class"] == self.class_en)
                & (rankings["spec"] == self.spec_en)
            ].sort_values("rank").reset_index(drop=True)
            self._current_df = df

            cls_kr = CLASS_KR.get(self.class_en, self.class_en)
            spec_kr = SPEC_KR.get(self.spec_en, self.spec_en)
            self.header.setText(f"{self.encounter_name}   ·   {cls_kr} {spec_kr}   (n={len(df)})")

            self._populate_rankings(df)
            self._populate_top_damage(df)
            self._populate_talents(df)
        finally:
            self.loader.hide()

    # ── 랭킹 ──────────────────────────────────────────────────────────────
    def _populate_rankings(self, df) -> None:
        cls_color = CLASS_COLOR.get(self.class_en or "", "#f5f0e8")
        self.ranking_table.setRowCount(len(df))
        for i, row in enumerate(df.itertuples(index=False)):
            # # 컬럼: 클래스 컬러 좌측 룰 글리프 + 순위 (텍스트는 cream)
            rank = int(getattr(row, "rank", i + 1))
            rank_item = QTableWidgetItem(f"▍ {rank}")
            rank_item.setForeground(QColor(cls_color))
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.ranking_table.setItem(i, 0, rank_item)

            # 이름: cream 통일 (가독성)
            name_item = QTableWidgetItem(str(getattr(row, "character", "")))
            font = name_item.font()
            font.setWeight(QFont.Weight.DemiBold)
            name_item.setFont(font)
            self.ranking_table.setItem(i, 1, name_item)

            self.ranking_table.setItem(i, 2, _center_cell(getattr(row, "server", "")))
            try:
                dps_str = f"{int(round(float(getattr(row, 'dps', 0)))):,}"
            except (TypeError, ValueError):
                dps_str = str(getattr(row, "dps", ""))
            dps_item = _center_cell(dps_str)
            dps_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.ranking_table.setItem(i, 3, dps_item)
            ilvl_item = _center_cell(getattr(row, "item_level", ""))
            ilvl_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.ranking_table.setItem(i, 4, ilvl_item)

    # ── 딜 비중 TOP10 (top 20 합산, SQLite + V2 비동기 lazy fetch) ────────
    def _populate_top_damage(self, ranking_df) -> None:
        spell_db = _load_json("spell_db.json")
        sample = ranking_df.head(20)

        # source_id 조회 + 누락 damage 페치 목록
        need_fetch: list[tuple[str, int, str]] = []
        triples: list[tuple[str, int, int]] = []  # SQLite 에 있는 (rid, fid, sid)
        for _, row in sample.iterrows():
            rid = str(row["report_id"])
            try:
                fid = int(row["fight_id"])
            except (TypeError, ValueError):
                continue
            char = str(row["character"])
            sid = db_source_id(rid, char)
            if sid is None:
                # sourceID 아직 없음 — 페치하면 v2_cache 에 들어감
                need_fetch.append((rid, fid, char))
                continue
            triples.append((rid, fid, sid))
            if not db_damage(rid, fid, sid):
                need_fetch.append((rid, fid, char))

        # 1) SQLite 에 있는 만큼 일단 즉시 렌더 (없으면 placeholder)
        self._render_top_damage(triples, spell_db, pending=len(need_fetch))

        # 2) 빠진 게 있으면 백그라운드 페치 — UI 안 막음
        if not need_fetch:
            return

        # request token: 사용자가 보스/스펙 바꾼 뒤 stale 응답 무시용
        self._damage_request_token += 1
        token = self._damage_request_token
        sample_snapshot = sample
        sdb = spell_db

        def _on_done(v2):
            # 이미 사용자가 다른 필터로 이동했으면 무시
            if token != self._damage_request_token:
                return
            if v2 is None:
                return
            # v2 는 main thread V2Data 와 같은 인스턴스 — dict 이미 in-place 업데이트됨
            # 페치 후 triples 재계산 (sourceID 새로 생긴 행 포함)
            new_triples: list[tuple[str, int, int]] = []
            for _, r in sample_snapshot.iterrows():
                rid_ = str(r["report_id"])
                try:
                    fid_ = int(r["fight_id"])
                except (TypeError, ValueError):
                    continue
                char_ = str(r["character"])
                sid_ = db_source_id(rid_, char_)
                if sid_ is not None:
                    new_triples.append((rid_, fid_, sid_))
            self._render_top_damage(new_triples, sdb, pending=0)

        thread = DamageFetchThread(need_fetch, _v2_data(), self)
        thread.finished_ok.connect(_on_done)
        thread.finished.connect(thread.deleteLater)
        self._damage_thread = thread  # GC 방지
        thread.start()

    def _render_top_damage(self, triples, spell_db, pending: int = 0) -> None:
        """SQLite 의 (rid, fid, sid) 들로 스펠별 합산 → spell_table 갱신."""
        agg: dict[int, dict] = {}
        matched = 0
        for rid, fid, sid in triples:
            entries = db_damage(rid, fid, sid)
            if not entries:
                continue
            matched += 1
            for e in entries:
                gid = e.get("guid")
                if not isinstance(gid, int) or gid <= 0:
                    continue
                t = e.get("total") or 0
                a = agg.setdefault(gid, {"total": 0, "name_en": e.get("name") or "", "icon": e.get("icon") or ""})
                a["total"] += t

        total_all = sum(v["total"] for v in agg.values()) or 1
        rows = sorted(agg.items(), key=lambda x: -x[1]["total"])[:10]

        # 데이터 0건이고 페치 진행 중이면 placeholder 한 줄
        if not rows and pending > 0:
            self.spell_table.setRowCount(1)
            ph = QTableWidgetItem(f"딜 비중 데이터 받는 중… ({pending}개)")
            ph.setForeground(QColor("#a39c8e"))
            self.spell_table.setItem(0, 0, ph)
            self.spell_table.setItem(0, 1, _center_cell(""))
            self.spell_table.setItem(0, 2, _center_cell(""))
            return

        self.spell_table.setRowCount(len(rows))
        for i, (gid, info) in enumerate(rows):
            primary, sub = _resolve_name(gid, spell_db)
            if primary == f"미상 #{gid}" and info.get("name_en"):
                primary = info["name_en"]
            label = f"{primary}    ({sub})" if sub else primary
            # V2 damage 가 icon filename 도 주니까 spell_db 미스 시 fallback
            self.spell_table.setItem(
                i, 0, _make_spell_item(gid, label, spell_db, icon_fallback=info.get("icon") or "")
            )
            pct = info["total"] / total_all * 100
            pct_item = _center_cell(f"{pct:5.1f}%")
            if pct >= 15:
                pct_item.setForeground(QColor("#d97757"))
            self.spell_table.setItem(i, 1, pct_item)
            self.spell_table.setItem(i, 2, _center_cell(f"{int(info['total']):>13,}"))

        log.info("top damage render: chars=%d spells=%d shown=%d pending=%d",
                 matched, len(agg), len(rows), pending)

    # ── 특성 트리만 갱신 (top100 픽률 + 0/1/2pt 분포 + 영웅 선택률) ────────
    def _populate_talents(self, ranking_df) -> None:
        spell_db = _load_json("spell_db.json")
        triples: list[tuple[str, int, str]] = []
        for _, row in ranking_df.iterrows():
            rid = str(row["report_id"])
            try:
                fid = int(row["fight_id"])
            except (TypeError, ValueError):
                continue
            char = str(row["character"])
            triples.append((rid, fid, char))
        # node_id 기반 (Blizzard tree 매칭) — talent_id 는 ID 체계 달라 매칭 안 됨
        node_counts, node_rank_dist, matched = db_node_picks_for_ranks(triples)
        denom = max(matched, 1)

        all_trees = _load_json("talent_trees.json")
        key = f"{self.class_en}/{self.spec_en}"
        tree_data = all_trees.get(key)
        if tree_data and node_counts:
            hero_picks = hero_tree_picks(tree_data, triples)
            tree_html = _build_tree_html(tree_data, node_counts, node_rank_dist,
                                          hero_picks, denom, spell_db)
        else:
            tree_html = _tree_empty_html(
                f"{key} 트리 데이터 없음 — fetch_talent_trees.py 의 SPECS 에 추가 필요"
            )
        self.tree_view.setHtml(tree_html)
        log.info("talents tree: chars=%d unique_nodes=%d", matched, len(node_counts))

    # ── 선택 캐릭터 빌드 (장비 + 전투시작 버프 + 스탯) ────────────────────
    def _populate_character_build(self, rid: str, fid: int, char: str) -> None:
        v2 = _v2_data()
        if v2 is None:
            self.gear_table.setRowCount(0)
            self.build_info.setHtml(_build_info_empty_html("V2Data 로드 안 됨"))
            return
        pf = v2.pfight.get(f"{rid}:{fid}:{char}")
        if not isinstance(pf, dict):
            self.gear_table.setRowCount(0)
            self.build_info.setHtml(_build_info_empty_html(
                f"{char} 의 빌드 데이터 캐시 없음 — backfill 미진행 스펙이거나 타겟 외"
            ))
            return

        spell_db = _load_json("spell_db.json")
        item_db = _load_json("item_db.json")
        # 1) gear table
        gear = pf.get("gear") or []
        gear_sorted = sorted(
            (g for g in gear if isinstance(g, dict)),
            key=lambda g: (g.get("slot") if isinstance(g.get("slot"), int) else 99),
        )
        self.gear_table.setRowCount(len(gear_sorted))
        for i, g in enumerate(gear_sorted):
            slot = g.get("slot") if isinstance(g.get("slot"), int) else -1
            slot_kr = SLOT_KR.get(slot, f"슬롯 #{slot}")
            slot_cell = _center_cell(slot_kr)
            slot_cell.setData(Qt.ItemDataRole.UserRole, slot)  # 비교 diff 용
            self.gear_table.setItem(i, 0, slot_cell)
            # 아이템 — 한글명 + 아이콘 + 등급 컬러 + 툴팁
            iid = g.get("id")
            if isinstance(iid, int):
                self.gear_table.setItem(i, 1, _make_item_item(iid, item_db, gear_entry=g))
            else:
                self.gear_table.setItem(i, 1, QTableWidgetItem("?"))
            ilvl = g.get("ilvl") or "-"
            self.gear_table.setItem(i, 2, _center_cell(str(ilvl)))
            # 마부 — spell_db 에서 한글 이름 lookup (대부분 enchant ID 가 미해결 — fallback 으로 ID 만 표시)
            ench_id = g.get("ench")
            if ench_id:
                emeta = spell_db.get(str(ench_id), {})
                ename_ko = (emeta.get("name_ko") or "").strip()
                if ename_ko:
                    ench_cell = _make_spell_item(int(ench_id), ename_ko, spell_db)
                else:
                    # spell_db 미해결 — ID 표시 + 정보 미상 툴팁
                    ench_cell = QTableWidgetItem(f"#{ench_id}")
                    ench_cell.setForeground(QColor("#a39c8e"))
                    ench_cell.setToolTip(
                        f"<p style='color:#a39c8e;margin:0'>마부 #{ench_id}</p>"
                        f"<p style='color:#6b6359;font-size:8.5pt;margin:4px 0 0 0'>"
                        f"한글 DB 미해결 — enrich_kr.py 재실행 시 Wowhead 스크래핑 시도</p>"
                    )
            else:
                ench_cell = QTableWidgetItem("—")
                ench_cell.setForeground(QColor("#6b6359"))
            self.gear_table.setItem(i, 3, ench_cell)
            # 보석 — item_db 에서 한글명 + 첫 보석 아이콘
            gems = [x for x in (g.get("gems") or []) if isinstance(x, int)]
            if gems:
                gem_names = []
                for gid in gems:
                    gmeta = item_db.get(str(gid), {})
                    nm = gmeta.get("name_ko") or f"#{gid}"
                    gem_names.append(nm)
                gem_text = ", ".join(gem_names[:2])
                if len(gem_names) > 2:
                    gem_text += f" +{len(gem_names)-2}"
                gem_cell = QTableWidgetItem(gem_text)
                # 첫 보석 아이콘
                first_meta = item_db.get(str(gems[0]), {})
                if first_meta.get("icon"):
                    ic = _icon_for(first_meta["icon"])
                    if ic:
                        gem_cell.setIcon(ic)
                # 툴팁: 모든 보석 상세 (Qt rich-text 자동 인식)
                tip_parts = []
                for gid in gems:
                    gm = item_db.get(str(gid), {})
                    tip_parts.append(
                        f"<p style='margin:0 0 4px 0'>"
                        f"<span style='color:#f5f0e8'>{_html_escape(gm.get('name_ko') or '#'+str(gid))}</span>"
                        f" <span style='color:#6b6359;font-size:8.5pt'>#{gid}</span></p>"
                    )
                gem_cell.setToolTip("".join(tip_parts))
            else:
                gem_cell = QTableWidgetItem("—")
                gem_cell.setForeground(QColor("#6b6359"))
            self.gear_table.setItem(i, 4, gem_cell)

        # 2) buffs + stats
        sid = pf.get("sourceID") if isinstance(pf.get("sourceID"), int) else None
        in_combat_buffs = _pre_fight_buffs(rid, fid, sid, spell_db) if sid else []
        stats = pf.get("stats") if isinstance(pf.get("stats"), dict) else None
        # stats 없으면 백그라운드 refetch (옛 cache 엔트리)
        if not stats and _v2_data() is not None:
            self._spawn_stats_fetch(rid, fid, char)

        # Pre-pull buffs: cache 있으면 사용, 없으면 async fetch
        pre_pull = []
        prepull_loading = False
        v2 = _v2_data()
        if v2 is not None and sid is not None:
            prepull_key = f"{rid}:{fid}:{sid}"
            cached = v2.prepull.get(prepull_key)
            if cached is not None:
                pre_pull = _enrich_buff_list(cached, spell_db)
            else:
                # 백그라운드 페치 시작
                prepull_loading = True
                self._spawn_prepull_fetch(rid, fid, char)

        # 상태 저장 — pre-pull 페치 완료 시 재렌더에 사용
        self._last_build_render = {
            "rid": rid, "fid": fid, "char": char, "sid": sid,
            "gear": gear_sorted, "in_combat": in_combat_buffs,
            "stats": stats,
        }

        html = _build_info_html(char, pre_pull, in_combat_buffs, stats, gear_sorted,
                                prepull_loading=prepull_loading)
        self.build_info.setHtml(html)
        log.info("character build: %s gear=%d in_combat=%d pre_pull=%d loading=%s has_stats=%s",
                 char, len(gear_sorted), len(in_combat_buffs), len(pre_pull),
                 prepull_loading, bool(stats))

        # 비교 분석 hook — 양쪽 모두 렌더 시 diff 하이라이트
        if self._on_build_rendered_hook:
            try:
                self._on_build_rendered_hook(self)
            except Exception:
                log.exception("build rendered hook failed")

    def _on_ranking_context_menu(self, pos) -> None:
        """랭킹 행 우클릭 → 비교 분석 좌/우 추가."""
        if self._current_df is None or self._current_df.empty:
            return
        item = self.ranking_table.itemAt(pos)
        if not item:
            return
        row_idx = item.row()
        if row_idx < 0 or row_idx >= len(self._current_df):
            return
        rec = self._current_df.iloc[row_idx]
        rid = str(rec.get("report_id", ""))
        try:
            fid = int(rec.get("fight_id", 0))
        except (TypeError, ValueError):
            return
        char = str(rec.get("character", ""))
        if not rid or not char:
            return
        menu = QMenu(self)
        a_left = menu.addAction(f"비교 분석 → 좌측 추가 ({char})")
        a_right = menu.addAction(f"비교 분석 → 우측 추가 ({char})")
        chosen = menu.exec(self.ranking_table.viewport().mapToGlobal(pos))
        if chosen not in (a_left, a_right):
            return
        side = "left" if chosen == a_left else "right"
        mw = self.window()
        if hasattr(mw, "load_into_comparison"):
            mw.load_into_comparison(side, rid, fid, char)

    def _spawn_full_char_fetch(self, rid: str, fid: int, char: str) -> None:
        """임의 로그 / 비백필 캐릭 — pfight+events+prepull 일괄 페치 후 row 클릭 재처리."""
        self._full_char_request_token += 1
        token = self._full_char_request_token

        def _on_done(result):
            if token != self._full_char_request_token:
                return  # 사용자가 이미 다른 row 클릭함
            # 현재 선택된 row 가 같은 캐릭인지 확인 후 재호출
            if self._current_df is None or self._current_df.empty:
                return
            row_idx = self.ranking_table.currentRow()
            if row_idx < 0 or row_idx >= len(self._current_df):
                return
            cur = self._current_df.iloc[row_idx]
            if (str(cur.get("report_id", "")) == result["rid"]
                    and int(cur.get("fight_id", 0)) == result["fid"]
                    and str(cur.get("character", "")) == result["char"]):
                self._on_ranking_row_changed()  # 이번엔 캐시 hit 으로 정상 렌더

        thread = FullCharFetchThread(rid, fid, char, _v2_data(), self)
        thread.finished_ok.connect(_on_done)
        thread.finished.connect(thread.deleteLater)
        self._full_char_thread = thread  # GC 방지
        thread.start()

    def _spawn_stats_fetch(self, rid: str, fid: int, char: str) -> None:
        """stats 가 없는 옛 pfight 엔트리 백그라운드 강제 refetch."""
        self._stats_request_token += 1
        token = self._stats_request_token

        def _on_done(result):
            if token != self._stats_request_token:
                return
            last = self._last_build_render
            if not last:
                return
            if (result.get("rid") != last["rid"] or
                    result.get("fid") != last["fid"] or
                    result.get("char") != last["char"]):
                return
            pf = result.get("pf")
            if not isinstance(pf, dict):
                return
            new_stats = pf.get("stats") if isinstance(pf.get("stats"), dict) else None
            if not new_stats:
                return
            last["stats"] = new_stats
            # 현재 pre-pull 캐시도 그대로 가져옴
            spell_db = _load_json("spell_db.json")
            v2 = _v2_data()
            pre_pull = []
            sid = last.get("sid")
            if v2 and sid:
                cached = v2.prepull.get(f"{last['rid']}:{last['fid']}:{sid}")
                if cached is not None:
                    pre_pull = _enrich_buff_list(cached, spell_db)
            html = _build_info_html(last["char"], pre_pull, last["in_combat"],
                                     new_stats, last["gear"], prepull_loading=False)
            self.build_info.setHtml(html)
            log.info("stats refetched: %s keys=%d", last["char"], len(new_stats))

        thread = StatsFetchThread(rid, fid, char, _v2_data(), self)
        thread.finished_ok.connect(_on_done)
        thread.finished.connect(thread.deleteLater)
        self._stats_thread = thread
        thread.start()

    def _spawn_prepull_fetch(self, rid: str, fid: int, char: str) -> None:
        """Pre-pull buff 가 캐시에 없을 때 백그라운드 페치."""
        self._prepull_request_token += 1
        token = self._prepull_request_token

        def _on_done(result):
            if token != self._prepull_request_token:
                return  # 다른 행 클릭함
            last = self._last_build_render
            if not last:
                return
            if (result.get("rid") != last["rid"] or
                    result.get("fid") != last["fid"] or
                    result.get("char") != last["char"]):
                return
            buffs_raw = result.get("buffs") or []
            spell_db = _load_json("spell_db.json")
            pre_pull = _enrich_buff_list(buffs_raw, spell_db)
            html = _build_info_html(
                last["char"], pre_pull, last["in_combat"], last["stats"], last["gear"],
                prepull_loading=False,
            )
            self.build_info.setHtml(html)
            log.info("prepull rendered: %s pre_pull=%d", last["char"], len(pre_pull))

        thread = PrepullFetchThread(rid, fid, char, _v2_data(), self)
        thread.finished_ok.connect(_on_done)
        thread.finished.connect(thread.deleteLater)
        self._prepull_thread = thread  # GC 방지
        thread.start()

    # ── 딜사이클 (랭킹 행 선택 시) ────────────────────────────────────────
    def _on_ranking_row_changed(self) -> None:
        if self._current_df is None or self._current_df.empty:
            return
        sel = self.ranking_table.selectedItems()
        if not sel:
            self.rotation_timeline.set_empty("랭킹에서 캐릭터 클릭")
            return
        row_idx = self.ranking_table.currentRow()
        if row_idx < 0 or row_idx >= len(self._current_df):
            return
        row = self._current_df.iloc[row_idx]
        rid = str(row.get("report_id", ""))
        try:
            fid = int(row.get("fight_id", 0))
        except (TypeError, ValueError):
            return
        char = str(row.get("character", ""))

        # 캐시 미스 시 async 페치 (임의 로그 / 비백필 캐릭)
        v2 = _v2_data()
        pfight_key = f"{rid}:{fid}:{char}"
        if v2 is not None and pfight_key not in v2.pfight:
            self.rotation_timeline.set_empty(f"{char} V2 페치 중… (수~십초)")
            self.gear_table.setRowCount(0)
            self.build_info.setHtml(_build_info_empty_html(
                f"{char} 데이터 가져오는 중… (pfight + events + prepull)"
            ))
            self._spawn_full_char_fetch(rid, fid, char)
            return

        # V2 cache (메모리) lookup — 빠름
        self.loader.show_with(f"{char} 의 시전·버프 불러오는 중…")
        try:
            spell_db = _load_json("spell_db.json")  # 작음 (3MB), 메모리 캐시
            # 빌드 패널도 같이 갱신 (장비/버프/스탯) — 탭 안 바꿔도 캐시됨
            self._populate_character_build(rid, fid, char)
            sid = db_source_id(rid, char)
            if sid is None:
                self.rotation_timeline.set_empty("이 캐릭의 source ID 매핑 없음")
                return
            # events 캐시 미스 → 페치 후 재호출
            events_key = f"{rid}:{fid}:{sid}"
            if v2 is not None and events_key not in v2.events:
                self.rotation_timeline.set_empty(f"{char} events 페치 중…")
                self._spawn_full_char_fetch(rid, fid, char)
                return
            cast_events = db_casts(rid, fid, sid)
            buff_events_raw = db_buffs(rid, fid, sid)
            fight_window = db_fight_window(rid, fid)
            if not fight_window:
                self.rotation_timeline.set_empty("fight 윈도우 데이터 없음")
                return

            # WCL V2 의 sourceID 가 Buffs 에서 "버프 받는 자" 의미 — 본인이 받은
            # 모든 버프 (외부 포함). 본인이 시전한 적 있는 spell 만 통과시켜
            # self-cast 만 필터링. 비사제는 PI (10060) 만 예외로 keep.
            own_cast_spells = {int(e[1]) for e in cast_events if len(e) >= 2}
            PI_SPELL = 10060
            allow_pi = (self.class_en or "") != "Priest"
            buff_events = [
                e for e in buff_events_raw
                if (len(e) >= 2 and (
                    int(e[1]) in own_cast_spells
                    or (allow_pi and int(e[1]) == PI_SPELL)
                ))
            ]
            filtered_out = len(buff_events_raw) - len(buff_events)
            log.info("buffs filter: %d/%d kept (filtered %d external)",
                     len(buff_events), len(buff_events_raw), filtered_out)

            # 비사제 — 사제로부터 받은 PI 보강 fetch (cast events 에 없는 경우)
            if allow_pi and PI_SPELL not in own_cast_spells:
                v2 = _v2_data()
                if v2 is not None:
                    try:
                        pi_evs = v2.external_pi_buffs(rid, fid, char)
                        if pi_evs:
                            buff_events = list(buff_events) + list(pi_evs)
                            v2.flush()
                            log.info("PI fetched for %s: +%d events", char, len(pi_evs))
                    except Exception as e:
                        log.warning("PI fetch fail: %s", e)

            self._last_rotation_args = dict(
                char=char,
                cast_events=cast_events,
                buff_events=buff_events,
                fight_window=fight_window,
                spell_db=spell_db,
            )
            # 데이터 준비 끝 → 탭을 딜사이클로 자동 전환
            self.detail_tabs.setCurrentIndex(1)
            self.rotation_timeline.render_fight(orientation=self._orientation,
                                                **self._last_rotation_args)
            log.info("rotation: char=%s casts=%d buffs=%d orient=%s",
                     char, len(cast_events), len(buff_events), self._orientation)
        finally:
            self.loader.hide()

    def _on_orient_toggled(self, checked: bool) -> None:
        self._orientation = "v" if checked else "h"
        self.orient_btn.setText("가로 모드" if checked else "세로 모드")
        if self._last_rotation_args:
            self.rotation_timeline.render_fight(orientation=self._orientation,
                                                **self._last_rotation_args)
        log.info("orientation toggle -> %s", self._orientation)


class RaidTab(QWidget):
    """한 난이도 패널: 보스 ▏직업/전문화 ▏결과."""

    def __init__(self, difficulty_label: str, has_data: bool,
                 csv_filename: str = "rankings_with_talents.csv",
                 parent=None) -> None:
        super().__init__(parent)
        self.difficulty_label = difficulty_label
        self.has_data = has_data
        self.csv_filename = csv_filename
        self._sel_encounter: tuple[int, str] | None = None
        self._sel_spec: tuple[str, str] | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(0)

        # 전체를 가로 QSplitter 로 — 사용자가 좌우 비율 드래그 가능
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        # ── 보스 리스트
        self.boss_list = QListWidget()
        self.boss_list.setFont(QFont("", 10))
        for enc_id, name_en, name_kr in BOSSES:
            item = QListWidgetItem(name_kr)
            item.setToolTip(name_en)
            item.setData(Qt.ItemDataRole.UserRole, (enc_id, name_en))
            self.boss_list.addItem(item)
        self.boss_list.itemSelectionChanged.connect(self._on_boss_changed)
        fm = QFontMetrics(self.boss_list.font())
        boss_min = max(fm.horizontalAdvance(name_kr) for _, _, name_kr in BOSSES) + 36
        boss_panel = vbox_panel("네임드", self.boss_list)
        boss_panel.setMinimumWidth(boss_min)
        splitter.addWidget(boss_panel)

        # ── 직업/전문화 트리
        self.class_tree = QTreeWidget()
        self.class_tree.setHeaderHidden(True)
        self.class_tree.setFont(QFont("", 10))
        for cls_en, specs in CLASSES.items():
            cls_kr = CLASS_KR.get(cls_en, cls_en)
            color = CLASS_COLOR.get(cls_en, "#f5f0e8")
            parent = QTreeWidgetItem([cls_kr])
            parent.setForeground(0, QColor(color))
            parent.setToolTip(0, cls_en)
            parent.setData(0, Qt.ItemDataRole.UserRole, cls_en)
            for spec_en in specs:
                spec_kr = SPEC_KR.get(spec_en, spec_en)
                child = QTreeWidgetItem([f"  {spec_kr}"])
                child.setToolTip(0, f"{cls_en} / {spec_en}")
                child.setData(0, Qt.ItemDataRole.UserRole, (cls_en, spec_en))
                child.setForeground(0, QColor(color))
                parent.addChild(child)
            self.class_tree.addTopLevelItem(parent)
        self.class_tree.expandAll()
        self.class_tree.itemSelectionChanged.connect(self._on_spec_changed)
        fm = QFontMetrics(self.class_tree.font())
        all_labels = list(CLASS_KR.values()) + [f"  {v}" for v in SPEC_KR.values()]
        class_min = max(fm.horizontalAdvance(lbl) for lbl in all_labels) + 48
        class_panel = vbox_panel("직업 / 전문화", self.class_tree)
        class_panel.setMinimumWidth(class_min)
        splitter.addWidget(class_panel)

        # ── 결과 패널
        if self.has_data:
            self.panel = RankingPanel(csv_filename=self.csv_filename)
            self.panel.setMinimumWidth(600)
            splitter.addWidget(self.panel)
        else:
            placeholder = QLabel(
                f"{self.difficulty_label} 데이터는 아직 수집 전.\n\n"
                "fetch_rankings.py 의 DIFFICULTY 값을 4로 바꿔\n"
                "한 번 더 돌리면 이 영역이 활성화돼."
            )
            placeholder.setObjectName("placeholder")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setWordWrap(True)
            placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.panel = None
            pl_panel = vbox_panel("분석 결과", placeholder)
            pl_panel.setMinimumWidth(400)
            splitter.addWidget(pl_panel)

        # 초기 비율: 보스(좁게) | 직업(좁게) | 결과(아주 크게)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setChildrenCollapsible(False)

    def _on_boss_changed(self) -> None:
        items = self.boss_list.selectedItems()
        if not items:
            self._sel_encounter = None
        else:
            self._sel_encounter = items[0].data(Qt.ItemDataRole.UserRole)
        self._push()

    def _on_spec_changed(self) -> None:
        items = self.class_tree.selectedItems()
        if not items:
            self._sel_spec = None
        else:
            data = items[0].data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and len(data) == 2:
                self._sel_spec = data
            else:
                self._sel_spec = None
        self._push()

    def _push(self) -> None:
        if not self.panel:
            return
        enc_id, enc_name = (self._sel_encounter or (None, None))
        cls_en, spec_en = (self._sel_spec or (None, None))
        log.info("filter: boss=%s spec=%s/%s", enc_name, cls_en, spec_en)
        self.panel.set_filter(enc_id, enc_name, cls_en, spec_en)


_RE_WCL_REPORT = __import__("re").compile(
    r"(?:warcraftlogs\.com|wcl\.gg)/reports/([a-zA-Z0-9]+)"
)
_RE_WCL_FIGHT = __import__("re").compile(r"fight=(\d+|last)")
_RE_WCL_SOURCE = __import__("re").compile(r"source=(\d+)")


def _parse_wcl_url(url: str) -> dict | None:
    """WCL URL → {rid, fid (str|None), source (int|None)}. 없으면 None."""
    if not url:
        return None
    m = _RE_WCL_REPORT.search(url)
    if not m:
        return None
    out: dict = {"rid": m.group(1), "fid": None, "source": None}
    fm = _RE_WCL_FIGHT.search(url)
    if fm:
        out["fid"] = fm.group(1)
    sm = _RE_WCL_SOURCE.search(url)
    if sm:
        try:
            out["source"] = int(sm.group(1))
        except ValueError:
            pass
    return out


def _fetch_report_players(v2, rid: str, fid: int) -> list[dict] | None:
    """V2 playerDetails 로 fight 안 모든 플레이어 → [{name, class, spec, sourceID, role, ilvl}]."""
    if v2 is None:
        return None
    try:
        d = v2.cli.query(
            """
            query($code: String!, $fightIDs: [Int]!) {
              reportData { report(code: $code) {
                playerDetails(fightIDs: $fightIDs, includeCombatantInfo: true)
              } }
            }
            """,
            {"code": rid, "fightIDs": [int(fid)]},
        )
    except Exception:
        log.exception("playerDetails fetch fail %s/%s", rid, fid)
        return None
    rep = (((d or {}).get("reportData") or {}).get("report") or {})
    pd_ = (rep.get("playerDetails") or {})
    actual = pd_.get("data", {}).get("playerDetails") if isinstance(pd_, dict) and "data" in pd_ else pd_
    if not isinstance(actual, dict):
        return None
    out: list[dict] = []
    for role in ("dps", "tanks", "healers"):
        for p in actual.get(role, []) or []:
            if not isinstance(p, dict):
                continue
            ci = p.get("combatantInfo") or {}
            il_raw = (ci.get("stats") or {}).get("Item Level") or {}
            ilvl = il_raw.get("min") if isinstance(il_raw, dict) else None
            specs = p.get("specs") or []
            spec_kr = (specs[0] if specs else "") or ""
            cls = p.get("type") or ""
            out.append({
                "name": p.get("name") or "",
                "class": cls,
                "spec": spec_kr,
                "sourceID": p.get("id"),
                "role": role,
                "ilvl": ilvl,
                "server": p.get("server") or "",
            })
    return out


class ArbitraryLogTab(QWidget):
    """WCL URL 입력 → 임의 fight + player 단일 분석. RankingPanel 재사용."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fights: list[dict] = []
        self._players: list[dict] = []
        self._rid: str | None = None
        self._pending_char_select: str | None = None  # _on_fight_changed 끝나면 선택
        self._build_ui()

    def load_url_and_select(self, rid: str, fid: int, char: str) -> None:
        """외부 (비교에 추가 등) 호출용 — URL 자동 입력 + fetch + 특정 캐릭 row 선택."""
        url = f"https://www.warcraftlogs.com/reports/{rid}?fight={fid}"
        self.url_input.setText(url)
        self._pending_char_select = char
        self._on_fetch()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        # URL row
        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        url_lab = QLabel("WCL URL")
        url_lab.setObjectName("section")
        url_row.addWidget(url_lab)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "https://www.warcraftlogs.com/reports/abc123  또는  ko.warcraftlogs.com/reports/abc123#fight=2"
        )
        self.url_input.returnPressed.connect(self._on_fetch)
        url_row.addWidget(self.url_input, 1)
        self.fetch_btn = QPushButton("리포트 분석")
        self.fetch_btn.clicked.connect(self._on_fetch)
        url_row.addWidget(self.fetch_btn)
        outer.addLayout(url_row)

        # Fight selector
        fight_row = QHBoxLayout()
        fight_lab = QLabel("Fight")
        fight_lab.setObjectName("section")
        fight_row.addWidget(fight_lab)
        self.fight_combo = QComboBox()
        self.fight_combo.setMinimumWidth(420)
        self.fight_combo.currentIndexChanged.connect(self._on_fight_changed)
        fight_row.addWidget(self.fight_combo)
        fight_row.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #a39c8e;")
        fight_row.addWidget(self.status_label)
        outer.addLayout(fight_row)

        # Embedded RankingPanel — 클릭 시 _populate_character_build 등 그대로 동작
        self.panel = RankingPanel()
        outer.addWidget(self.panel, 1)

    def _on_fetch(self) -> None:
        url = self.url_input.text().strip()
        parsed = _parse_wcl_url(url)
        if not parsed:
            self.status_label.setText("URL 파싱 실패 — warcraftlogs.com/reports/... 형식")
            return
        self.status_label.setText("리포트 메타 가져오는 중…")
        QApplication.processEvents()
        v2 = _v2_data()
        if v2 is None:
            self.status_label.setText("V2Data 사용 불가 (.env 확인)")
            return
        meta = v2.report_meta(parsed["rid"])
        if not meta:
            self.status_label.setText("리포트 못 찾음 (private 이거나 잘못된 ID)")
            return
        # 캐시된 meta 가 옛 killType:Kills 일 수 있어서, fight 갯수 0 이거나
        # encounter 누락이면 force refetch 한 번.
        if not (meta.get("fights") or []):
            v2.meta.pop(parsed["rid"], None)
            meta = v2.report_meta(parsed["rid"])
            if not meta:
                self.status_label.setText("재페치 실패 — 리포트 권한 / 네트워크 확인")
                return
        self._rid = parsed["rid"]
        self._fights = meta.get("fights") or []
        if not self._fights:
            self.status_label.setText(f"{self._rid} — fights 0개. private report 일 가능성")
            return
        boss_kr = {enc_id: name_kr for enc_id, _, name_kr in BOSSES}
        DIFF_KR = {1: "LFR", 2: "Normal", 3: "Heroic", 4: "Mythic", 5: "Mythic"}  # WoW 11.x
        self.fight_combo.blockSignals(True)
        self.fight_combo.clear()
        for f in self._fights:
            fid = f.get("id"); enc_id = f.get("encounterID")
            dur = (f.get("endTime", 0) - f.get("startTime", 0)) / 1000.0
            nm = boss_kr.get(enc_id, f.get("name") or f"encounter {enc_id}")
            diff_lab = DIFF_KR.get(f.get("difficulty"), f"diff{f.get('difficulty')}")
            kill_mark = "✓" if f.get("kill") else "✗"
            self.fight_combo.addItem(
                f"fight {fid} · {diff_lab} · {kill_mark} {nm} ({dur:.0f}s)", userData=fid
            )
        self.fight_combo.blockSignals(False)
        self.status_label.setText(f"{self._rid} · fights {len(self._fights)}")
        # URL 에 fight 지정돼 있으면 선택
        if parsed.get("fid"):
            for i in range(self.fight_combo.count()):
                if str(self.fight_combo.itemData(i)) == str(parsed["fid"]):
                    self.fight_combo.setCurrentIndex(i)
                    return
        if self.fight_combo.count() > 0:
            self.fight_combo.setCurrentIndex(0)
            self._on_fight_changed(0)

    def _on_fight_changed(self, idx: int) -> None:
        if idx < 0 or not self._rid:
            return
        fid = self.fight_combo.itemData(idx)
        if fid is None:
            return
        self.status_label.setText(f"fight {fid} 플레이어 가져오는 중…")
        QApplication.processEvents()
        v2 = _v2_data()
        players = _fetch_report_players(v2, self._rid, int(fid))
        if not players:
            self.status_label.setText("플레이어 목록 페치 실패")
            return
        self._players = players
        # fake DataFrame — 기존 RankingPanel 의 _current_df 형식
        import pandas as pd
        rows = []
        for i, p in enumerate(players, 1):
            rows.append({
                "report_id": self._rid,
                "fight_id": int(fid),
                "character": p["name"],
                "server": p.get("server") or "",
                "class": p["class"],
                "spec": p["spec"],
                "dps": 0,  # damage 계산 없이 0 으로
                "item_level": p.get("ilvl") or "",
                "rank": i,
                "encounter_id": next((f.get("encounterID") for f in self._fights if f.get("id") == int(fid)), 0),
            })
        df = pd.DataFrame(rows)
        fight_meta = next((f for f in self._fights if f.get("id") == int(fid)), {})
        enc_id = fight_meta.get("encounterID")
        from collections import OrderedDict
        boss_kr = next((n for eid, _, n in BOSSES if eid == enc_id), f"encounter {enc_id}")
        # RankingPanel 의 헤더/데이터만 update — _refresh() 의 aggregate 부분은 안 거침
        p = self.panel
        p.encounter_id = enc_id
        p.encounter_name = boss_kr
        p.class_en = None  # mixed
        p.spec_en = None
        p._current_df = df
        p.header.setText(f"{boss_kr}  ·  {self._rid}/fight {fid}  ·  플레이어 {len(players)}명")
        p.spell_table.setRowCount(0)
        p.gear_table.setRowCount(0)
        p.build_info.setHtml(_build_info_empty_html("플레이어 클릭 시 빌드 표시"))
        p.tree_view.setHtml(_tree_empty_html("임의 로그 모드 — 트리 픽률 X (단일 fight)"))
        p.rotation_timeline.set_empty("플레이어 클릭")
        p._populate_rankings(df)
        self.status_label.setText(f"플레이어 {len(players)}명 — 행 클릭")
        # pending char 가 있으면 자동 선택 (비교에 추가 흐름)
        if self._pending_char_select:
            target = self._pending_char_select
            self._pending_char_select = None
            for i in range(p.ranking_table.rowCount()):
                it = p.ranking_table.item(i, 1)
                if it and it.text() == target:
                    p.ranking_table.selectRow(i)
                    break


class ComparisonTab(QWidget):
    """비교 분석 탭 — ArbitraryLogTab 2개를 좌우 splitter 로 배치.

    각각 독립적으로 URL → fight → player 선택. 같은 시점/같은 보스 다른 캐릭
    비교, 본인 로그 vs 톱100 비교, 본인 다른 시기 비교 등 자유.
    """

    def load_into(self, side: str, rid: str, fid: int, char: str) -> None:
        """좌(left) / 우(right) 한쪽에 URL 자동 입력 + 캐릭 선택."""
        target = self.left if side == "left" else self.right
        target.load_url_and_select(rid, fid, char)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        self.hint = QLabel(
            "비교 분석 — 좌측 / 우측 각각 WCL URL 입력. 캐릭터 클릭하면 자동 V2 페치."
        )
        self.hint.setStyleSheet("color: #a39c8e; font-size: 9.5pt; padding: 4px 12px;")
        outer.addWidget(self.hint)

        self.left = ArbitraryLogTab()
        self.right = ArbitraryLogTab()
        # 딜사이클 timeline 을 각 패널에서 detach → 하단 stack 으로 옮김
        left_tl = self.left.panel.detach_rotation_timeline()
        right_tl = self.right.panel.detach_rotation_timeline()

        # 위/아래 스플릿: 상단(좌우 패널) ↕ 하단(딜사이클 위아래 stack)
        v_split = QSplitter(Qt.Orientation.Vertical)
        v_split.setChildrenCollapsible(False)

        # 상단 — 좌우 ArbitraryLogTab (timeline 빠진 상태)
        top_split = QSplitter(Qt.Orientation.Horizontal)
        top_split.setChildrenCollapsible(False)
        top_split.addWidget(self.left)
        top_split.addWidget(self.right)
        top_split.setStretchFactor(0, 1)
        top_split.setStretchFactor(1, 1)
        v_split.addWidget(top_split)

        # 하단 — 딜사이클 헤더 (버프 토글) + 좌/우 timeline 위/아래 stack
        bottom = QWidget()
        b_layout = QVBoxLayout(bottom)
        b_layout.setContentsMargins(8, 4, 8, 0)
        b_layout.setSpacing(4)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head_lab = QLabel("딜사이클 비교 (위=좌 · 아래=우)")
        head_lab.setStyleSheet("color: #f5f0e8; font-size: 10pt; font-weight: 600;")
        head.addWidget(head_lab)
        head.addStretch()
        self.buff_chk = QCheckBox("버프 표시")
        self.buff_chk.setChecked(True)
        self.buff_chk.toggled.connect(self._on_buff_toggled)
        head.addWidget(self.buff_chk)
        b_layout.addLayout(head)
        tl_split = QSplitter(Qt.Orientation.Vertical)
        tl_split.setChildrenCollapsible(False)
        # timeline 자체에 라벨 wrapper (어느 쪽인지 식별)
        def _wrap_tl(lab_text: str, tl) -> QWidget:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            lab = QLabel(lab_text)
            lab.setStyleSheet("color: #a39c8e; font-size: 9pt; padding: 2px 4px;")
            v.addWidget(lab)
            v.addWidget(tl, 1)
            return w
        tl_split.addWidget(_wrap_tl("◀ 좌측", left_tl))
        tl_split.addWidget(_wrap_tl("◀ 우측", right_tl))
        tl_split.setStretchFactor(0, 1)
        tl_split.setStretchFactor(1, 1)
        b_layout.addWidget(tl_split, 1)
        v_split.addWidget(bottom)
        v_split.setStretchFactor(0, 3)  # 상단 (랭킹/장비/특성) 더 큼
        v_split.setStretchFactor(1, 2)  # 하단 (딜사이클)
        outer.addWidget(v_split, 1)

        # 양쪽 RankingPanel build 렌더 hook 등록 → 다 차면 diff 하이라이트
        self.left.panel._on_build_rendered_hook = self._on_side_build_rendered
        self.right.panel._on_build_rendered_hook = self._on_side_build_rendered

    def _on_buff_toggled(self, checked: bool) -> None:
        """버프 lane 표시/숨김 — 양쪽 timeline 에 동시 적용."""
        self.left.panel.rotation_timeline.set_buffs_visible(checked)
        self.right.panel.rotation_timeline.set_buffs_visible(checked)

    # ── 비교 diff 하이라이트 ─────────────────────────────────────────────
    def _on_side_build_rendered(self, panel) -> None:
        """한쪽 build 렌더 끝남 → 양쪽 다 차있으면 gear diff 적용."""
        ld = self.left.panel._last_build_render
        rd = self.right.panel._last_build_render
        if not (ld and rd):
            self.hint.setText(
                "비교 분석 — 좌측 / 우측 각각 WCL URL 입력. 캐릭터 클릭하면 자동 V2 페치."
            )
            return
        diff_slots = self._apply_gear_diff(
            self.left.panel.gear_table, ld.get("gear") or [],
            self.right.panel.gear_table, rd.get("gear") or [],
        )
        lchar = ld.get("char", "?")
        rchar = rd.get("char", "?")
        self.hint.setText(
            f"비교: 좌 {lchar} ↔ 우 {rchar}  ·  장비 차이 {diff_slots} 슬롯 (빨강 강조)"
        )

    @staticmethod
    def _apply_gear_diff(ltab, lgear, rtab, rgear) -> int:
        """양쪽 gear_table 의 슬롯별 비교 — item ID 다르면 두 테이블 모두 빨강 배경.

        Returns: diff 슬롯 갯수.
        """
        diff_color = QColor(120, 50, 50, 130)   # 어두운 빨강 (반투명)
        same_color = QColor(0, 0, 0, 0)         # 투명 (초기화)
        # 슬롯 → item_id 매핑
        l_by_slot = {g.get("slot"): g.get("id") for g in lgear if isinstance(g, dict)}
        r_by_slot = {g.get("slot"): g.get("id") for g in rgear if isinstance(g, dict)}

        def paint(table, partner_by_slot):
            n_diff = 0
            for row in range(table.rowCount()):
                slot_item = table.item(row, 0)
                if not slot_item:
                    continue
                slot = slot_item.data(Qt.ItemDataRole.UserRole)
                my_id = None
                # 같은 테이블의 gear list 에서 이 slot 의 id 찾기
                for g in (lgear if table is ltab else rgear):
                    if isinstance(g, dict) and g.get("slot") == slot:
                        my_id = g.get("id")
                        break
                partner_id = partner_by_slot.get(slot)
                is_diff = (my_id != partner_id)
                color = diff_color if is_diff else same_color
                if is_diff:
                    n_diff += 1
                for col in range(table.columnCount()):
                    cell = table.item(row, col)
                    if cell:
                        cell.setBackground(color)
            return n_diff

        n_left = paint(ltab, r_by_slot)
        paint(rtab, l_by_slot)
        return n_left


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WoW 한밤 레이드 로그 분석기")
        self.resize(2200, 1280)
        self.setMinimumSize(1400, 860)
        # 작업표시줄 제외하고 화면에 들어가면 maximize 도 OK
        self.showMaximized()

        self._build_menubar()

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        # 영웅 / 신화 CSV 존재 여부로 has_data 결정
        if DATA_DIR:
            heroic_has = (DATA_DIR / "rankings_zone46_heroic_dps_top100.csv").exists()
            mythic_has = (DATA_DIR / "rankings_with_talents.csv").exists()
        else:
            heroic_has = mythic_has = False
        tabs.addTab(
            RaidTab("영웅", has_data=heroic_has,
                    csv_filename="rankings_zone46_heroic_dps_top100.csv"),
            "영웅 레이드"
        )
        tabs.addTab(
            RaidTab("신화", has_data=mythic_has,
                    csv_filename="rankings_with_talents.csv"),
            "신화 레이드"
        )
        tabs.addTab(ArbitraryLogTab(), "임의 로그 분석")
        self.comparison_tab = ComparisonTab()
        tabs.addTab(self.comparison_tab, "비교 분석")
        self.tabs = tabs
        tabs.setCurrentIndex(1)
        tabs.currentChanged.connect(lambda i: log.info("tab change: %s", tabs.tabText(i)))

        container = QFrame()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(tabs)
        self.setCentralWidget(container)
        log.info("MainWindow ready")

    def _build_menubar(self) -> None:
        """테마 메뉴 — 4개 액션 (라디오), 즉시 적용 + 디스크 저장."""
        bar = self.menuBar()
        theme_menu = bar.addMenu("테마")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        current_id = _load_theme_id()
        for tid, theme in THEMES.items():
            act = QAction(theme.name_kr, self, checkable=True)
            act.setData(tid)
            if tid == current_id:
                act.setChecked(True)
            # default arg 로 클로저 변수 고정 (Python 클로저 함정 회피)
            act.triggered.connect(lambda _checked=False, _id=tid: self._switch_theme(_id))
            self._theme_group.addAction(act)
            theme_menu.addAction(act)

    def load_into_comparison(self, side: str, rid: str, fid: int, char: str) -> None:
        """RankingPanel 우클릭 메뉴 → ComparisonTab 한쪽 로드 + 탭 전환."""
        self.comparison_tab.load_into(side, rid, fid, char)
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) is self.comparison_tab:
                self.tabs.setCurrentIndex(i)
                break

    def _switch_theme(self, tid: str) -> None:
        theme = THEMES.get(tid)
        if not theme:
            return
        app = QApplication.instance()
        if app is None:
            return
        apply_theme(app, theme)
        _save_theme_id(tid)


def main() -> None:
    log.info("QApplication start")
    app = QApplication(sys.argv)
    theme = THEMES.get(_load_theme_id()) or THEMES[DEFAULT_THEME_ID]
    apply_theme(app, theme)
    win = MainWindow()
    win.show()
    log.info("event loop enter")
    rc = app.exec()
    log.info("exit code=%d", rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
