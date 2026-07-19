"""모던 UI 테마 (라이트/다크) — 둥근 모서리, 부드러운 색, 넉넉한 여백.

배달의민족류 최신 앱 스타일: 밝은 배경 + 민트 포인트 + 카드형 표면.
"""

_LIGHT = {
    "BG": "#F4F6F8",           # 앱 배경
    "SURFACE": "#FFFFFF",      # 카드/입력 표면
    "SURFACE2": "#EBEFF3",     # 보조 표면 (hover 등)
    "BORDER": "#E1E6EA",
    "TEXT": "#1E232B",
    "SUB": "#69737E",
    "ACCENT": "#2AC1BC",       # 민트 포인트
    "ACCENT_SOFT": "#E2F6F5",  # 민트 연한 배경
    "HANDLE": "#C9D2D9",       # 스크롤바
}

_DARK = {
    "BG": "#17191D",
    "SURFACE": "#1E2126",
    "SURFACE2": "#262A31",
    "BORDER": "#33383F",
    "TEXT": "#E7EAEE",
    "SUB": "#97A1AB",
    "ACCENT": "#2AC1BC",
    "ACCENT_SOFT": "#1D3A38",
    "HANDLE": "#3D434B",
}

_QSS = """
* { outline: none; }
QMainWindow, QDialog { background: @BG; }
QWidget { color: @TEXT; font-family: "맑은 고딕"; font-size: 10pt; }
QLabel { background: transparent; }

QTabWidget::pane { border: 1px solid @BORDER; border-radius: 10px;
                   background: @SURFACE; }
QTabBar::tab { background: transparent; color: @SUB; padding: 6px 16px;
               margin: 2px 3px; border-radius: 8px; }
QTabBar::tab:selected { background: @SURFACE; color: @ACCENT;
                        font-weight: bold; border: 1px solid @BORDER; }
QTabBar::tab:hover:!selected { background: @SURFACE2; }

QPushButton { background: @SURFACE; color: @TEXT;
              border: 1px solid @BORDER; border-radius: 8px;
              padding: 6px 12px; }
/* hover: 살짝 눌리는 느낌 (전체 높이는 유지한 채 내용만 1px 아래로) */
QPushButton:hover { background: @ACCENT_SOFT; border-color: @ACCENT;
                    padding-top: 7px; padding-bottom: 5px; }
QPushButton:pressed { background: @SURFACE2;
                      padding-top: 8px; padding-bottom: 4px; }
QPushButton:disabled { color: @SUB; background: @SURFACE2;
                       padding: 6px 12px; }

/* 주요 동작 버튼 (가져오기/등록 등): 민트 채움 */
QPushButton#primaryBtn { background: @ACCENT; color: white;
                         border: none; font-weight: bold; }
QPushButton#primaryBtn:hover { background: @ACCENT;
                               padding-top: 7px; padding-bottom: 5px; }
QPushButton#primaryBtn:pressed { padding-top: 8px; padding-bottom: 4px; }

QToolButton { background: transparent; border: none; border-radius: 6px;
              padding: 2px; }
QToolButton:hover { background: @SURFACE2; }

QTextEdit, QPlainTextEdit, QLineEdit, QSpinBox, QComboBox {
    background: @SURFACE; color: @TEXT; border: 1px solid @BORDER;
    border-radius: 8px; padding: 4px 8px;
    selection-background-color: @ACCENT; selection-color: white; }
QTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 2px solid @ACCENT; }

QListWidget { background: @SURFACE; border: 1px solid @BORDER;
              border-radius: 8px; padding: 3px; }
QListWidget::item { border-radius: 6px; padding: 3px 6px; }
QListWidget::item:selected { background: @ACCENT_SOFT; color: @TEXT; }
QListWidget::item:hover { background: @SURFACE2; }

QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: @SURFACE; color: @TEXT;
    border: 1px solid @BORDER; border-radius: 8px;
    selection-background-color: @ACCENT_SOFT; selection-color: @TEXT; }

QGroupBox { border: 1px solid @BORDER; border-radius: 10px;
            margin-top: 10px; background: @SURFACE; padding-top: 4px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px;
                   color: @ACCENT; font-weight: bold;
                   background: transparent; }

QMenuBar { background: @BG; color: @TEXT; padding: 2px 4px; }
QMenuBar::item { padding: 5px 10px; border-radius: 6px;
                 background: transparent; }
QMenuBar::item:selected { background: @ACCENT_SOFT; color: @TEXT; }
QMenu { background: @SURFACE; color: @TEXT; border: 1px solid @BORDER;
        border-radius: 10px; padding: 6px; }
QMenu::item { padding: 6px 26px 6px 12px; border-radius: 6px; }
QMenu::item:selected { background: @ACCENT_SOFT; }
QMenu::separator { height: 1px; background: @BORDER; margin: 5px 8px; }

QStatusBar { background: @BG; color: @SUB; }
QToolBar { background: @BG; border: none; padding: 3px; spacing: 4px; }
QDockWidget { color: @TEXT; }
QDockWidget::title { background: @SURFACE2; padding: 6px 10px;
                     border-radius: 8px; }
QSplitter::handle { background: @BG; }
QSplitter::handle:hover { background: @ACCENT_SOFT; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: @HANDLE; border-radius: 4px;
                              min-height: 30px; }
QScrollBar::handle:vertical:hover { background: @SUB; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: @HANDLE; border-radius: 4px;
                                min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: @SUB; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px;
                       border: 2px solid @BORDER; background: @SURFACE; }
QCheckBox::indicator:hover { border-color: @ACCENT; }
QCheckBox::indicator:checked { background: @ACCENT; border-color: @ACCENT; }

QProgressDialog { background: @SURFACE; }
QProgressBar { border: 1px solid @BORDER; border-radius: 8px;
               background: @SURFACE2; text-align: center; color: @TEXT; }
QProgressBar::chunk { background: @ACCENT; border-radius: 7px; }

QToolTip { background: #2A2E35; color: #F0F2F4; border: none;
           border-radius: 6px; padding: 6px 8px; }
QMessageBox { background: @SURFACE; }
QHeaderView::section { background: @SURFACE2; color: @SUB; border: none;
                       padding: 4px; }
"""


def build_style(dark: bool) -> str:
    tokens = _DARK if dark else _LIGHT
    qss = _QSS
    # 긴 키부터 치환 (@ACCENT_SOFT가 @ACCENT보다 먼저)
    for key in sorted(tokens, key=len, reverse=True):
        qss = qss.replace("@" + key, tokens[key])
    return qss
