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

from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QPalette, QPixmap
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
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
    """WoWhead JSON tooltip → Qt rich-text 툴팁."""
    name_ko = spell_meta.get("name_ko") or ""
    name_en = spell_meta.get("name_en") or ""
    body = spell_meta.get("tooltip_ko") or ""
    title = name_ko or name_en or "(이름 없음)"
    subtitle = f" <span style='color:#a39c8e;font-size:9pt'>({name_en})</span>" if name_ko and name_en else ""
    return (
        f"<div style='max-width:480px'>"
        f"<div style='color:#d97757;font-size:11pt;font-weight:600;margin-bottom:4px'>{title}{subtitle}</div>"
        f"<div style='color:#f5f0e8'>{body}</div>"
        f"</div>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# SQLite (cache.db) — 큰 데이터는 JSON 대신 인덱스 조회로

import sqlite3 as _sqlite

_db_conn: _sqlite.Connection | None = None


def _db() -> _sqlite.Connection | None:
    global _db_conn
    if _db_conn is not None:
        return _db_conn
    if not DATA_DIR:
        return None
    path = DATA_DIR / "cache.db"
    if not path.exists():
        log.warning("cache.db 없음 — migrate_to_sqlite.py 실행 필요")
        return None
    _db_conn = _sqlite.connect(str(path), check_same_thread=False)
    _db_conn.row_factory = _sqlite.Row
    _db_conn.execute("PRAGMA journal_mode=WAL")
    _db_conn.execute("PRAGMA cache_size=-65536")  # 64MB cache
    log.info("opened cache.db at %s", path)
    return _db_conn


def db_casts(rid: str, fid: int, sid: int) -> list[tuple]:
    """[(ts, spell_id, type), ...]"""
    c = _db()
    if not c:
        return []
    rows = c.execute(
        "SELECT ts, spell_id, type FROM casts WHERE rid=? AND fid=? AND source_id=?",
        (rid, fid, sid),
    ).fetchall()
    return [(r["ts"], r["spell_id"], r["type"]) for r in rows]


def db_buffs(rid: str, fid: int, sid: int) -> list[tuple]:
    """[(ts, spell_id, type[, stack]), ...]"""
    c = _db()
    if not c:
        return []
    rows = c.execute(
        "SELECT ts, spell_id, type, stack FROM buffs WHERE rid=? AND fid=? AND source_id=?",
        (rid, fid, sid),
    ).fetchall()
    out = []
    for r in rows:
        rec = [r["ts"], r["spell_id"], r["type"]]
        if r["stack"] is not None:
            rec.append(r["stack"])
        out.append(tuple(rec))
    return out


def db_source_id(rid: str, char_name: str) -> int | None:
    c = _db()
    if not c:
        return None
    r = c.execute(
        "SELECT source_id FROM source_ids WHERE rid=? AND char_name=?",
        (rid, char_name),
    ).fetchone()
    return r["source_id"] if r else None


def db_fight_window(rid: str, fid: int) -> list | None:
    c = _db()
    if not c:
        return None
    r = c.execute(
        "SELECT start_ms, end_ms FROM fights WHERE rid=? AND fid=?",
        (rid, fid),
    ).fetchone()
    if not r:
        return None
    return [r["start_ms"], r["end_ms"]]


def db_damage(rid: str, fid: int, sid: int) -> list[dict]:
    c = _db()
    if not c:
        return []
    rows = c.execute(
        "SELECT spell_guid, name, icon, total FROM damage WHERE rid=? AND fid=? AND source_id=?",
        (rid, fid, sid),
    ).fetchall()
    return [{"guid": r["spell_guid"], "name": r["name"], "icon": r["icon"], "total": r["total"]} for r in rows]


def _ingest_v2_damage_to_db(damage_cache: dict) -> None:
    """V2Data.damage 캐시의 새 엔트리들을 SQLite damage 테이블에 INSERT."""
    c = _db()
    if not c:
        return
    rows = []
    for key, entries in damage_cache.items():
        if not isinstance(entries, list):
            continue
        parts = key.split(":")
        if len(parts) != 3:
            continue
        try:
            rid, fid, sid = parts[0], int(parts[1]), int(parts[2])
        except (TypeError, ValueError):
            continue
        # 이미 있으면 skip
        existing = c.execute(
            "SELECT 1 FROM damage WHERE rid=? AND fid=? AND source_id=? LIMIT 1",
            (rid, fid, sid),
        ).fetchone()
        if existing:
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            gid = e.get("guid")
            if not isinstance(gid, int):
                continue
            rows.append((rid, fid, sid, gid, e.get("name") or "", e.get("icon") or "",
                         int(e.get("total") or 0)))
    if rows:
        c.executemany(
            "INSERT INTO damage (rid, fid, source_id, spell_guid, name, icon, total) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        c.commit()
        log.info("damage ingested to db: %d rows", len(rows))


def db_talent_counts_for_ranks(rid_fid_char: list[tuple[str, int, str]]) -> tuple[dict[int, int], int]:
    """주어진 (rid, fid, char) 리스트 들의 talent_id 별 출현 횟수 + 본 캐릭 수."""
    c = _db()
    if not c:
        return {}, 0
    if not rid_fid_char:
        return {}, 0
    # 임시 테이블에 묶음 넣고 JOIN
    c.execute("CREATE TEMP TABLE IF NOT EXISTS _q (rid TEXT, fid INTEGER, char_name TEXT)")
    c.execute("DELETE FROM _q")
    c.executemany("INSERT INTO _q VALUES (?,?,?)", rid_fid_char)
    rows = c.execute("""
        SELECT t.talent_id AS tid, COUNT(*) AS cnt
        FROM talents t INNER JOIN _q q
          ON t.rid=q.rid AND t.fid=q.fid AND t.char_name=q.char_name
        GROUP BY t.talent_id
    """).fetchall()
    counts = {r["tid"]: r["cnt"] for r in rows}
    matched_row = c.execute("""
        SELECT COUNT(*) AS n FROM (
          SELECT DISTINCT t.rid, t.fid, t.char_name
          FROM talents t INNER JOIN _q q
            ON t.rid=q.rid AND t.fid=q.fid AND t.char_name=q.char_name
        )
    """).fetchone()
    matched = matched_row["n"] if matched_row else 0
    return counts, matched


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
# 스타일 (다크 테마 + 위젯 QSS)

DARK_QSS = """
/* === Claude-inspired warm dark ============================================ */
QWidget {
    background-color: #1a1614;
    color: #f5f0e8;
    font-family: 'Pretendard Variable', 'Pretendard', 'Segoe UI Variable',
                 'Segoe UI', -apple-system, system-ui, sans-serif;
    font-size: 10pt;
}
QMainWindow { background-color: #1a1614; border: none; }
QTabWidget::pane { background-color: #1a1614; border: none; border-top: 1px solid #2c2521; }

/* 패널 헤더 — 회색, 작게, uppercase 트래킹 (chrome 톤) */
QLabel#section {
    color: #a39c8e;
    font-size: 9.5pt;
    font-weight: 500;
    padding: 8px 4px;
    margin-bottom: 4px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
/* 페이지 헤더 — 카드 X, 브레드크럼 톤, hairline 만 */
QLabel#pageHeader {
    color: #f5f0e8;
    font-size: 13pt;
    font-weight: 600;
    padding: 8px 16px;
    background-color: transparent;
    border: none;
    border-bottom: 1px solid #2c2521;
    letter-spacing: -0.015em;
}
QLabel#placeholder {
    color: #a39c8e;
    font-size: 10.5pt;
    padding: 40px 24px;
    background-color: #221d1a;
    border: 1px dashed #3a322c;
    border-radius: 12px;
}

/* === Lists / Trees ======================================================== */
QListWidget, QTreeWidget {
    background-color: #221d1a;
    border: 1px solid #2c2521;
    border-radius: 10px;
    padding: 6px;
    outline: none;
}
QListWidget::item, QTreeWidget::item {
    padding: 8px 8px 8px 12px;
    border-radius: 6px;
    border-left: 3px solid transparent;
    margin: 1px 0;
}
QListWidget::item:hover, QTreeWidget::item:hover { background-color: #2a2420; }
QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: rgba(217, 119, 87, 45);
    border-left: 3px solid #d97757;
    color: #ffffff;
}
QListWidget::item:selected:active, QTreeWidget::item:selected:active {
    background-color: rgba(217, 119, 87, 70);
}
QTreeWidget::branch { background-color: transparent; }

/* === Tabs ================================================================= */
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab {
    background-color: transparent;
    color: #a39c8e;
    padding: 11px 26px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
    font-size: 10.5pt;
}
QTabBar::tab:selected { color: #d97757; border-bottom: 2px solid #d97757; }
QTabBar::tab:hover:!selected { color: #f5f0e8; border-bottom: 2px solid #3a322c; }

/* === Buttons ============================================================== */
QPushButton {
    background-color: #2a2420;
    color: #f5f0e8;
    border: 1px solid #3a322c;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
}
QPushButton:hover { background-color: #332b25; border-color: #d97757; }
QPushButton:pressed { background-color: #3d342c; }
QPushButton:checked {
    background-color: #d97757;
    color: #1a1614;
    border-color: #d97757;
    font-weight: 600;
}
QPushButton:checked:hover { background-color: #e8855f; }

/* === Tables =============================================================== */
QTableWidget {
    background-color: #221d1a;
    border: 1px solid #2c2521;
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: rgba(217, 119, 87, 50);
    selection-color: #ffffff;
}
QTableWidget::item { padding: 8px 8px; border-bottom: 1px solid #1f1a17; }
QTableWidget::item:hover { background-color: #2a2420; }
QTableWidget::item:selected {
    background-color: rgba(217, 119, 87, 60);
    color: #ffffff;
}
QHeaderView::section {
    background-color: #221d1a;
    color: #a39c8e;
    padding: 8px 12px;
    border: none;
    border-bottom: 1px solid #2c2521;
    font-weight: 500;
    font-size: 9.5pt;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
QHeaderView::section:last { border-right: none; }

/* === Splitters — hairline + 큰 hit area, hover 도 subtle ================== */
QSplitter::handle { background-color: #2c2521; }
QSplitter::handle:hover { background-color: #3a322c; }
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }

/* === Scrollbars =========================================================== */
QScrollBar:vertical {
    background-color: #221d1a;
    width: 12px;
    border: none;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background-color: #3a322c;
    border-radius: 4px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover { background-color: #d97757; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; width: 0; }
QScrollBar:horizontal {
    background-color: #221d1a;
    height: 12px;
    border: none;
    margin: 2px 4px;
}
QScrollBar::handle:horizontal {
    background-color: #3a322c;
    border-radius: 4px;
    min-width: 32px;
}
QScrollBar::handle:horizontal:hover { background-color: #d97757; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { height: 0; width: 0; }

/* === Tooltips ============================================================= */
QToolTip {
    background-color: #221d1a;
    color: #f5f0e8;
    border: 1px solid #3a322c;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 10pt;
}
"""


def apply_dark_palette(app: QApplication) -> None:
    """Fusion 스타일 + Claude-inspired 따뜻한 다크 팔레트."""
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor("#1a1614"))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor("#f5f0e8"))
    pal.setColor(QPalette.ColorRole.Base,            QColor("#221d1a"))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor("#1f1a17"))
    pal.setColor(QPalette.ColorRole.Text,            QColor("#f5f0e8"))
    pal.setColor(QPalette.ColorRole.Button,          QColor("#2a2420"))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor("#f5f0e8"))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor("#d97757"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#1a1614"))
    pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor("#221d1a"))
    pal.setColor(QPalette.ColorRole.ToolTipText,     QColor("#f5f0e8"))
    app.setPalette(pal)


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
body.horizontal { overflow-x: auto; overflow-y: hidden; }
body.vertical   { overflow-x: hidden; overflow-y: auto; }
/* 시간 → 픽셀 매핑 함수 (CSS calc) — --t (초) 와 --pps 곱 */
body.horizontal .pos-t { left: calc(var(--t) * var(--pps) * 1px); }
body.vertical   .pos-t { top:  calc(var(--t) * var(--pps) * 1px); }
body.horizontal .size-w { width:  max(8px, calc(var(--w) * var(--pps) * 1px)); }
body.vertical   .size-w { height: max(8px, calc(var(--w) * var(--pps) * 1px)); }
body.horizontal .span-d { width:  calc(var(--d) * var(--pps) * 1px); }
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

