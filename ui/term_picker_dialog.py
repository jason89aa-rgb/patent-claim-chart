"""청구항에서 자동 추출한 후보 용어를 골라 매칭 용어로 등록하는 다이얼로그."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QDialogButtonBox, QLineEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.term_extractor import TermCandidate


class TermPickerDialog(QDialog):
    """후보 용어 체크 선택 + 직접 입력."""

    def __init__(self, candidates: list[TermCandidate],
                 existing_terms: list[str] = None, parent=None):
        super().__init__(parent)
        self._candidates = candidates
        self._existing = {t.lower() for t in (existing_terms or [])}
        self.setWindowTitle("청구항 요소(Element) 선택")
        self.resize(520, 560)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(
            "청구항에서 추출한 <b>요소(Element)</b> 후보입니다. "
            "선행문헌·표준과 매칭할 요소를 선택하세요.\n"
            "선택한 요소는 청구항과 대응부분에서 <b>같은 색</b>으로 표시됩니다 "
            "(예: 청구항 power lines ↔ 도면 VDDL).")
        header.setWordWrap(True)
        header.setTextFormat(Qt.TextFormat.RichText)
        header.setStyleSheet("color: #aaa;")
        layout.addWidget(header)

        guide = QLabel(
            "💡 구성요소부 = <b>요소(Element)</b> + <b>제한조건(Limitation)</b>\n"
            "   · 요소(Element): 청구항이 정의하는 핵심 구성 (명사구) — 여기서 선택\n"
            "   · 제한조건(Limitation): 그 요소를 수식하는 나머지 문구\n"
            "   · All Elements Rule: 모든 요소·제한조건이 대응돼야 침해/무효 성립")
        guide.setWordWrap(True)
        guide.setTextFormat(Qt.TextFormat.RichText)
        guide.setStyleSheet(
            "color: #888; font-size: 9px; padding: 6px; "
            "border: 1px dashed #555; border-radius: 4px;")
        layout.addWidget(guide)

        # 전체 선택/해제
        sel_bar = QHBoxLayout()
        all_btn = QPushButton("전체 선택")
        all_btn.clicked.connect(lambda: self._set_all(True))
        sel_bar.addWidget(all_btn)
        none_btn = QPushButton("전체 해제")
        none_btn.clicked.connect(lambda: self._set_all(False))
        sel_bar.addWidget(none_btn)
        sel_bar.addStretch()
        layout.addLayout(sel_bar)

        self.list_widget = QListWidget()
        self.list_widget.setFont(QFont("맑은 고딕", 10))
        for c in self._candidates:
            already = c.text.lower() in self._existing
            where = f"  [{', '.join(c.element_ids)}]" if c.element_ids else ""
            label = f"{c.text}   —  {c.count}회 등장{where}"
            if already:
                label += "  [등록됨]"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, c.text)
            if already:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, stretch=1)

        # 직접 입력
        manual_bar = QHBoxLayout()
        manual_bar.addWidget(QLabel("요소 직접 추가:"))
        self.manual_input = QLineEdit()
        self.manual_input.setPlaceholderText(
            "추출되지 않은 요소(Element)를 직접 입력 (Enter)")
        self.manual_input.returnPressed.connect(self._add_manual)
        manual_bar.addWidget(self.manual_input, stretch=1)
        add_btn = QPushButton("추가")
        add_btn.setFixedWidth(64)
        add_btn.clicked.connect(self._add_manual)
        manual_bar.addWidget(add_btn)
        layout.addLayout(manual_bar)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("등록")
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryBtn")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _set_all(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(state)

    def _add_manual(self):
        text = self.manual_input.text().strip()
        if not text:
            return
        if text.lower() in self._existing:
            self.manual_input.clear()
            return
        item = QListWidgetItem(f"{text}   —  직접 입력")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        item.setData(Qt.ItemDataRole.UserRole, text)
        self.list_widget.insertItem(0, item)
        self.manual_input.clear()

    def get_selected_terms(self) -> list[str]:
        result = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result
