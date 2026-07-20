"""선행문헌 명세서 텍스트 붙여넣기 다이얼로그.

붙여넣은 텍스트는 PDF로 변환되어 기존 뷰어 기능(드래그 선택, 문장 스냅,
영역 캡처, 매핑, 키워드 검색)을 그대로 사용할 수 있다.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton
)


class PasteTextDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("텍스트 붙여넣기")
        self.resize(760, 560)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        guide = QLabel(
            "선행문헌 명세서 텍스트를 붙여넣으세요 (Ctrl+V).\n"
            "문서 탭으로 변환되어 드래그 선택·검색·매핑이 그대로 동작합니다.")
        guide.setStyleSheet("color: #69737E;")
        guide.setWordWrap(True)
        layout.addWidget(guide)

        title_bar = QHBoxLayout()
        title_bar.addWidget(QLabel("문서 이름:"))
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("예: KR10-2020-0012345 명세서")
        title_bar.addWidget(self.title_input, stretch=1)
        layout.addLayout(title_bar)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("여기에 명세서 텍스트를 붙여넣기…")
        layout.addWidget(self.text_edit, stretch=1)

        self.count_label = QLabel("0자")
        self.count_label.setStyleSheet("color: #98A2AD;")
        self.text_edit.textChanged.connect(self._update_count)

        btn_bar = QHBoxLayout()
        btn_bar.addWidget(self.count_label)
        btn_bar.addStretch()
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("문서로 열기")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_bar.addWidget(cancel_btn)
        btn_bar.addWidget(ok_btn)
        layout.addLayout(btn_bar)

    def _update_count(self):
        n = len(self.text_edit.toPlainText())
        self.count_label.setText(f"{n:,}자")

    def get_result(self) -> tuple:
        title = self.title_input.text().strip() or "붙여넣은 명세서"
        return title, self.text_edit.toPlainText()
