"""붙여넣은 명세서를 '텍스트 그대로' 보여주는 뷰어 탭.

PDF 렌더링이 아니라 실제 텍스트 위젯이므로 글자 간격이 벌어지지 않고
복사도 된다. 선택 영역은 문자 오프셋(rect = [start, end, 0, 0])으로
매핑에 저장되므로, 다시 열었을 때 매핑된 구간을 그대로 표시할 수 있다.
"""
import re

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import (QColor, QFont, QIcon, QPixmap, QTextCharFormat,
                         QTextCursor)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QTextEdit, QMessageBox, QMenu
)

from core.project import MappingEntry
from core.text_doc import doc_title, load_text_doc
from utils.term_format import term_texts

# 문장 끝 후보: 마침표/물음표/느낌표 뒤 공백(또는 끝)
_SENT_END = re.compile(r"[.!?](?=\s|$)")
# 문장 끝으로 보지 않는 약어 (Fig. 7 / No. 2 / U.S. Pat.)
_ABBREV = re.compile(
    r"(?:\b(?:Fig|FIG|No|Nos|Pat|Ser|Vol|Ref|Inc|Ltd|Co|Corp|et al|e\.g|i\.e"
    r"|U\.S|Dr|Mr|Ms|approx|cf|vs)\.?|\b[A-Z])$")


def _is_sentence_end(text: str, pos: int) -> bool:
    """text[pos]가 진짜 문장 끝인지 (약어 마침표 제외)."""
    return not _ABBREV.search(text[max(0, pos - 12):pos])


def _sent_ends(text: str, from_pos: int = 0, to_pos: int = None):
    for m in _SENT_END.finditer(text, from_pos,
                                len(text) if to_pos is None else to_pos):
        if _is_sentence_end(text, m.start()):
            yield m


def _sentence_bounds(text: str, start: int, end: int) -> tuple:
    """선택 구간을 포함하는 문장 전체로 확장."""
    left = 0
    for m in _sent_ends(text, 0, start):
        left = m.end()
    right = len(text)
    for m in _sent_ends(text, max(end - 1, 0)):
        right = m.end()
        break
    # 문단 경계를 넘지 않도록
    para = text.rfind("\n\n", 0, start)
    if para != -1 and para + 2 > left:
        left = para + 2
    para_end = text.find("\n\n", end)
    if para_end != -1 and para_end < right:
        right = para_end
    while left < len(text) and text[left] in " \t\n":
        left += 1
    return left, max(right, left)


