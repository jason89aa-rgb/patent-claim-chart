"""PDF에서 추출된 청구항을 미리보고 선택해서 가져오는 다이얼로그."""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QTextEdit, QPushButton, QCheckBox,
    QRadioButton, QButtonGroup, QSplitter, QWidget, QDialogButtonBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.claims_extractor import ExtractedClaim


class ClaimsImportDialog(QDialog):
    """추출된 청구항 목록 → 체크 선택 + 미리보기 + 가져오기 옵션."""

    def __init__(self, claims: list[ExtractedClaim], source_path: str,
                 parent=None):
        super().__init__(parent)
        self._claims = claims
        self.setWindowTitle("PDF에서 청구항 가져오기")
        self.resize(760, 560)
        self._setup_ui(source_path)

    def _setup_ui(self, source_path: str):
        layout = QVBoxLayout(self)

        n_indep = sum(1 for c in self._claims if c.is_independent)
        header = QLabel(
            f"<b>{os.path.basename(source_path)}</b> 에서 "
            f"청구항 <b>{len(self._claims)}개</b> 발견 "
            f"(독립항 {n_indep}개, 종속항 {len(self._claims) - n_indep}개)")
        layout.addWidget(header)

        # 전체 선택/해제
        sel_bar = QHBoxLayout()
        all_btn = QPushButton("전체 선택")
        all_btn.clicked.connect(lambda: self._set_all_checked(True))
        sel_bar.addWidget(all_btn)
        none_btn = QPushButton("전체 해제")
        none_btn.clicked.connect(lambda: self._set_all_checked(False))
        sel_bar.addWidget(none_btn)
        indep_btn = QPushButton("독립항만")
        indep_btn.clicked.connect(self._check_independent_only)
        sel_bar.addWidget(indep_btn)
        sel_bar.addStretch()
        layout.addLayout(sel_bar)

        # 좌: 목록 / 우: 미리보기
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.list_widget = QListWidget()
        for c in self._claims:
            kind = "독립" if c.is_independent else f"종속 ← {c.parent_claim}"
            preview = c.text[:60].replace("\n", " ")
            item = QListWidgetItem(f"청구항 {c.number} [{kind}]  {preview}…")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, c.number)
            self.list_widget.addItem(item)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        splitter.addWidget(self.list_widget)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("맑은 고딕", 10))
        splitter.addWidget(self.preview)
        splitter.setSizes([380, 380])
        layout.addWidget(splitter, stretch=1)

        if self._claims:
            self.list_widget.setCurrentRow(0)

        # 옵션 — 왼쪽에 깔끔하게 한 줄로 정렬
        opt_bar = QHBoxLayout()
        opt_bar.setSpacing(14)
        self.auto_split_check = QCheckBox("구성요소 자동 분할")
        self.auto_split_check.setChecked(True)
        opt_bar.addWidget(self.auto_split_check)

        sep = QLabel("|")
        sep.setStyleSheet("color: #bbb;")
        opt_bar.addWidget(sep)

        self.replace_radio = QRadioButton("기존 청구항 교체")
        self.append_radio = QRadioButton("기존 뒤에 추가")
        self.replace_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.replace_radio)
        mode_group.addButton(self.append_radio)
        opt_bar.addWidget(self.replace_radio)
        opt_bar.addWidget(self.append_radio)
        opt_bar.addStretch()
        layout.addLayout(opt_bar)

        # 버튼 — 우측 하단 정렬, 가져오기는 주요 버튼 강조
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()
        cancel_btn = QPushButton("취소")
        cancel_btn.setFixedWidth(88)
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)
        ok_btn = QPushButton("가져오기")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.setFixedWidth(110)
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_bar.addWidget(ok_btn)
        layout.addLayout(btn_bar)

    def _on_row_changed(self, row: int):
        if 0 <= row < len(self._claims):
            self.preview.setText(self._claims[row].text)

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(state)

    def _check_independent_only(self):
        for i in range(self.list_widget.count()):
            c = self._claims[i]
            state = (Qt.CheckState.Checked if c.is_independent
                     else Qt.CheckState.Unchecked)
            self.list_widget.item(i).setCheckState(state)

    # ------------------------------------------------------------ 결과

    def get_selected_claims(self) -> list[ExtractedClaim]:
        selected_nums = set()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_nums.add(item.data(Qt.ItemDataRole.UserRole))
        return [c for c in self._claims if c.number in selected_nums]

    def auto_split_enabled(self) -> bool:
        return self.auto_split_check.isChecked()

    def replace_mode(self) -> bool:
        return self.replace_radio.isChecked()