/* === 시간 축 (1초 단위, 5초마다 라벨) ============================= */
.tick { position: absolute; color: transparent; }
.horizontal .axis  { position: relative; height: 26px; border-bottom: 1px solid #4a4039; margin-bottom: 8px; }
.horizontal .tick  { top: 0; height: 26px; width: 1px; background: #1f1a17; }
.horizontal .tick.major { background: #6b6359; width: 2px; }
.horizontal .tick.label { color: #888; font-size: 10px; width: auto; background: none; padding-left: 4px; line-height: 26px; }
.horizontal .tick.label.major-label { color: #d97757; font-weight: 600; font-size: 11px; }

.vertical .axis  { position: absolute; left: 0; top: 0; width: 32px; border-right: 1px solid #3a322c; }
.vertical .tick  { left: 24px; width: 8px; height: 1px; background: #2a2420; }
.vertical .tick.major { left: 20px; width: 12px; background: #4a4039; }
.vertical .tick.label {
    left: 0; width: 22px; height: auto; background: none;
    color: #888; font-size: 10px; text-align: right; padding-right: 4px;
}

/* === 시전 / 버프 lane 컨테이너 ==================================== */
.casts, .buffs { position: relative; }
.horizontal .casts { height: 32px; margin-bottom: 8px; }
.horizontal .buffs { background: #1f1a17; border-radius: 4px; padding: 4px 0; }
.vertical  .lanes  { position: absolute; left: 36px; top: 0; right: 0; }
.vertical  .lanes-buffs { left: auto; right: 0; }

/* === 캐스트 아이콘 (40px) ========================================= */
.cast {
    position: absolute;
    width: 40px; height: 40px;
    z-index: 2;
}
.cast img {
    width: 40px; height: 40px; display: block;
    border: 1px solid #4a4039; border-radius: 5px; box-sizing: border-box;
}
.cast:hover img { border-color: #d97757; z-index: 10; }

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
    z-index: 100; pointer-events: none;
    font-size: 11px;
}
.cast:hover .tip, .buff:hover .tip { display: block; }
.horizontal .cast .tip { bottom: 34px; left: -8px; }
.horizontal .buff .tip { bottom: 22px; left: 0; }
.vertical  .cast .tip { left: 34px; top: -8px; }
.vertical  .buff .tip { left: 28px; top: 0; }
.tip .tname { color: #d97757; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.tip .ten { color: #a39c8e; font-style: italic; font-size: 10px; margin-bottom: 6px; }
.tip .tbody table { font-size: 11px; }
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
        self.set_empty("랭킹에서 캐릭터 클릭")

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
          document.addEventListener('mousemove', (e) => {
            if (!dragging) return;
            targetSx = dscX - (e.clientX - dsx);
            targetSy = dscY - (e.clientY - dsy);
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

        # ── 시전: lane 배정은 기본 pps 기준으로 (zoom 시 재계산 없음) ────────
        events_sorted: list[tuple[int, int, float, int]] = []
        for ev in cast_events:
            if len(ev) >= 3 and ev[2] != "cast":
                continue
            ts = int(ev[0]); sid = int(ev[1])
            t_rel = (ts - start_ms) / 1000.0
            if t_rel < 0:
                continue
            ms_in = int(round((t_rel - int(t_rel)) * 1000))
            events_sorted.append((ts, sid, t_rel, ms_in))
        events_sorted.sort()

        # lane 점유 — 기본 pps 기준 픽셀 충돌
        cast_lane_endtime: list[float] = []  # lane 별 다음 사용 가능 t_rel
        cast_items: list[tuple[int, int, float, int]] = []  # (sid, lane_row, t_rel, ms_in)
        for ts, sid, t_rel, ms_in in events_sorted:
            lane_i = 0
            while lane_i < len(cast_lane_endtime) and cast_lane_endtime[lane_i] > t_rel:
                lane_i += 1
            if lane_i == len(cast_lane_endtime):
                cast_lane_endtime.append(t_rel + ICON_TIME + 0.05)
            else:
                cast_lane_endtime[lane_i] = t_rel + ICON_TIME + 0.05
            cast_items.append((sid, lane_i, t_rel, ms_in))

        casts_lane_span = max(len(cast_lane_endtime), 1) * (ICON_PX + 4)

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
        for sid, row, t_rel, ms_in in cast_items:
            lane_pos = row * (ICON_PX + 4)
            cast_html.append(self._cast_html(sid, lane_pos, t_rel, ms_in, spell_db, is_v))

        buff_html: list[str] = []
        for sid, t_start, t_end in intervals:
            t_rel_start = max((t_start - start_ms) / 1000.0, 0)
            dur_s = (t_end - t_start) / 1000.0
            lane_pos = buff_lane.get(sid, 0) * BUFF_LANE_PX
            buff_html.append(self._buff_html(sid, lane_pos, t_rel_start, dur_s, spell_db, is_v))

        # tick — --t 만 박음 (CSS 가 px 변환)
        tick_html: list[str] = []
        for s in range(0, int(duration_s) + 1):
            is_major = (s % 5 == 0)
            cls = "tick pos-t major" if is_major else "tick pos-t"
            tick_html.append(f'<div class="{cls}" style="--t:{s}"></div>')
            label_cls = ("tick label pos-t major-label" if is_major
                         else "tick label pos-t")
            tick_html.append(f'<div class="{label_cls}" style="--t:{s}">{s}s</div>')

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
                    · 시전 {len(cast_items)}회 · 버프 인터벌 {len(intervals)}개
                    {f' (미상 {hidden_unknown_buffs}개 숨김)' if hidden_unknown_buffs else ''}
                    · 휠=줌 · 더블클릭=리셋</div>
                <div class="timeline span-d" style="{timeline_style}">
                    <div class="axis {axis_style} span-d">{"".join(tick_html)}</div>
                    <div class="casts lanes span-d" style="{casts_style};left:{casts_left}px">
                        {"".join(cast_html)}
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
                    · 시전 {len(cast_items)}회 · 버프 인터벌 {len(intervals)}개
                    {f' (미상 {hidden_unknown_buffs}개 숨김)' if hidden_unknown_buffs else ''}
                    · 휠=줌 · 더블클릭=리셋</div>
                <div class="timeline span-d" style="{timeline_style}">
                    <div class="axis {axis_style} span-d">{"".join(tick_html)}</div>
                    <span class="lane-label">시전</span>
                    <div class="casts span-d" style="{casts_style}">
                        {"".join(cast_html)}
                    </div>
                    <span class="lane-label">버프</span>
                    <div class="buffs span-d" style="{buffs_style}">
                        {"".join(buff_html)}
                    </div>
                </div>
            </div>
            '''
            body_class = "horizontal"
        self.setHtml(self._wrap(body, body_class))

    @staticmethod
    def _cast_html(sid: int, lane_pos: int, t_rel: float,
                   ms_in: int, spell_db: dict, is_v: bool) -> str:
        meta = spell_db.get(str(sid), {})
        icon = meta.get("icon") or ""
        tip_body = (meta.get("tooltip_ko") or meta.get("tooltip_en")
                    or meta.get("description_ko") or "")
        icon_url = (f"https://wow.zamimg.com/images/wow/icons/medium/{icon}"
                    if icon else "")
        title, sub = _resolve_name(sid, spell_db)
        time_str = f"t={t_rel:.3f}s (+{ms_in}ms)"
        if sub:
            subtitle = f'<div class="ten">{_html_escape(sub)} · {time_str}</div>'
        else:
            subtitle = f'<div class="ten">{time_str}</div>'
        # --t = 초 단위 시간 (CSS 가 px 변환), lane_pos = 픽셀 (고정)
        cross = f"left:{lane_pos}px" if is_v else f"top:{lane_pos}px"
        return (
            f'<div class="cast pos-t" style="--t:{t_rel:.4f};{cross}">'
            f'<img src="{icon_url}" alt="">'
            f'<div class="tip">'
            f'<div class="tname">{_html_escape(title)}</div>'
            f'{subtitle}'
            f'<div class="tbody">{tip_body}</div>'
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


def _make_spell_item(spell_id: int, label_text: str, spell_db: dict) -> QTableWidgetItem:
    """스펠 셀: 아이콘 + 한글/영문 + WoWhead 툴팁."""
    meta = spell_db.get(str(spell_id), {})
    item = QTableWidgetItem(label_text)
    item.setData(Qt.ItemDataRole.UserRole, spell_id)
    icon_file = meta.get("icon") or ""
    icon = _icon_for(icon_file) if icon_file else None
    if icon:
        item.setIcon(icon)
    if meta:
        item.setToolTip(_build_tooltip(meta))
    return item


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
.tnode:hover { transform: scale(1.12); z-index: 50; }
.tnode img { width: 100%; height: 100%; border-radius: 4px; display: block; }
.tnode.choice { border-radius: 50%; }
.tnode.choice img { border-radius: 50%; }

.tnode.t-essential {
    border-color: #d97757;
    box-shadow: 0 0 10px rgba(217, 119, 87, 0.45);
}
.tnode.t-common { border-color: #d97757; }
.tnode.t-split { border-color: #4a4039; }
.tnode.t-niche { opacity: 0.55; }
.tnode.t-zero { opacity: 0.22; }

/* 픽률 배지 — 우하단, 정수% */
.tnode .pct {
    position: absolute; bottom: -4px; right: -4px;
    background: rgba(10, 8, 6, 0.9); color: #f5f0e8;
    font-size: 9px; font-weight: 600;
    padding: 1px 4px; border-radius: 8px; min-width: 14px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.5);
}
.tnode.t-essential .pct { background: rgba(217, 119, 87, 0.9); }

/* 호버 툴팁 */
.tnode .tip {
    display: none; position: absolute; bottom: 48px; left: -8px;
    background: #15110f; border: 1px solid #3a322c; border-radius: 8px;
    padding: 10px 12px; min-width: 280px; max-width: 400px;
    z-index: 100; box-shadow: 0 8px 24px rgba(0,0,0,0.7);
    color: #f5f0e8; font-size: 11px; pointer-events: none;
}
.tnode:hover .tip { display: block; }
.tip .tname { color: #d97757; font-weight: 600; font-size: 12px; margin-bottom: 4px; letter-spacing: -0.01em; }
.tip .tdesc { color: #c4bdaf; line-height: 1.5; }

.empty {
    color: #a39c8e; text-align: center; padding: 64px 24px;
    background: #221d1a; border: 1px dashed #3a322c; border-radius: 12px; margin: 16px;
}
"""


def _tree_empty_html(msg: str = "보스 + 전문화 선택 시 트리 표시") -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{TREE_CSS}</style></head>"
            f"<body><div class='empty'>{_html_escape(msg)}</div></body></html>")


def _node_html(node: dict, pick_pct: float, spell_db: dict) -> str:
    """단일 노드 HTML — 위치 + 아이콘 + 픽률 배지 + 호버 툴팁."""
    if not node.get("options"):
        return ""
    opt = node["options"][0]
    spell_id = opt.get("spell_id")
    name = opt.get("name") or f"#{node.get('id')}"
    desc = opt.get("desc") or ""

    # 아이콘 — spell_db 에서 매핑 시도
    icon_file = ""
    if spell_id:
        meta = spell_db.get(str(spell_id), {})
        icon_file = meta.get("icon") or ""
    icon_url = (f"https://wow.zamimg.com/images/wow/icons/medium/{icon_file}"
                if icon_file else "")

    # 위치: display_col × 56px, display_row × 56px
    col = node.get("col") or 1
    row = node.get("row") or 1
    left = (col - 1) * 56 + 6
    top = (row - 1) * 56 + 6

    # 픽률 ramp — design spec 따름
    if pick_pct >= 85:
        cls = "t-essential"     # 핵심 패스 — 앰버 ring + glow
    elif pick_pct >= 50:
        cls = "t-common"        # 보편적 — 솔리드 앰버
    elif pick_pct >= 25:
        cls = "t-split"         # 분기 — 회색 ring
    elif pick_pct >= 5:
        cls = "t-niche"         # 소수 — ring 없음, 흐림
    else:
        cls = "t-zero"          # 거의 안 찍힘 — 거의 안 보임
    if node.get("type") == "CHOICE":
        cls += " choice"

    # 배지 — 5% 이상만 표시 (노이즈 제거)
    pct_html = ""
    if pick_pct >= 5:
        pct_html = f'<div class="pct">{int(round(pick_pct))}</div>'

    return (
        f'<div class="tnode {cls}" style="left:{left}px;top:{top}px">'
        f'<img src="{icon_url}" alt="">'
        f'{pct_html}'
        f'<div class="tip">'
        f'<div class="tname">{_html_escape(name)}</div>'
        f'<div class="tdesc">{_html_escape(desc)[:240]}</div>'
        f'</div></div>'
    )


def _build_tree_html(tree_data: dict, pick_count: dict, denom: int,
                     spell_db: dict, hero_filter: str | None = None) -> str:
    """class / spec / hero 트리 HTML."""
    if not tree_data:
        return _tree_empty_html("이 스펙은 아직 트리 데이터 없음 — fetch_talent_trees.py 실행 필요")

    def pct_of(node) -> float:
        # talent_id 매칭 (options[0].talent_id)
        if not node.get("options"):
            return 0
        opt = node["options"][0]
        tid = opt.get("talent_id")
        if tid is None:
            return 0
        return pick_count.get(int(tid), 0) / max(1, denom) * 100

    def col_size(nodes):
        if not nodes:
            return (300, 300)
        max_col = max((n.get("col") or 1) for n in nodes)
        max_row = max((n.get("row") or 1) for n in nodes)
        return (max_col * 56 + 60, max_row * 56 + 60)

    class_nodes = tree_data.get("class") or []
    spec_nodes = tree_data.get("spec") or []
    cw, ch = col_size(class_nodes)
    sw, sh = col_size(spec_nodes)

    class_html = "".join(_node_html(n, pct_of(n), spell_db) for n in class_nodes)
    spec_html = "".join(_node_html(n, pct_of(n), spell_db) for n in spec_nodes)

    # 영웅 트리: 사용자가 선택한 거 or 첫 번째
    hero_dict = tree_data.get("hero") or {}
    hero_html = ""
    hero_w, hero_h = 200, 600
    hero_name_display = ""
    if hero_dict:
        # 가장 픽률 높은 영웅 트리 자동 선택
        def avg_hero_pct(nodes):
            if not nodes:
                return 0
            return sum(pct_of(n) for n in nodes) / len(nodes)
        if hero_filter and hero_filter in hero_dict:
            chosen_name = hero_filter
        else:
            chosen_name = max(hero_dict.keys(), key=lambda hn: avg_hero_pct(hero_dict[hn].get("nodes") or []))
        hero_name_display = chosen_name
        hero_nodes = hero_dict[chosen_name].get("nodes") or []
        hw, hh = col_size(hero_nodes)
        hero_w, hero_h = hw, hh
        hero_html = "".join(_node_html(n, pct_of(n), spell_db) for n in hero_nodes)
    other_heroes = ", ".join(n for n in hero_dict.keys() if n != hero_name_display)
    hero_note = f" (다른 영웅트리: {other_heroes})" if other_heroes else ""

    body = f"""
    <div class='tree-wrap'>
      <div class='tree-row'>
        <div class='tree-col'>
          <h3>직업 특성</h3>
          <div class='tree-canvas' style='width:{cw}px;height:{ch}px'>{class_html}</div>
        </div>
        <div class='tree-col'>
          <h3>영웅 특성 — {_html_escape(hero_name_display)}{_html_escape(hero_note)}</h3>
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


# ─────────────────────────────────────────────────────────────────────────────
# 로딩 오버레이 — 무거운 click 작업 동안 위에 띄움

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

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.encounter_id: int | None = None
        self.encounter_name: str | None = None
        self.class_en: str | None = None
        self.spec_en: str | None = None
        self._current_df = None
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
        top_split.addWidget(vbox_panel("랭킹 (top 100)", self.ranking_table))

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

        top_split.setStretchFactor(0, 2)
        top_split.setStretchFactor(1, 1)
        main_split.addWidget(top_split)

        # ── 아래: 탭 (특성 / 딜사이클)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setDocumentMode(True)

        # 탭 1: 특성 분포 (상: 픽률 + 하: WoWhead 추천 빌드)
        self.talent_table = QTableWidget()
        self.talent_table.setColumnCount(4)
        self.talent_table.setHorizontalHeaderLabels(["트리", "특성", "선택률", "수"])
        self.talent_table.verticalHeader().setVisible(False)
        self.talent_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.talent_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.talent_table.setAlternatingRowColors(True)
        self.talent_table.setIconSize(QSize(24, 24))
        th = self.talent_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        # 비주얼 트리 (QWebEngineView)
        self.tree_view = QWebEngineView()
        self.tree_view.setMinimumHeight(420)
        self.tree_view.setHtml(_tree_empty_html())

        self.builds_table = QTableWidget()
        self.builds_table.setColumnCount(4)
        self.builds_table.setHorizontalHeaderLabels(["영웅특성", "시나리오", "BEST", "임포트 코드 (더블클릭 = 복사)"])
        self.builds_table.verticalHeader().setVisible(False)
        self.builds_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.builds_table.setAlternatingRowColors(True)
        bh = self.builds_table.horizontalHeader()
        bh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        bh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        bh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        bh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.builds_table.cellDoubleClicked.connect(self._copy_build_code)

        talent_wrap = QWidget()
        tw_v = QVBoxLayout(talent_wrap)
        tw_v.setContentsMargins(0, 0, 0, 0)
        tw_v.setSpacing(6)
        sp = QSplitter(Qt.Orientation.Vertical)
        sp.addWidget(vbox_panel("특성 트리 (top100 픽률 오버레이)", self.tree_view))
        # 표 형태는 보조 — 작게
        side_sp = QSplitter(Qt.Orientation.Horizontal)
        side_sp.addWidget(vbox_panel("픽률 표 (디버그/대체)", self.talent_table))
        side_sp.addWidget(vbox_panel("WoWhead 가이드 추천 빌드", self.builds_table))
        side_sp.setStretchFactor(0, 1)
        side_sp.setStretchFactor(1, 1)
        sp.addWidget(side_sp)
        sp.setStretchFactor(0, 4)
        sp.setStretchFactor(1, 2)
        tw_v.addWidget(sp, 1)
        self.detail_tabs.addTab(talent_wrap, "특성 분포")

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
        tw_layout.addWidget(self.rotation_timeline, 1)
        self.detail_tabs.addTab(timeline_wrap, "딜사이클")

        main_split.addWidget(self.detail_tabs)
        main_split.setStretchFactor(0, 1)
        main_split.setStretchFactor(1, 2)  # 탭 영역 더 크게

        self._orientation = "h"
        self._last_rotation_args: dict | None = None

        # 로딩 오버레이 — 전체 패널 위에
        self.loader = LoadingOverlay(self)

    # ── 필터 변경 ─────────────────────────────────────────────────────────
    def set_filter(self, encounter_id, encounter_name, class_en, spec_en) -> None:
        self.encounter_id = encounter_id
        self.encounter_name = encounter_name
        self.class_en = class_en
        self.spec_en = spec_en
        self._refresh()

    def _refresh(self) -> None:
        self.rotation_timeline.set_empty("랭킹에서 캐릭터 클릭")
        if not all([self.encounter_id, self.class_en, self.spec_en]):
            self.header.setText("← 보스와 전문화를 골라봐")
            self.ranking_table.setRowCount(0)
            self.spell_table.setRowCount(0)
            self.talent_table.setRowCount(0)
            self._current_df = None
            return

        self.loader.show_with("랭킹 / 시전 / 특성 불러오는 중…")
        try:
            rankings = _load_csv("rankings_with_talents.csv")
            if rankings is None:
                self.header.setText("data/rankings_with_talents.csv 를 못 찾음")
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
            self._populate_builds()
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

    # ── 딜 비중 TOP10 (top 20 합산, SQLite + V2 lazy fetch) ───────────────
    def _populate_top_damage(self, ranking_df) -> None:
        spell_db = _load_json("spell_db.json")
        sample = ranking_df.head(20)

        # source_id 조회 + 누락 damage 만 V2 lazy fetch
        need_fetch: list[tuple[str, int, str]] = []
        triples: list[tuple[str, int, int]] = []  # (rid, fid, sid) 도 보관
        for _, row in sample.iterrows():
            rid = str(row["report_id"])
            try:
                fid = int(row["fight_id"])
            except (TypeError, ValueError):
                continue
            char = str(row["character"])
            sid = db_source_id(rid, char)
            if sid is None:
                continue
            triples.append((rid, fid, sid))
            existing = db_damage(rid, fid, sid)
            if not existing:
                need_fetch.append((rid, fid, char))

        if need_fetch:
            try:
                from wcl_v2_data import V2Data
                self.loader.show_with(f"딜 비중 데이터 가져오는 중… ({len(need_fetch)}개)")
                v2 = V2Data()
                for rid, fid, char in need_fetch:
                    v2.damage_table(rid, fid, char)
                v2.flush()
                # 새로 받은 거 SQLite 에도 INSERT
                _ingest_v2_damage_to_db(v2.damage)
            except Exception as e:
                log.warning("damage lazy fetch err: %s", e)

        # 집계
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

        self.spell_table.setRowCount(len(rows))
        for i, (gid, info) in enumerate(rows):
            primary, sub = _resolve_name(gid, spell_db)
            # spell_db 에 없으면 V2 damage 의 영문명 사용
            if primary == f"미상 #{gid}" and info.get("name_en"):
                primary = info["name_en"]
            label = f"{primary}    ({sub})" if sub else primary
            self.spell_table.setItem(i, 0, _make_spell_item(gid, label, spell_db))
            pct = info["total"] / total_all * 100
            pct_item = _center_cell(f"{pct:5.1f}%")
            if pct >= 15:
                pct_item.setForeground(QColor("#d97757"))
            self.spell_table.setItem(i, 1, pct_item)
            self.spell_table.setItem(i, 2, _center_cell(f"{int(info['total']):>13,}"))

        log.info("top damage: chars_matched=%d unique_spells=%d shown=%d",
                 matched, len(agg), len(rows))

    # ── 특성 분포 (3-tree 분류 그룹핑) ────────────────────────────────────
    def _populate_talents(self, ranking_df) -> None:
        spell_db = _load_json("spell_db.json")
        tree_lut = _load_tree_lut()

        # SQL 한 방에 — 랭킹 캐릭터들의 talent_id 별 카운트
        triples: list[tuple[str, int, str]] = []
        for _, row in ranking_df.iterrows():
            rid = str(row["report_id"])
            try:
                fid = int(row["fight_id"])
            except (TypeError, ValueError):
                continue
            char = str(row["character"])
            triples.append((rid, fid, char))
        counts, matched = db_talent_counts_for_ranks(triples)
        if not counts:
            self.talent_table.setRowCount(0)
            return

        denom = max(matched, 1)
        cls, spec = self.class_en, self.spec_en

        # 한국 와우 UI 명칭 매핑: 공용 → 직업, 전문화 → 전문화, 영웅 → 영웅
        TREE_DISPLAY = {
            "공용":    "직업 특성",
            "전문화":  "전문화 특성",
            "영웅":    "영웅 특성",
            "spec?":   "전문화 특성",   # 단일 DPS 클래스는 비교 못해도 일단 전문화로 표시
            "미분류":  "기타",
        }
        TREE_ORDER = {
            "직업 특성":   0,
            "전문화 특성": 1,
            "영웅 특성":   2,
            "기타":        9,
        }
        TREE_COLOR = {
            "직업 특성":   QColor("#88c0d0"),
            "전문화 특성": QColor("#d97757"),
            "영웅 특성":   QColor("#b48ead"),
            "기타":        QColor("#6b6359"),
        }

        def tree_of(tid: int) -> str:
            raw = tree_lut.get((cls, spec, tid), "미분류")
            return TREE_DISPLAY.get(raw, "기타")

        # 미상 (영문/한글 둘 다 없는) 행은 일단 숨김 — WoWhead 데이터 한계
        meaningful = [(tid, cnt) for tid, cnt in counts.items()
                      if spell_db.get(str(tid), {}).get("name_ko") or
                         spell_db.get(str(tid), {}).get("name_en")]
        hidden_count = len(counts) - len(meaningful)

        rows_sorted = sorted(
            meaningful,
            key=lambda x: (TREE_ORDER.get(tree_of(x[0]), 9), -x[1], x[0]),
        )

        self.talent_table.setSortingEnabled(False)
        self.talent_table.setRowCount(len(rows_sorted))
        for i, (tid, cnt) in enumerate(rows_sorted):
            t = tree_of(tid)
            tree_item = _center_cell(t)
            tree_item.setForeground(TREE_COLOR.get(t, QColor("#f5f0e8")))
            self.talent_table.setItem(i, 0, tree_item)

            primary, sub = _resolve_name(tid, spell_db)
            label = f"{primary}    ({sub})" if sub else primary
            self.talent_table.setItem(i, 1, _make_spell_item(tid, label, spell_db))

            pct = cnt / denom * 100
            pct_item = _center_cell(f"{pct:5.1f}%")
            if pct >= 99.5:
                pct_item.setForeground(QColor("#6b6359"))
            elif pct < 60:
                pct_item.setForeground(QColor("#e07a5f"))
            self.talent_table.setItem(i, 2, pct_item)
            self.talent_table.setItem(i, 3, _center_cell(f"{cnt}/{denom}"))

        self.talent_table.setSortingEnabled(True)
        log.info("talents: chars=%d shown=%d hidden_unknown=%d",
                 matched, len(rows_sorted), hidden_count)

        # ── 비주얼 트리도 같이 갱신 ───────────────────────────────────────
        all_trees = _load_json("talent_trees.json")
        key = f"{self.class_en}/{self.spec_en}"
        tree_data = all_trees.get(key)
        if tree_data and counts:
            tree_html = _build_tree_html(tree_data, counts, denom, spell_db)
        else:
            tree_html = _tree_empty_html(
                f"{key} 트리 데이터 없음 — fetch_talent_trees.py 의 SPECS 에 추가 필요"
            )
        self.tree_view.setHtml(tree_html)

    # ── WoWhead 추천 빌드 ─────────────────────────────────────────────────
    def _populate_builds(self) -> None:
        all_builds = _load_json("wowhead_builds.json")
        key = f"{self.class_en}/{self.spec_en}"
        builds = all_builds.get(key) or []
        self.builds_table.setRowCount(len(builds))

        # 영웅특성 코드 → 한글 매핑 (간단)
        HERO_KR = {
            "pack-leader": "무리의 우두머리", "dark-ranger": "어둠 순찰자",
            "diabolist": "지옥술사", "soul-harvester": "영혼 수확자",
            "hellcaller": "지옥소환사",
            "keeper-of-the-grove": "수풀의 수호자", "elunes-chosen": "엘룬의 선택받은 자",
            "wildstalker": "야생추적자", "druid-of-the-claw": "발톱의 드루이드",
            "slayer": "학살자", "colossus": "거신",
            "mountain-thane": "산왕",
        }

        for i, b in enumerate(builds):
            hero = b.get("hero") or "?"
            hero_kr = HERO_KR.get(hero, hero)
            scenario = b.get("scenario") or "?"
            is_best = b.get("is_best", False)
            code = b.get("code") or ""

            self.builds_table.setItem(i, 0, _center_cell(hero_kr))
            self.builds_table.setItem(i, 1, _center_cell(scenario))
            best_item = _center_cell("★" if is_best else "")
            if is_best:
                best_item.setForeground(QColor("#d97757"))
            self.builds_table.setItem(i, 2, best_item)
            code_item = QTableWidgetItem(code)
            code_item.setForeground(QColor("#a39c8e"))
            code_item.setData(Qt.ItemDataRole.UserRole, code)
            code_item.setToolTip("더블클릭 시 클립보드에 복사")
            self.builds_table.setItem(i, 3, code_item)

        log.info("wowhead builds: spec=%s count=%d", key, len(builds))

    def _copy_build_code(self, row: int, _col: int) -> None:
        item = self.builds_table.item(row, 3)
        if not item:
            return
        code = item.data(Qt.ItemDataRole.UserRole) or item.text()
        QApplication.clipboard().setText(code)
        log.info("clipboard copied: %s...", code[:50])
        # 헤더 임시 알림 (간단)
        scn = self.builds_table.item(row, 1).text() if self.builds_table.item(row, 1) else ""
        self.header.setText(self.header.text() + f"   ✓ [{scn}] 코드 복사됨")

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

        # SQLite 사용 — 8~30MB JSON 안 읽음
        self.loader.show_with(f"{char} 의 시전·버프 불러오는 중…")
        try:
            spell_db = _load_json("spell_db.json")  # 작음 (3MB), 메모리 캐시
            sid = db_source_id(rid, char)
            if sid is None:
                self.rotation_timeline.set_empty("이 캐릭의 source ID 매핑 없음")
                return
            cast_events = db_casts(rid, fid, sid)
            buff_events = db_buffs(rid, fid, sid)
            fight_window = db_fight_window(rid, fid)
            if not fight_window:
                self.rotation_timeline.set_empty("fight 윈도우 데이터 없음")
                return

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

    def __init__(self, difficulty_label: str, has_data: bool, parent=None) -> None:
        super().__init__(parent)
        self.difficulty_label = difficulty_label
        self.has_data = has_data
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
            self.panel = RankingPanel()
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WoW 한밤 레이드 로그 분석기")
        self.resize(2200, 1280)
        self.setMinimumSize(1400, 860)
        # 작업표시줄 제외하고 화면에 들어가면 maximize 도 OK
        self.showMaximized()

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(RaidTab("영웅", has_data=False), "영웅 레이드")
        tabs.addTab(RaidTab("신화", has_data=True),  "신화 레이드")
        tabs.setCurrentIndex(1)
        tabs.currentChanged.connect(lambda i: log.info("tab change: %s", tabs.tabText(i)))

        container = QFrame()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(tabs)
        self.setCentralWidget(container)
        log.info("MainWindow ready")


def main() -> None:
    log.info("QApplication start")
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    apply_dark_palette(app)
    win = MainWindow()
    win.show()
    log.info("event loop enter")
    rc = app.exec()
    log.info("exit code=%d", rc)
    sys.exit(rc)


if __name__ == "__main__":
    main()