class TextDocumentViewer(QWidget):
    """텍스트 문서(.txt) 탭 — PDF 뷰어와 같은 시그널 인터페이스를 갖는다."""
    mapping_requested = pyqtSignal(str, int, list, str)
    alias_requested = pyqtSignal(str, str)

    SEARCH_COLORS = [
        (255, 235, 59), (129, 199, 132), (79, 195, 247), (244, 143, 177),
        (255, 183, 77), (179, 157, 219), (128, 222, 234), (197, 225, 165),
    ]

    def __init__(self, doc_path: str, parent=None):
        super().__init__(parent)
        self.doc_path = doc_path
        self._text = load_text_doc(doc_path)
        self._terms: list = []
        self._mappings: list = []
        self._elem_colors: dict = {}
        self._term_colors: dict = {}
        self._search_hits: list = []      # [(start, end, kw_idx)]
        self._search_kws: list = []
        self._search_idx = -1
        self._last_query = ""
        self._setup_ui()

    # ------------------------------------------------------------ UI

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        bar = QHBoxLayout()
        bar.setSpacing(4)

        bar.addWidget(QLabel("선택:"))
        self.snap_combo = QComboBox()
        self.snap_combo.addItem("문장 단위", "sentence")
        self.snap_combo.addItem("드래그 그대로", "none")
        self.snap_combo.setFixedWidth(120)
        self.snap_combo.setToolTip(
            "문장 단위: 문장 일부만 선택해도 문장 전체를 가져옵니다\n"
            "드래그 그대로: 선택한 범위만 가져옵니다")
        bar.addWidget(self.snap_combo)

        self.map_btn = QPushButton("선택 영역 매핑")
        self.map_btn.setToolTip("선택한 문장을 청구항 구성요소와 연결합니다")
        self.map_btn.clicked.connect(self._map_selection)
        bar.addWidget(self.map_btn)

        bar.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("키워드 검색 (쉼표로 여러 개)")
        self.search_input.setMinimumWidth(180)
        self.search_input.setMaximumWidth(260)
        self.search_input.setToolTip(
            "여러 키워드는 쉼표(,)로 구분합니다.\n"
            "등록된 용어는 'host material'처럼 여러 단어여도\n"
            "한 덩어리로 검색됩니다.\n"
            "Enter/▼: 다음 결과, ▲: 이전 결과")
        self.search_input.returnPressed.connect(self._search_or_next)
        search_btn = QPushButton("검색")
        search_btn.setFixedWidth(58)
        search_btn.clicked.connect(self._search_or_next)
        prev_btn = QPushButton("▲")
        prev_btn.setFixedWidth(42)
        prev_btn.clicked.connect(lambda: self._goto_hit(-1))
        next_btn = QPushButton("▼")
        next_btn.setFixedWidth(42)
        next_btn.clicked.connect(lambda: self._goto_hit(1))
        self.hit_label = QLabel("")
        self.hit_label.setStyleSheet("color: #69737E; min-width: 52px;")
        self.hit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.term_btn = QPushButton("용어 색")
        self.term_btn.setFixedWidth(64)
        self.term_btn.setToolTip(
            "검색한 단어를 청구항 용어의 '선행문헌 표기'로 등록합니다.\n"
            "등록하면 그 단어가 용어와 같은 색으로 표시됩니다.")
        self.term_btn.clicked.connect(self._show_term_menu)
        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(42)
        clear_btn.setToolTip("검색 지우기")
        clear_btn.clicked.connect(self._clear_search)
        for w in (self.search_input, search_btn, prev_btn, next_btn,
                  self.hit_label, self.term_btn, clear_btn):
            bar.addWidget(w)
        layout.addLayout(bar)

        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        font = QFont("맑은 고딕", 11)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        self.editor.setFont(font)
        self.editor.setStyleSheet(
            "QTextEdit { background: #FFFFFF; padding: 18px 22px; "
            "line-height: 160%; }")
        self.editor.setPlainText(self._text)
        self.editor.selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.editor, stretch=1)

    # ------------------------------------------------------- 선택 → 매핑

    def _on_selection_changed(self):
        c = self.editor.textCursor()
        self.map_btn.setEnabled(c.hasSelection())

    def _selected_range(self) -> tuple:
        c = self.editor.textCursor()
        if not c.hasSelection():
            return (0, 0)
        start, end = c.selectionStart(), c.selectionEnd()
        if self.snap_combo.currentData() == "sentence":
            start, end = _sentence_bounds(self._text, start, end)
        return start, end

    def _map_selection(self):
        start, end = self._selected_range()
        text = self._text[start:end].strip()
        if len(text) < 2:
            QMessageBox.information(
                self, "알림", "매핑할 문장을 먼저 선택해 주세요.")
            return
        # rect 자리에 문자 오프셋을 저장 (도면 캡처는 없음)
        self.mapping_requested.emit(
            self.doc_path, 0, [start, end, 0, 0], text)

    # ------------------------------------------------------------ 검색

    def _parse_keywords(self, query: str) -> list:
        """등록된 여러 단어 용어는 한 덩어리로 유지한다.

        'host material'은 두 단어가 합쳐져 하나의 구성요소이므로
        host / material로 쪼개 검색하면 안 된다.
        """
        return parse_keywords(query, self._terms)

    def _search_or_next(self):
        query = self.search_input.text().strip()
        if not query:
            self._clear_search()
            return
        if query != self._last_query:
            self._run_search(query)
        else:
            self._goto_hit(1)

    def _run_search(self, query: str):
        self._last_query = query
        self._search_hits = []
        self._search_idx = -1
        self._search_kws = self._parse_keywords(query)
        low = self._text.lower()
        for ki, kw in enumerate(self._search_kws):
            k = kw.lower()
            if not k:
                continue
            pos = low.find(k)
            while pos != -1:
                self._search_hits.append((pos, pos + len(kw), ki))
                pos = low.find(k, pos + len(k))
        self._search_hits.sort()
        if self._search_hits:
            self._goto_hit(1)
        else:
            self._refresh_display()

    def _goto_hit(self, delta: int):
        if not self._search_hits:
            return
        self._search_idx = (self._search_idx + delta) % len(self._search_hits)
        start, _end, _ki = self._search_hits[self._search_idx]
        c = self.editor.textCursor()
        c.setPosition(start)
        self.editor.setTextCursor(c)
        self.editor.ensureCursorVisible()
        self._refresh_display()

    def _clear_search(self):
        self.search_input.clear()
        self._search_hits = []
        self._search_kws = []
        self._search_idx = -1
        self._last_query = ""
        self.hit_label.setText("")
        self._refresh_display()

    def _term_for_keyword(self, kw: str):
        low = (kw or "").strip().lower()
        if not low:
            return None
        for t in self._terms:
            for txt in term_texts(t):
                tl = txt.lower()
                if low == tl or low == tl + "s" or low + "s" == tl:
                    return t
        return None

    def _hit_color(self, ki: int) -> tuple:
        if 0 <= ki < len(self._search_kws):
            t = self._term_for_keyword(self._search_kws[ki])
            if t is not None:
                return tuple(t.color_rgb)
        return self.SEARCH_COLORS[ki % len(self.SEARCH_COLORS)]

    # ------------------------------------------------------------ 표시

    def _refresh_display(self):
        """검색 하이라이트 + 매핑된 구간 표시를 다시 그린다."""
        sels = []

        # 매핑된 구간: 옅은 밑줄로 표시 (검색 하이라이트에 묻히지 않게 먼저)
        for m in self._mappings:
            rect = list(m.rect or [0, 0, 0, 0])
            start, end = int(rect[0]), int(rect[1])
            if not (0 <= start < end <= len(self._text)):
                continue
            rgb = (self._term_colors.get(m.term_id)
                   or self._elem_colors.get(m.element_id) or (120, 120, 120))
            fmt = QTextCharFormat()
            fmt.setUnderlineColor(QColor(*rgb))
            fmt.setUnderlineStyle(
                QTextCharFormat.UnderlineStyle.SingleUnderline)
            sels.append(self._selection(start, end, fmt))

        for i, (start, end, ki) in enumerate(self._search_hits):
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(*self._hit_color(ki)))
            if i == self._search_idx:
                fmt.setUnderlineColor(QColor(220, 30, 30))
                fmt.setUnderlineStyle(
                    QTextCharFormat.UnderlineStyle.SingleUnderline)
            sels.append(self._selection(start, end, fmt))

        self.editor.setExtraSelections(sels)

        if not self._last_query:
            self.hit_label.setText("")
        elif not self._search_hits:
            self.hit_label.setText("0건")
        else:
            self.hit_label.setText(
                f"{self._search_idx + 1}/{len(self._search_hits)}")

    def _selection(self, start: int, end: int, fmt: QTextCharFormat):
        sel = QTextEdit.ExtraSelection()
        c = QTextCursor(self.editor.document())
        c.setPosition(start)
        c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = c
        sel.format = fmt
        return sel

    # ------------------------------------------------------------ 용어

    def _show_term_menu(self):
        kws = self._search_kws or self._parse_keywords(
            self.search_input.text().strip())
        if not kws:
            QMessageBox.information(self, "알림",
                                    "먼저 색을 지정할 단어를 검색해 주세요.")
            return
        if not self._terms:
            QMessageBox.information(
                self, "알림",
                "등록된 매칭 용어가 없습니다.\n"
                "왼쪽 청구항 패널에서 용어를 먼저 등록해 주세요.")
            return

        kw = kws[0] if len(kws) == 1 else ", ".join(kws)
        menu = QMenu(self)
        menu.addAction(f'"{kw}" → 아래 용어와 같은 색으로').setEnabled(False)
        menu.addSeparator()
        for t in self._terms:
            pm = QPixmap(14, 14)
            pm.fill(QColor(*tuple(t.color_rgb)))
            act = menu.addAction(QIcon(pm), f"{t.term_id}  {t.text}")
            act.triggered.connect(
                lambda _c=False, tid=t.term_id: self._assign_terms(tid))
        menu.exec(self.term_btn.mapToGlobal(
            self.term_btn.rect().bottomLeft()))

    def _assign_terms(self, term_id: str):
        kws = self._search_kws or self._parse_keywords(
            self.search_input.text().strip())
        for kw in kws:
            self.alias_requested.emit(term_id, kw)

    # -------------------------------------------- PDF 뷰어와 같은 인터페이스

    def set_terms(self, terms: list):
        self._terms = terms or []
        if self._last_query:      # 용어가 바뀌면 구분 단위도 달라진다
            self._run_search(self._last_query)
        else:
            self._refresh_display()

    def update_mappings(self, mappings: list[MappingEntry],
                        element_colors: dict = None,
                        term_colors: dict = None):
        self._mappings = [m for m in mappings if m.doc_path == self.doc_path]
        if element_colors:
            self._elem_colors = element_colors
        if term_colors is not None:
            self._term_colors = term_colors
        self._refresh_display()

    def _goto_page(self, index: int):
        """PDF 뷰어 호환 (텍스트 문서는 단일 페이지)."""
        return

    def goto_offset(self, start: int, end: int):
        if not (0 <= start < end <= len(self._text)):
            return
        c = self.editor.textCursor()
        c.setPosition(start)
        c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(c)
        self.editor.ensureCursorVisible()

    def title(self) -> str:
        return doc_title(self.doc_path)

    def close_doc(self):
        return


