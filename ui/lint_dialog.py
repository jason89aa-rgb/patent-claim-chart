"""내보내기 전 점검 결과 다이얼로그.

경고를 무시하고 내보낼 수 있게 하되, 무엇이 빠졌는지는 반드시 보여준다.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QCheckBox
)

from core.export_lint import ERROR, summarize

_LEVEL_COLOR = {ERROR: "#9D3533", "경고": "#8A6000"}
_MAX_ITEMS = 40


class LintDialog(QDialog):
    def __init__(self, issues: list, target: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{target} 내보내기 전 점검")
        self.resize(680, 480)
        self._issues = issues
        self._setup_ui(target)

    def _setup_ui(self, target: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        n_err, n_warn = summarize(self._issues)
        head = QLabel(
            f"내보내기 전에 확인할 항목이 있습니다 — "
            f"오류 {n_err}건, 경고 {n_warn}건")
        head.setWordWrap(True)
        head.setStyleSheet("font-weight: bold;")
        layout.addWidget(head)

        sub = QLabel("그대로 진행할 수 있지만, 오류는 산출물에 그대로 반영됩니다.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #69737E;")
        layout.addWidget(sub)

        tree = QTreeWidget()
        tree.setHeaderLabels(["항목", "내용"])
        tree.setColumnWidth(0, 300)
        for issue in self._issues:
            top = QTreeWidgetItem([f"[{issue.level}] {issue.title}",
                                   issue.detail])
            top.setForeground(0, Qt.GlobalColor.darkRed
                              if issue.level == ERROR
                              else Qt.GlobalColor.darkYellow)
            for text in issue.items[:_MAX_ITEMS]:
                top.addChild(QTreeWidgetItem([text, ""]))
            if len(issue.items) > _MAX_ITEMS:
                top.addChild(QTreeWidgetItem(
                    [f"… 외 {len(issue.items) - _MAX_ITEMS}건", ""]))
            top.setExpanded(issue.level == ERROR)
            tree.addTopLevelItem(top)
        layout.addWidget(tree, stretch=1)

        self.skip_check = QCheckBox("이번 세션에서 이 점검 건너뛰기")
        layout.addWidget(self.skip_check)

        bar = QHBoxLayout()
        bar.addStretch()
        cancel = QPushButton("취소하고 수정하기")
        cancel.clicked.connect(self.reject)
        go = QPushButton("그대로 내보내기")
        go.setObjectName("primaryBtn")
        go.setDefault(True)
        go.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(go)
        layout.addLayout(bar)

    def skip_future(self) -> bool:
        return self.skip_check.isChecked()
