"""GUI 테마 정의 (4종).

각 테마 = 컬러 + 폰트 + 추가 QSS. build_qss(theme) 가 완성된 QSS 문자열을 만든다.
gui.py 는 이 모듈만 import 하고 Qt 통합은 직접 함 (이 파일은 Qt 비의존).
"""
from __future__ import annotations

from dataclasses import dataclass, field


def _hex_to_rgba(hex_color: str, alpha: int) -> str:
    """'#d97757', 45 -> 'rgba(217, 119, 87, 45)'."""
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


@dataclass(frozen=True)
class Theme:
    id: str
    name_kr: str
    # 컬러
    bg: str               # 메인 윈도우
    surface: str          # 패널/테이블 배경
    surface_alt: str      # zebra alt row, hover
    surface_raised: str   # 카드/raised 패널 (Hearthstone 등)
    border: str           # 1px hairline
    border_strong: str    # 버튼/강조 테두리
    text: str             # primary
    text_muted: str       # secondary
    accent: str           # 주 액센트
    accent_alt: str       # 보조 액센트 (gold/red 등)
    # 폰트
    body_font_css: str = "'Pretendard Variable', 'Pretendard', 'Segoe UI', sans-serif"
    header_font_css: str = "'Pretendard Variable', 'Pretendard', 'Segoe UI', sans-serif"
    # 사이즈/여백 톤
    pageheader_pt: float = 13.0
    section_pt: float = 9.5
    body_pt: float = 10.0
    panel_radius: int = 10
    panel_border_px: int = 1
    # 테마별 추가 룰
    extra_qss: str = ""


# ── 1) Claude × WoW 하이브리드 (기본/추천) ───────────────────────────────────
CLAUDE_WOW = Theme(
    id="claude_wow",
    name_kr="Claude × WoW 하이브리드",
    bg="#1a1614",
    surface="#221d1a",
    surface_alt="#1f1a17",
    surface_raised="#28221e",
    border="#2c2521",
    border_strong="#3a322c",
    text="#f5f0e8",
    text_muted="#a39c8e",
    accent="#d97757",      # Claude 오렌지
    accent_alt="#c8a560",  # 전설 골드 (보스 헤더용)
    header_font_css="'Cambria', 'Georgia', 'Pretendard Variable', serif",
    pageheader_pt=15.0,
    extra_qss="""
/* 페이지 헤더에 골드 underline 추가 (하이브리드 시그니처) */
QLabel#pageHeader {
    border-bottom: 1px solid #c8a560;
}
""",
)


# ── 2) Claude Design 정제판 ──────────────────────────────────────────────────
CLAUDE_REFINED = Theme(
    id="claude_refined",
    name_kr="Claude Design 정제",
    bg="#1a1614",
    surface="#221d1a",
    surface_alt="#1f1a17",
    surface_raised="#28221e",
    border="#2c2521",
    border_strong="#3a322c",
    text="#f5f0e8",
    text_muted="#a39c8e",
    accent="#d97757",
    accent_alt="#a39c8e",  # neutral — 액센트 alt 도 절제
    header_font_css="'Cambria', 'Constantia', 'Georgia', 'Pretendard Variable', serif",
    body_font_css="'Inter', 'Pretendard Variable', 'Segoe UI', sans-serif",
    pageheader_pt=16.0,
    section_pt=9.0,
    body_pt=10.5,
    panel_radius=8,
    extra_qss="""
/* 더 큰 여백 — editorial 톤 */
QLabel#pageHeader {
    padding: 14px 20px;
    letter-spacing: -0.02em;
}
QLabel#section {
    padding: 10px 6px;
    margin-bottom: 8px;
}
QTableWidget::item { padding: 10px 10px; }
QHeaderView::section { padding: 10px 14px; }
QListWidget::item, QTreeWidget::item { padding: 10px 10px 10px 14px; }
""",
)


