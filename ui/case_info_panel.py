"""사건 정보 패널 - 출원번호, 등록번호, 우선일, 패밀리 특허 등 메타데이터 관리."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QGroupBox, QScrollArea,
    QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont

from core.project import CaseInfo


class CaseInfoPanel(QWidget):
    changed = pyqtSignal()
    biblio_import_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._building = False
        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)

        # --- PDF에서 서지사항 가져오기 ---
        import_bar = QHBoxLayout()
        self.biblio_btn = QPushButton("PDF에서 서지사항 가져오기")
        self.biblio_btn.setObjectName("primaryBtn")
        self.biblio_btn.setToolTip(
            "특허 PDF 1페이지에서 출원번호·출원일·우선일·등록번호 등을\n"
            "자동으로 읽어 아래 항목을 채웁니다.\n"
            "적용 전에 어떤 값이 들어갈지 확인할 수 있습니다.")
        self.biblio_btn.clicked.connect(self.biblio_import_requested)
        import_bar.addWidget(self.biblio_btn)
        import_bar.addStretch()
        layout.addLayout(import_bar)

        # --- 기본 정보 ---
        basic_group = QGroupBox("기본 사건 정보")
        form = QFormLayout(basic_group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("사건/특허 제목")
        form.addRow("제목:", self.title_edit)

        self.applicant_edit = QLineEdit()
        self.applicant_edit.setPlaceholderText("출원인/특허권자")
        form.addRow("출원인:", self.applicant_edit)

        self.app_num_edit = QLineEdit()
        self.app_num_edit.setPlaceholderText("예: 10-2020-0012345")
        form.addRow("출원번호:", self.app_num_edit)

        self.reg_num_edit = QLineEdit()
        self.reg_num_edit.setPlaceholderText("예: 10-2345678")
        form.addRow("등록번호:", self.reg_num_edit)

        self.priority_date_edit = QLineEdit()
        self.priority_date_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("우선일:", self.priority_date_edit)

        self.app_date_edit = QLineEdit()
        self.app_date_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("출원일:", self.app_date_edit)

        self.reg_date_edit = QLineEdit()
        self.reg_date_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("등록일:", self.reg_date_edit)

        layout.addWidget(basic_group)

        # --- 패밀리 특허 ---
        family_group = QGroupBox("패밀리 특허")
        family_layout = QVBoxLayout(family_group)

        self.family_list = QListWidget()
        self.family_list.setMaximumHeight(120)
        family_layout.addWidget(self.family_list)

        family_input_layout = QHBoxLayout()
        self.family_input = QLineEdit()
        self.family_input.setPlaceholderText("특허번호 입력 후 추가")
        self.family_input.returnPressed.connect(self._add_family)
        add_btn = QPushButton("추가")
        add_btn.clicked.connect(self._add_family)
        del_btn = QPushButton("삭제")
        del_btn.clicked.connect(self._delete_family)
        family_input_layout.addWidget(self.family_input)
        family_input_layout.addWidget(add_btn)
        family_input_layout.addWidget(del_btn)
        family_layout.addLayout(family_input_layout)

        layout.addWidget(family_group)

        # --- 비고 ---
        notes_group = QGroupBox("비고 / 메모")
        notes_layout = QVBoxLayout(notes_group)
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(100)
        self.notes_edit.setPlaceholderText("사건 관련 메모...")
        notes_layout.addWidget(self.notes_edit)
        layout.addWidget(notes_group)

        layout.addStretch()
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # 시그널 연결
        for w in [self.title_edit, self.applicant_edit, self.app_num_edit,
                  self.reg_num_edit, self.priority_date_edit,
                  self.app_date_edit, self.reg_date_edit]:
            w.textChanged.connect(self._on_changed)
        self.notes_edit.textChanged.connect(self._on_changed)

    def _on_changed(self):
        if not self._building:
            self.changed.emit()

    def _add_family(self):
        text = self.family_input.text().strip()
        if text:
            self.family_list.addItem(text)
            self.family_input.clear()
            self.changed.emit()

    def _delete_family(self):
        row = self.family_list.currentRow()
        if row >= 0:
            self.family_list.takeItem(row)
            self.changed.emit()

    def load(self, ci: CaseInfo):
        self._building = True
        self.title_edit.setText(ci.title)
        self.applicant_edit.setText(ci.applicant)
        self.app_num_edit.setText(ci.application_number)
        self.reg_num_edit.setText(ci.registration_number)
        self.priority_date_edit.setText(ci.priority_date)
        self.app_date_edit.setText(ci.application_date)
        self.reg_date_edit.setText(ci.registration_date)
        self.notes_edit.setPlainText(ci.notes)
        self.family_list.clear()
        for fp in ci.family_patents:
            self.family_list.addItem(fp)
        self._building = False

    def current_values(self) -> dict:
        """현재 입력값 (가져오기 다이얼로그의 '현재 값' 비교용)."""
        return {
            "title": self.title_edit.text(),
            "applicant": self.applicant_edit.text(),
            "application_number": self.app_num_edit.text(),
            "registration_number": self.reg_num_edit.text(),
            "priority_date": self.priority_date_edit.text(),
            "application_date": self.app_date_edit.text(),
            "registration_date": self.reg_date_edit.text(),
            "family_patents": [self.family_list.item(i).text()
                               for i in range(self.family_list.count())],
        }

    def apply_biblio(self, values: dict):
        """PDF에서 읽은 값 중 선택된 항목만 채운다."""
        widgets = {
            "title": self.title_edit,
            "applicant": self.applicant_edit,
            "application_number": self.app_num_edit,
            "registration_number": self.reg_num_edit,
            "priority_date": self.priority_date_edit,
            "application_date": self.app_date_edit,
            "registration_date": self.reg_date_edit,
        }
        self._building = True
        for key, w in widgets.items():
            if values.get(key):
                w.setText(str(values[key]))
        if values.get("family_patents"):
            existing = {self.family_list.item(i).text()
                        for i in range(self.family_list.count())}
            for fp in values["family_patents"]:
                if fp not in existing:
                    self.family_list.addItem(fp)
        self._building = False
        self.changed.emit()

    def save_to(self, ci: CaseInfo):
        ci.title = self.title_edit.text()
        ci.applicant = self.applicant_edit.text()
        ci.application_number = self.app_num_edit.text()
        ci.registration_number = self.reg_num_edit.text()
        ci.priority_date = self.priority_date_edit.text()
        ci.application_date = self.app_date_edit.text()
        ci.registration_date = self.reg_date_edit.text()
        ci.notes = self.notes_edit.toPlainText()
        ci.family_patents = [
            self.family_list.item(i).text()
            for i in range(self.family_list.count())
        ]
