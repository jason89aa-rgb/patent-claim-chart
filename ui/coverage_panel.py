"""대응 현황표 — 구성요소 × 선행문헌 격자.

어느 구성요소가 아직 어떤 문헌으로도 대응되지 않았는지 한눈에 본다.
모든 구성요소가 대응돼야 무효/침해가 성립하므로(All Elements Rule),
빈칸이 곧 남은 일감이다.

셀을 누르면 해당 매핑 위치로 뷰어가 이동한다(근거 확인용).
"""
import os

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox
)

from core.claim_scope import ScopeElement, effective_elements
from core.project import Claim, MappingEntry
from core.text_doc import is_text_doc, doc_title

# 판단별 셀 색 (배경, 글자)
_JUDGMENT_CELL = {
    "일치": ("#D7F4E0", "#1B683E"),
    "부분일치": ("#FBEEC9", "#8A6000"),
    "불일치": ("#F8E3E1", "#9D3533"),
    "미판단": ("#E9E9EA", "#5A5A5D"),
}
_GAP_BG = "#FDECEA"        # 매핑 없음 (갭)
_GAP_FG = "#B4443F"
_ROW_GAP_BG = "#FFF6F5"    # 어느 문헌에도 대응 없는 구성요소 행

_JUDGMENT_RANK = {"일치": 0, "부분일치": 1, "불일치": 2, "미판단": 3}


def doc_label(path: str) -> str:
    """열 머리말용 짧은 문서 이름."""
    if not path:
        return "선행문헌"
    if is_text_doc(path):
        return doc_title(path)
    return os.path.splitext(os.path.basename(path))[0]