# ── 3) WoW Heroic 전면 ───────────────────────────────────────────────────────
WOW_HEROIC = Theme(
    id="wow_heroic",
    name_kr="WoW Heroic",
    bg="#0d0a06",                # 거의 검정, 따뜻한 골드 언더톤
    surface="#1a130a",           # 다크 우드/패치먼트 뒷면
    surface_alt="#241a0d",
    surface_raised="#2d220f",
    border="#4d3a1f",            # 다크 골드
    border_strong="#7a5d2f",     # 골드 강조
    text="#f3e7c8",              # 파치먼트 크림
    text_muted="#a89070",        # 브론즈
    accent="#c8a560",            # 골드
    accent_alt="#ff8000",        # Heroic 주황 (BoA 색)
    header_font_css="'Cambria', 'Constantia', 'IM Fell English', 'Georgia', serif",
    body_font_css="'Pretendard Variable', 'Segoe UI', sans-serif",
    pageheader_pt=17.0,
    panel_radius=4,              # 더 각진 — 옛 UI 톤
    panel_border_px=2,
    extra_qss="""
/* 페이지 헤더: 골드 underline, 큼직, 자간 */
QLabel#pageHeader {
    color: #c8a560;
    font-weight: 700;
    letter-spacing: 0.02em;
    border-bottom: 2px solid #4d3a1f;
    padding: 12px 16px;
}
/* 섹션 헤더: 골드 컬러 */
QLabel#section {
    color: #c8a560;
    font-weight: 600;
    letter-spacing: 0.08em;
}
/* 테이블 헤더 골드 */
QHeaderView::section {
    color: #c8a560;
    border-bottom: 2px solid #4d3a1f;
    background-color: #14100a;
}
/* 탭 선택 시 골드 */
QTabBar::tab:selected { color: #c8a560; border-bottom: 3px solid #c8a560; }
QTabBar::tab:hover:!selected { color: #f3e7c8; border-bottom: 3px solid #4d3a1f; }
/* 패널 외곽 골드 hairline */
QListWidget, QTreeWidget, QTableWidget {
    border: 1px solid #4d3a1f;
}
""",
)


# ── 4) Hearthstone Tavern ────────────────────────────────────────────────────
HEARTHSTONE = Theme(
    id="hearthstone_tavern",
    name_kr="Hearthstone Tavern",
    bg="#241308",                # 진한 우드
    surface="#3d2817",           # 우드 패널
    surface_alt="#4a3220",       # 밝은 우드 (zebra)
    surface_raised="#523b28",    # 카드 raised
    border="#5d4632",            # worn wood
    border_strong="#8a6b3c",     # 브래스
    text="#ede4d0",              # 파치먼트
    text_muted="#b8a888",        # 크림-브론즈
    accent="#c8923d",            # 브래스
    accent_alt="#a83232",        # 명대 적동 (배너)
    header_font_css="'Cambria', 'Georgia', 'Constantia', serif",
    body_font_css="'Pretendard Variable', 'Segoe UI', sans-serif",
    pageheader_pt=18.0,
    body_pt=10.5,
    panel_radius=12,             # 카드 라운드
    panel_border_px=2,
    extra_qss="""
/* 우드 텍스처 비슷한 세로 그라디언트 (텍스처 이미지 없이) */
QWidget {
    background-color: #241308;
}
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #2d1a0e, stop:1 #1a0e07);
}
/* 페이지 헤더 — 브래스 banner 톤 */
QLabel#pageHeader {
    color: #c8923d;
    font-weight: 800;
    font-size: 18pt;
    letter-spacing: 0.01em;
    padding: 14px 20px;
    background-color: #2d1a0e;
    border: 2px solid #8a6b3c;
    border-radius: 8px;
}
/* 섹션 헤더 브래스 */
QLabel#section {
    color: #c8923d;
    font-weight: 700;
}
/* 패널 = 카드 (2px border + raised 느낌) */
QListWidget, QTreeWidget, QTableWidget {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #4a3220, stop:1 #3d2817);
    border: 2px solid #5d4632;
    border-radius: 12px;
}
QTableWidget::item:selected {
    background-color: rgba(200, 146, 61, 80);
    color: #ffffff;
}
QHeaderView::section {
    color: #c8923d;
    background-color: #2d1a0e;
    border-bottom: 2px solid #8a6b3c;
    font-weight: 700;
}
/* 버튼: 브래스 raised */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #523b28, stop:1 #3d2817);
    border: 2px solid #5d4632;
    color: #ede4d0;
    font-weight: 600;
    padding: 9px 18px;
}
QPushButton:hover {
    border-color: #c8923d;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #5e4530, stop:1 #4a3220);
}
QPushButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #d9a04a, stop:1 #a87330);
    color: #1a0e07;
    border-color: #8a6b3c;
}
/* 탭 — 두꺼운 브래스 선 */
QTabBar::tab:selected { color: #c8923d; border-bottom: 3px solid #c8923d; }
QTabBar::tab:hover:!selected { color: #ede4d0; border-bottom: 3px solid #5d4632; }
""",
)


THEMES: dict[str, Theme] = {
    t.id: t for t in [CLAUDE_WOW, CLAUDE_REFINED, WOW_HEROIC, HEARTHSTONE]
}
DEFAULT_THEME_ID = "claude_wow"


