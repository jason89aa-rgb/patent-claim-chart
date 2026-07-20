"""커버리지 갭 매트릭스 — 구성요소 × 선행문헌 격자.

어느 구성요소가 아직 어떤 문헌으로도 대응되지 않았는지(= 갭) 한눈에 본다.
All Elements Rule 상 모든 구성요소가 대응돼야 무효/침해가 성립하므로,
빈칸이 곧 남은 일감이다.

셀을 누르면 해당 매핑 위치로 뷰어가 이동한다(검증용).
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cells: dict = {}      # (row, col) -> [MappingEntry, ...]
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("커버리지 갭")
        title.setStyleSheet("font-weight: bold;")
        head.addWidget(title)

        self.inherit_check = QCheckBox("종속항에 인용항 구성요소 포함")
        self.inherit_check.setChecked(True)
        self.inherit_check.setToolTip(
            "종속항은 인용항의 모든 구성요소를 포함합니다.\n"
            "켜두면 인용항 구성요소가 종속항 행에도 나타나고,\n"
            "독립항에 붙인 매핑이 그대로 표시됩니다 (매핑 복제 없음).")
        self.inherit_check.stateChanged.connect(self._rebuild)
        head.addWidget(self.inherit_check)

        self.gap_only_check = QCheckBox("갭만 보기")
        self.gap_only_check.setToolTip(
            "어느 문헌으로도 대응되지 않은 구성요소만 표시합니다")
        self.gap_only_check.stateChanged.connect(self._rebuild)
        head.addWidget(self.gap_only_check)

        head.addStretch()
        self.summary_label = QLabel("")
        head.addWidget(self.summary_label)
        layout.addLayout(head)

        self.table = QTableWidget()
        self.table.setFont(QFont("맑은 고딕", 8))
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.table, stretch=1)

        hint = QLabel("셀을 클릭하면 해당 매핑 위치로 이동합니다")
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
        """(claim, ScopeElement) 목록 — '갭만 보기'면 미대응 구성요소만.

        종속항은 인용항 구성요소까지 함께 보여준다(상속). 매핑을 복제하지
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
                label += f"  ← {item_scope.source_claim}항"
            head = QTableWidgetItem(label)
            tip = elem.text
            if item_scope.inherited:
                tip = (f"[{item_scope.source_claim}항에서 상속]\n"
                       f"종속항은 인용항 구성요소를 모두 포함합니다.\n\n{tip}")
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
                    item.setToolTip("대응 없음")
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
            self.summary_label.setText("선행문헌을 열고 매핑을 추가해 주세요")
            self.summary_label.setStyleSheet("color: #98A2AD;")
        elif gap_elems:
            self.summary_label.setText(
                f"미대응 구성요소 {gap_elems} / {total_elems}개")
            self.summary_label.setStyleSheet(
                "color: #B4443F; font-weight: bold;")
        else:
            self.summary_label.setText(
                f"전체 대응 완료 ({total_elems}개)")
            self.summary_label.setStyleSheet(
                "color: #1B683E; font-weight: bold;")

    # ------------------------------------------------------------ 상호작용

    def _on_cell_clicked(self, row: int, col: int):
        maps = self._cells.get((row, col))
        if not maps:
            return
        m = maps[0]
        self.jump_requested.emit(m.doc_path, m.page, list(m.rect))