class CoveragePanel(QWidget):
    """구성요소 × 문헌 커버리지 매트릭스."""
    jump_requested = pyqtSignal(str, int, list)   # doc_path, page, rect
    inherit_changed = pyqtSignal(bool)   # 인용항 구성요소 함께 보기 on/off

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cells: dict = {}      # (row, col) -> [MappingEntry, ...]
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("구성요소별 대응 현황")
        title.setStyleSheet("font-weight: bold;")
        title.setToolTip(
            "청구항 구성요소와 선행문헌이 만나는 자리에 대응 여부를 "
            "표시합니다.\n빈칸은 아직 근거를 찾지 못한 곳입니다.")
        head.addWidget(title)

        self.inherit_check = QCheckBox("종속항에 인용항 구성요소 함께 보기")
        self.inherit_check.setChecked(True)
        self.inherit_check.setToolTip(
            "예: 3항이 1항을 인용하면 3항도 1항 구성요소를 모두 포함합니다.\n"
            "켜두면 3항 줄에 1항 구성요소가 함께 나오고,\n"
            "1항에 이미 연결해 둔 근거가 그대로 보입니다.\n"
            "(매핑을 복사하는 것이 아니라 같이 보여주는 것입니다)")
        self.inherit_check.toggled.connect(self._on_inherit_toggled)
        head.addWidget(self.inherit_check)

        self.gap_only_check = QCheckBox("근거 없는 것만 보기")
        self.gap_only_check.setToolTip(
            "어느 선행문헌으로도 대응되지 않은 구성요소만 추립니다.\n"
            "= 앞으로 근거를 찾아야 할 목록")
        self.gap_only_check.stateChanged.connect(self._rebuild)
        head.addWidget(self.gap_only_check)

        head.addStretch()
        self.summary_label = QLabel("")
        head.addWidget(self.summary_label)
        layout.addLayout(head)

        guide = QLabel(
            "가로줄 = 청구항 구성요소 · 세로칸 = 선행문헌 · "
            "빈칸(—)은 아직 대응 근거가 없다는 뜻입니다.")
        guide.setWordWrap(True)
        guide.setStyleSheet("color: #69737E; font-size: 11px;")
        layout.addWidget(guide)

        self.table = QTableWidget()
        self.table.setFont(QFont("맑은 고딕", 8))
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table, stretch=1)

        hint = QLabel(
            "칸을 클릭하면 그 근거가 있는 선행문헌 위치로 이동합니다  ·  "
            "칸 색: 일치(초록) / 부분일치(노랑) / 불일치(빨강) / "
            "미판단(회색) / 근거 없음(연분홍)")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #98A2AD; font-size: 10px;")
        layout.addWidget(hint)

        self._claims: list = []
        self._mappings: list = []
        self._docs: list = []

    # ------------------------------------------------------------ 데이터

    def refresh(self, claims: list, mappings: list, doc_paths: list = None):
        self._claims = claims or []
        self._mappings = mappings or []
        # 열: 매핑에 등장하는 문헌 + 현재 열려 있는 문헌
        docs = []
        for m in self._mappings:
            if m.doc_path and m.doc_path not in docs:
                docs.append(m.doc_path)
        for p in (doc_paths or []):
            if p and p not in docs:
                docs.append(p)
        self._docs = docs
        self._rebuild()

    def _rows(self) -> list:
        """(claim, ScopeElement) 목록 — '근거 없는 것만 보기'면 미대응만.

        종속항은 인용항 구성요소까지 함께 보여준다. 매핑을 복제하지
        않으므로 독립항에 붙인 근거가 종속항 행에도 그대로 나타난다.
        """
        mapped = {m.element_id for m in self._mappings if m.element_id}
        rows = []
        for claim in self._claims:
            scope = (effective_elements(claim, self._claims)
                     if self.inherit_check.isChecked()
                     else [ScopeElement(e, claim.claim_number)
                           for e in claim.elements])
            for item in scope:
                if (self.gap_only_check.isChecked()
                        and item.element_id in mapped):
                    continue
                rows.append((claim, item))
        return rows

    def _rebuild(self):
        rows = self._rows()
        self._cells = {}

        self.table.clear()
        self.table.setColumnCount(1 + len(self._docs))
        self.table.setHorizontalHeaderLabels(
            ["구성요소"] + [doc_label(p) for p in self._docs])
        self.table.setRowCount(len(rows))

        by_elem_doc = {}
        for m in self._mappings:
            by_elem_doc.setdefault((m.element_id, m.doc_path), []).append(m)

        total_elems, gap_elems = 0, 0
        for r, (claim, item_scope) in enumerate(rows):
            elem = item_scope.element
            total_elems += 1
            label = f"청구항 {claim.claim_number}  {elem.element_id}"
            if item_scope.inherited:
                label += f"  ({item_scope.source_claim}항 인용)"
            head = QTableWidgetItem(label)
            tip = elem.text
            if item_scope.inherited:
                src = item_scope.source_claim
                tip = (f"[{src}항에서 가져온 구성요소]\n"
                       f"이 청구항은 {src}항을 인용하므로 {src}항 "
                       f"구성요소도 함께 대비해야 합니다.\n\n{tip}")
            head.setToolTip(tip)
            rgb = tuple(elem.color_rgb)
            head.setForeground(QBrush(QColor(*rgb)))
            head.setFont(QFont("맑은 고딕", 8,
                               QFont.Weight.Normal if item_scope.inherited
                               else QFont.Weight.Bold))
            self.table.setItem(r, 0, head)

            row_has_any = False
            for c, doc in enumerate(self._docs, start=1):
                maps = by_elem_doc.get((elem.element_id, doc), [])
                item = QTableWidgetItem()
                if maps:
                    row_has_any = True
                    best = min(maps, key=lambda m: _JUDGMENT_RANK.get(
                        m.judgment, 9))
                    bg, fg = _JUDGMENT_CELL.get(best.judgment,
                                                _JUDGMENT_CELL["미판단"])
                    label = best.judgment
                    if len(maps) > 1:
                        label += f" ({len(maps)})"
                    item.setText(label)
                    item.setToolTip(
                        "\n".join(f"p.{m.page + 1}  {m.judgment} / "
                                  f"{m.interpretation}" for m in maps[:6]))
                    self._cells[(r, c)] = maps
                else:
                    bg, fg = _GAP_BG, _GAP_FG
                    item.setText("—")
                    item.setToolTip("아직 이 문헌에서 대응 근거를 찾지 못했습니다")
                item.setBackground(QBrush(QColor(bg)))
                item.setForeground(QBrush(QColor(fg)))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)

            if not row_has_any:
                gap_elems += 1
                head.setBackground(QBrush(QColor(_ROW_GAP_BG)))

        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for c in range(1, self.table.columnCount()):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)

        if not self._docs:
            self.summary_label.setText(
                "선행문헌을 열고 대응 부분을 연결해 주세요")
            self.summary_label.setStyleSheet("color: #98A2AD;")
        elif gap_elems:
            self.summary_label.setText(
                f"근거 없는 구성요소 {gap_elems} / {total_elems}개")
            self.summary_label.setStyleSheet(
                "color: #B4443F; font-weight: bold;")
        else:
            self.summary_label.setText(
                f"모든 구성요소에 근거 있음 ({total_elems}개)")
            self.summary_label.setStyleSheet(
                "color: #1B683E; font-weight: bold;")

    # ------------------------------------------------------------ 상호작용

    def _on_inherit_toggled(self, on: bool):
        self._rebuild()
        self.inherit_changed.emit(on)

    def set_inherit(self, on: bool):
        """메뉴 쪽에서 바뀐 설정을 반영 (되돌아오는 신호는 막는다)."""
        if self.inherit_check.isChecked() == on:
            return
        self.inherit_check.blockSignals(True)
        self.inherit_check.setChecked(on)
        self.inherit_check.blockSignals(False)
        self._rebuild()

    def _on_cell_clicked(self, row: int, col: int):
        maps = self._cells.get((row, col))
        if not maps:
            return
        m = maps[0]
        self.jump_requested.emit(m.doc_path, m.page, list(m.rect))