def parse_keywords(query: str, terms: list = None) -> list:
    """검색어를 키워드 목록으로 분해.

    - 쉼표(,)가 있으면 쉼표 기준 (구문 검색)
    - 큰따옴표로 묶은 부분은 통째로 한 키워드
    - 등록된 용어/별칭이 여러 단어면 쪼개지 않고 한 덩어리로 유지
      ("host material"은 host와 material로 나뉘면 안 된다)
    """
    query = (query or "").strip()
    if not query:
        return []
    if "," in query or ";" in query:
        return [c.strip() for c in query.replace(";", ",").split(",")
                if c.strip()]

    phrases = []
    for t in (terms or []):
        for txt in term_texts(t):
            if " " in txt.strip():
                phrases.append(txt.strip())
    # 인용부호로 묶은 구문도 하나의 키워드로 취급
    for m in re.finditer(r'"([^"]+)"', query):
        if m.group(1).strip():
            phrases.append(m.group(1).strip())
    phrases.sort(key=len, reverse=True)

    out, rest = [], query
    for ph in phrases:
        pat = re.compile(r'"?' + re.escape(ph) + r'"?', re.IGNORECASE)
        if pat.search(rest):
            out.append(ph)
            rest = pat.sub(" ", rest)
    out += [w for w in rest.replace('"', " ").split() if w.strip()]

    seen, uniq = set(), []
    for kw in out:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            uniq.append(kw)
    return uniq
