"""PDF에서 읽은 서지사항을 확인하고 사건 정보에 반영하는 다이얼로그.

읽은 값을 그대로 덮어쓰지 않고, 항목별로 체크해서 적용한다
(이미 입력해 둔 값을 실수로 날리지 않도록).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGridLayout, QWidget, QScrollArea, QFrame
)

from core.biblio_extractor import FIELD_LABELS


class BiblioImportDialog(QDialog):
    def __init__(self, biblio: dict, current: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF에서 서지사항 가져오기")
        self.resize(680, 520)
        self._biblio = biblio
        self._current = current
        self._checks: dict = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        src = self._biblio.get("_source") or "?"
        head = QLabel(f"PDF 1페이지에서 읽은 값입니다 ({src} 공보 형식). "
                      "적용할 항목만 체크하세요.")
        head.setWordWrap(True)
        head.setStyleSheet("color: #69737E;")
        layout.addWidget(head)

        container = QWidget()
        grid = QGridLayout(container)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        for col, title in enumerate(("항목", "PDF에서 읽은 값", "현재 값")):
            lb = QLabel(title)
            lb.setStyleSheet("font-weight: bold; color: #4A5560;")
            grid.addWidget(lb, 0, col)

        row = 1
        found_any = False
        for key, label in FIELD_LABELS:
            new_val = self._biblio.get(key) or ""
            if isinstance(new_val, list):
                new_val = ", ".join(new_val)
            cur_val = self._current.get(key) or ""
            if isinstance(cur_val, list):
                cur_val = ", ".join(cur_val)

            cb = QCheckBox(label)
            cb.setEnabled(bool(new_val))
            # 값이 있고, 기존 값과 다를 때만 기본 체크
            cb.setChecked(bool(new_val) and new_val != cur_val)
            self._checks[key] = cb
            grid.addWidget(cb, row, 0)

            new_lb = QLabel(new_val or "— 못 찾음 —")
            new_lb.setWordWrap(True)
            if new_val:
                found_any = True
                new_lb.setStyleSheet("color: #1B683E; font-weight: bold;")
            else:
                new_lb.setStyleSheet("color: #A0A8B0;")
            grid.addWidget(new_lb, row, 1)

            cur_lb = QLabel(cur_val or "(비어 있음)")
            cur_lb.setWordWrap(True)
            cur_lb.setStyleSheet(
                "color: #8A6000;" if cur_val and cur_val != new_val
                else "color: #98A2AD;")
            grid.addWidget(cur_lb, row, 2)
            row += 1

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        if not found_any:
            warn = QLabel(
                "서지사항을 찾지 못했습니다. 스캔본(이미지 PDF)이거나 "
                "지원하지 않는 공보 형식일 수 있습니다.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #9D3533;")
            layout.addWidget(warn)

        btn_bar = QHBoxLayout()
        all_btn = QPushButton("전체 선택")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = QPushButton("전체 해제")
        none_btn.clicked.connect(lambda: self._set_all(False))
        btn_bar.addWidget(all_btn)
        btn_bar.addWidget(none_btn)
        btn_bar.addStretch()
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("선택 항목 적용")
        ok.setObjectName("primaryBtn")
        ok.setDefault(True)
        ok.setEnabled(found_any)
        ok.clicked.connect(self.accept)
        btn_bar.addWidget(cancel)
        btn_bar.addWidget(ok)
        layout.addLayout(btn_bar)

    def _set_all(self, state: bool):
        for cb in self._checks.values():
            if cb.isEnabled():
                cb.setChecked(state)

    def selected(self) -> dict:
        """체크된 항목만 담은 dict."""
        return {k: self._biblio[k] for k, cb in self._checks.items()
                if cb.isChecked() and self._biblio.get(k)}
