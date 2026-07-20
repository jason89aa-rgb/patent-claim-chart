"""선행문헌 정보 패널 — 라벨(D1 …)·공개일·적격성을 한 표로 관리.

문헌을 열면 서지가 자동으로 채워지고, 공개일이 대상 특허의
기준일(우선일)보다 앞서는지 즉시 판정된다. 기준일 이후에 공개된
문헌을 인용하면 무효 논리가 통째로 무너지므로 붉게 경고한다.
"""
import os

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox
)

from core.prior_art import (STATUS_BAD, STATUS_OK, STATUS_STYLE,
                            eligibility, public_date)
from core.text_doc import is_text_doc

_COLS = ["라벨", "문헌", "공보 번호", "공개일", "등록일", "적격성"]
_EDITABLE = {0, 2, 3, 4}          # 라벨·공보번호·공개일·등록일


class PriorArtPanel(QWidget):
    """선행문헌 등록부 표. 편집(라벨·날짜)은 즉시 프로젝트에 반영된다."""
    changed = pyqtSignal()                 # 라벨/날짜 편집됨
    open_requested = pyqtSignal(str)       # 더블클릭 → 문서 열기
    reread_requested = pyqtSignal(str, bool)   # (path, OCR 사용 여부)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._docs: list = []
        self._base_date = ""
        self._base_kind = ""
        self._building = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("선행문헌 정보")
        title.setStyleSheet("font-weight: bold;")
        head.addWidget(title)

        self.base_label = QLabel("")
        head.addWidget(self.base_label)
        head.addStretch()

        reread_btn = QPushButton("서지 다시 읽기")
        reread_btn.setToolTip(
            "선택한 문헌의 1페이지에서 공보번호·공개일·등록일을 다시 "
            "읽어 채웁니다 (직접 고친 값은 덮어씁니다)")
        reread_btn.clicked.connect(lambda: self._reread(False))
        head.addWidget(reread_btn)

        self.ocr_btn = QPushButton("OCR로 읽기")
        self.ocr_btn.setToolTip(
            "스캔본(텍스트 없는 PDF)의 서지를 OCR로 읽습니다.\n"
            "30초~2분 정도 걸리고 오탈자가 있을 수 있습니다.")
        self.ocr_btn.clicked.connect(lambda: self._reread(True))
        head.addWidget(self.ocr_btn)
        layout.addLayout(head)

        guide = QLabel(
            "선행문헌은 대상 특허 기준일보다 먼저 공개된 것이어야 합니다. "
            "라벨·공보번호·날짜 칸은 직접 고칠 수 있고, "
            "문헌 이름을 더블클릭하면 그 문서를 엽니다.")
        guide.setWordWrap(True)
        guide.setStyleSheet("color: #69737E; font-size: 11px;")
        layout.addWidget(guide)

        self.table = QTableWidget()
        self.table.setFont(QFont("맑은 고딕", 8))
        self.table.setColumnCount(len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.table, stretch=1)

    # ------------------------------------------------------------ 데이터

    def refresh(self, prior_arts: list, base_date: str, base_kind: str):
        self._docs = list(prior_arts or [])
        self._base_date = base_date or ""
        self._base_kind = base_kind or ""

        if base_date:
            self.base_label.setText(
                f"대상 특허 기준일: {base_date} ({base_kind})")
            self.base_label.setStyleSheet("color: #2C455D; font-weight: bold;")
        else:
            self.base_label.setText(
                "대상 특허 기준일 없음 — 서지사항 탭에서 우선일을 입력하세요")
            self.base_label.setStyleSheet("color: #9D3533; font-weight: bold;")

        self._building = True
        try:
            self.table.setRowCount(len(self._docs))
            for r, doc in enumerate(self._docs):
                self._fill_row(r, doc)
        finally:
            self._building = False

        header = self.table.horizontalHeader()
        for c in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def _fill_row(self, r: int, doc):
        def put(col, text, editable, tooltip=""):
            item = QTableWidgetItem(text or "")
            if not editable:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if tooltip:
                item.setToolTip(tooltip)
            self.table.setItem(r, col, item)
            return item

        label_item = put(0, doc.label, True,
                         "보고서에 실릴 문헌 번호 (D1, 갑제3호증 등)")
        label_item.setFont(QFont("맑은 고딕", 8, QFont.Weight.Bold))

        name = doc.title or os.path.basename(doc.path)
        kind = " (붙여넣은 텍스트)" if is_text_doc(doc.path) else ""
        put(1, name + kind, False,
            f"{doc.path}\n더블클릭하면 이 문서를 엽니다")

        put(2, doc.pub_number, True)
        put(3, doc.pub_date, True,
            "공개공보 발행일 (YYYY-MM-DD) — 적격성 판단의 기준")
        put(4, doc.reg_date, True, "등록공고일 (YYYY-MM-DD)")

        status, detail = eligibility(doc, self._base_date)
        fg, bg = STATUS_STYLE[status]
        mark = {STATUS_OK: "✓ ", STATUS_BAD: "✗ "}.get(status, "? ")
        st = put(5, mark + status, False, detail)
        st.setForeground(QBrush(QColor(fg)))
        st.setBackground(QBrush(QColor(bg)))
        st.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    # ------------------------------------------------------------ 편집

    def _on_item_changed(self, item):
        if self._building:
            return
        r, c = item.row(), item.column()
        if not (0 <= r < len(self._docs)) or c not in _EDITABLE:
            return
        doc = self._docs[r]
        value = item.text().strip()
        if c == 0:
            doc.label = value
        elif c == 2:
            doc.pub_number = value
        elif c == 3:
            doc.pub_date = value
        elif c == 4:
            doc.reg_date = value
        # 날짜가 바뀌면 적격성 칸을 다시 그린다
        self._building = True
        try:
            self._fill_row(r, doc)
        finally:
            self._building = False
        self.changed.emit()

    def _on_double_clicked(self, row: int, col: int):
        if col == 1 and 0 <= row < len(self._docs):
            self.open_requested.emit(self._docs[row].path)

    def _reread(self, use_ocr: bool):
        row = self.table.currentRow()
        if not (0 <= row < len(self._docs)):
            QMessageBox.information(
                self, "알림", "먼저 표에서 문헌을 선택해 주세요.")
            return
        doc = self._docs[row]
        if is_text_doc(doc.path):
            QMessageBox.information(
                self, "알림",
                "붙여넣은 텍스트 문서에는 서지 페이지가 없습니다.\n"
                "공개일을 직접 입력해 주세요.")
            return
        self.reread_requested.emit(doc.path, use_ocr)

    # ------------------------------------------------------------ 요약

    def bad_count(self) -> int:
        return sum(1 for d in self._docs
                   if eligibility(d, self._base_date)[0] == STATUS_BAD)
