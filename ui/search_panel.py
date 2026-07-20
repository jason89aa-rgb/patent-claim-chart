"""전체 문헌 통합 검색 — 열려 있는 선행문헌을 한 번에 훑는다.

한 구성요소가 문헌마다 다른 말로 쓰이는 게 보통이라(체결부 / 결합 /
고정 / fastening), 용어에 등록해 둔 표기를 모두 넣어 한 번에 찾는다.
찾은 결과에서 바로 매핑을 만들 수 있다.
"""
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMessageBox
)

from core.text_doc import is_text_doc
from utils.term_format import term_texts

_ALL = "— 전체 용어 —"


class SearchPanel(QWidget):
    """등록 용어(별칭 포함)로 모든 문헌을 검색하고 매핑까지 만든다."""
    jump_requested = pyqtSignal(str, int, list)          # doc_path, page, rect
    mapping_requested = pyqtSignal(str, int, list, str)  # + 추출 텍스트
    search_requested = pyqtSignal(list)                  # 키워드 목록

    def __init__(self, parent=None):
        super().__init__(parent)
        self._terms: list = []
        self._hits: list = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        title = QLabel("문헌 통합 검색")
        title.setStyleSheet("font-weight: bold;")
        bar.addWidget(title)

        bar.addWidget(QLabel("용어:"))
        self.term_combo = QComboBox()
        self.term_combo.setMinimumWidth(190)
        self.term_combo.setToolTip(
            "청구항 용어를 고르면 등록된 표기를 모두 넣어 검색합니다.\n"
            "예: 'power lines'를 고르면 선행문헌 표기 'VDDL'도 함께 찾습니다.")
        self.term_combo.currentIndexChanged.connect(self._on_term_picked)
        bar.addWidget(self.term_combo)

        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(
            "찾을 말 (쉼표로 여러 개: 체결부, 결합, fastening)")
        self.query_edit.setToolTip(
            "여러 표기를 쉼표로 구분해 넣으면 한 번에 찾습니다.\n"
            "같은 구성요소를 문헌마다 다르게 부르는 경우에 씁니다.")
        self.query_edit.returnPressed.connect(self._run)
        bar.addWidget(self.query_edit, stretch=1)

        go = QPushButton("전체 문헌 검색")
        go.setObjectName("primaryBtn")
        go.clicked.connect(self._run)
        bar.addWidget(go)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: #69737E;")
        bar.addWidget(self.count_label)
        layout.addLayout(bar)

        self.table = QTableWidget()
        self.table.setFont(QFont("맑은 고딕", 8))
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["선행문헌", "위치", "찾은 말", "문맥"])
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self._on_row_clicked)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, stretch=1)

        foot = QHBoxLayout()
        hint = QLabel(
            "한 번 클릭 = 그 위치로 이동 · 두 번 클릭 = 그 문장으로 매핑 만들기")
        hint.setStyleSheet("color: #98A2AD; font-size: 10px;")
        foot.addWidget(hint)
        foot.addStretch()
        self.map_btn = QPushButton("선택 결과로 매핑 만들기")
        self.map_btn.clicked.connect(self._map_selected)
        foot.addWidget(self.map_btn)
        layout.addLayout(foot)

    # ------------------------------------------------------------ 데이터

    def set_terms(self, terms: list):
        """용어 목록 갱신 (선택 상태는 최대한 유지)."""
        self._terms = terms or []
        current = self.term_combo.currentText()
        self.term_combo.blockSignals(True)
        self.term_combo.clear()
        self.term_combo.addItem(_ALL)
        for t in self._terms:
            texts = term_texts(t)
            label = f"{t.term_id}  {t.text}"
            if len(texts) > 1:
                label += f"  (+{len(texts) - 1})"
            self.term_combo.addItem(label, t.term_id)
        idx = self.term_combo.findText(current)
        self.term_combo.setCurrentIndex(max(idx, 0))
        self.term_combo.blockSignals(False)

    def _on_term_picked(self):
        """용어를 고르면 그 용어의 모든 표기를 검색창에 채운다."""
        term_id = self.term_combo.currentData()
        if not term_id:
            return
        term = next((t for t in self._terms if t.term_id == term_id), None)
        if term:
            self.query_edit.setText(", ".join(term_texts(term)))

    def _keywords(self) -> list:
        raw = self.query_edit.text().strip()
        if raw:
            return [k.strip() for k in raw.replace(";", ",").split(",")
                    if k.strip()]
        # 검색창이 비었으면 등록된 모든 표기를 찾는다
        out = []
        for t in self._terms:
            out.extend(term_texts(t))
        return out

    def _run(self):
        kws = self._keywords()
        if not kws:
            QMessageBox.information(
                self, "알림",
                "찾을 말을 입력하거나 청구항 용어를 먼저 등록해 주세요.")
            return
        self.search_requested.emit(kws)

    def show_results(self, hits: list, keywords: list = None):
        """검색 결과 표시 (실제 검색은 뷰어 패널이 수행)."""
        self._hits = hits or []
        self.table.setRowCount(len(self._hits))
        for r, h in enumerate(self._hits):
            doc = QTableWidgetItem(h["doc_label"])
            doc.setToolTip(h["doc_path"])
            self.table.setItem(r, 0, doc)

            if is_text_doc(h["doc_path"]):
                where = f"{int(h['rect'][0]):,}번째 글자"
            else:
                where = f"p.{h['page'] + 1}"
            self.table.setItem(r, 1, QTableWidgetItem(where))

            kw = QTableWidgetItem(h["keyword"])
            kw.setForeground(QBrush(QColor("#1B683E")))
            kw.setFont(QFont("맑은 고딕", 8, QFont.Weight.Bold))
            self.table.setItem(r, 2, kw)

            ctx = QTableWidgetItem(h.get("context", ""))
            ctx.setToolTip(h.get("context", ""))
            self.table.setItem(r, 3, ctx)

        header = self.table.horizontalHeader()
        for c in range(3):
            header.setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        n_docs = len({h["doc_path"] for h in self._hits})
        if self._hits:
            self.count_label.setText(f"{len(self._hits)}건 · 문헌 {n_docs}곳")
            self.count_label.setStyleSheet(
                "color: #1B683E; font-weight: bold;")
        else:
            kw_text = ", ".join(keywords or [])
            self.count_label.setText(f"'{kw_text}' 결과 없음")
            self.count_label.setStyleSheet("color: #B4443F;")

    # ------------------------------------------------------------ 상호작용

    def _hit_at(self, row: int):
        if 0 <= row < len(self._hits):
            return self._hits[row]
        return None

    def _on_row_clicked(self, row: int, _col: int):
        h = self._hit_at(row)
        if h:
            self.jump_requested.emit(h["doc_path"], h["page"],
                                     list(h["rect"]))

    def _on_row_double_clicked(self, row: int, _col: int):
        self._emit_mapping(self._hit_at(row))

    def _map_selected(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            QMessageBox.information(
                self, "알림", "매핑할 결과를 목록에서 선택해 주세요.")
            return
        self._emit_mapping(self._hit_at(min(rows)))

    def _emit_mapping(self, hit):
        """검색 결과 위치를 그대로 매핑 대상으로 넘긴다.

        문맥(주변 문장)을 인용 텍스트 초안으로 함께 보내 손질만 하면
        되게 한다.
        """
        if not hit:
            return
        self.mapping_requested.emit(
            hit["doc_path"], hit["page"], list(hit["rect"]),
            hit.get("context", "") or hit["keyword"])