def build_qss(t: Theme) -> str:
    """테마 -> 완성된 QSS 문자열."""
    sel_45 = _hex_to_rgba(t.accent, 45)
    sel_70 = _hex_to_rgba(t.accent, 70)
    sel_60 = _hex_to_rgba(t.accent, 60)
    sel_50 = _hex_to_rgba(t.accent, 50)

    return f"""
/* === Theme: {t.name_kr} ({t.id}) ============================================ */

QWidget {{
    background-color: {t.bg};
    color: {t.text};
    font-family: {t.body_font_css};
    font-size: {t.body_pt}pt;
}}
QMainWindow {{ background-color: {t.bg}; border: none; }}
QTabWidget::pane {{ background-color: {t.bg}; border: none; border-top: 1px solid {t.border}; }}

/* 패널 헤더 */
QLabel#section {{
    color: {t.text_muted};
    font-size: {t.section_pt}pt;
    font-weight: 500;
    padding: 8px 4px;
    margin-bottom: 4px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}}
/* 페이지 헤더 */
QLabel#pageHeader {{
    color: {t.text};
    font-size: {t.pageheader_pt}pt;
    font-weight: 600;
    font-family: {t.header_font_css};
    padding: 8px 16px;
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {t.border};
    letter-spacing: -0.015em;
}}
QLabel#placeholder {{
    color: {t.text_muted};
    font-size: 10.5pt;
    padding: 40px 24px;
    background-color: {t.surface};
    border: 1px dashed {t.border_strong};
    border-radius: 12px;
}}

/* Lists / Trees */
QListWidget, QTreeWidget {{
    background-color: {t.surface};
    border: {t.panel_border_px}px solid {t.border};
    border-radius: {t.panel_radius}px;
    padding: 6px;
    outline: none;
    /* Palette Highlight 거친 직사각형 비활성화 — QSS 로 부드럽게 그림 */
    selection-background-color: transparent;
    selection-color: {t.accent};
}}
QListWidget::item, QTreeWidget::item {{
    padding: 6px 12px;
    border-radius: 6px;
    margin: 2px 4px;
    color: {t.text};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {t.surface_alt};
    color: {t.text};
}}
QListWidget::item:selected, QTreeWidget::item:selected,
QListWidget::item:selected:active, QTreeWidget::item:selected:active {{
    background-color: {sel_45};
    color: {t.accent};
    font-weight: 600;
}}
QListWidget::item:selected:!active, QTreeWidget::item:selected:!active {{
    background-color: {sel_45};
    color: {t.accent};
}}
QTreeWidget::branch {{ background-color: transparent; }}
QTreeWidget::branch:selected {{ background-color: transparent; }}

/* Tabs */
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background-color: transparent;
    color: {t.text_muted};
    padding: 11px 26px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
    font-size: 10.5pt;
}}
QTabBar::tab:selected {{ color: {t.accent}; border-bottom: 2px solid {t.accent}; }}
QTabBar::tab:hover:!selected {{ color: {t.text}; border-bottom: 2px solid {t.border_strong}; }}

/* Buttons */
QPushButton {{
    background-color: {t.surface_alt};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
}}
QPushButton:hover {{ background-color: {t.surface_raised}; border-color: {t.accent}; }}
QPushButton:pressed {{ background-color: {t.surface_raised}; }}
QPushButton:checked {{
    background-color: {t.accent};
    color: {t.bg};
    border-color: {t.accent};
    font-weight: 600;
}}

/* Tables */
QTableWidget {{
    background-color: {t.surface};
    border: {t.panel_border_px}px solid {t.border};
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: {sel_50};
    selection-color: #ffffff;
}}
QTableWidget::item {{ padding: 8px 8px; border-bottom: 1px solid {t.surface_alt}; }}
QTableWidget::item:hover {{ background-color: {t.surface_alt}; }}
QTableWidget::item:selected {{
    background-color: {sel_60};
    color: #ffffff;
}}
QHeaderView::section {{
    background-color: {t.surface};
    color: {t.text_muted};
    padding: 8px 12px;
    border: none;
    border-bottom: 1px solid {t.border};
    font-weight: 500;
    font-size: {t.section_pt}pt;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}}
QHeaderView::section:last {{ border-right: none; }}

/* Splitters */
QSplitter::handle {{ background-color: {t.border}; }}
QSplitter::handle:hover {{ background-color: {t.border_strong}; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}

/* Scrollbars */
QScrollBar:vertical {{
    background-color: {t.surface};
    width: 12px;
    border: none;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background-color: {t.border_strong};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {t.accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; width: 0; }}
QScrollBar:horizontal {{
    background-color: {t.surface};
    height: 12px;
    border: none;
    margin: 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background-color: {t.border_strong};
    border-radius: 4px;
    min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {t.accent}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ height: 0; width: 0; }}

/* Tooltips */
QToolTip {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 10pt;
}}

/* MenuBar */
QMenuBar {{
    background-color: {t.bg};
    color: {t.text_muted};
    border-bottom: 1px solid {t.border};
    padding: 2px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 12px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{ color: {t.accent}; background-color: {t.surface_alt}; }}
QMenu {{
    background-color: {t.surface};
    color: {t.text};
    border: 1px solid {t.border_strong};
    padding: 4px 0;
}}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{ background-color: {sel_45}; color: #ffffff; }}
QMenu::item:checked {{ color: {t.accent}; font-weight: 600; }}

{t.extra_qss}
"""
