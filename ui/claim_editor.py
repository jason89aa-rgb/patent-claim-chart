"""좌측 청구항 에디터 패널 - 탭별 청구항, 구성요소 분할, 색상 표시, 매칭 용어."""
import html
import os
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTextEdit, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QComboBox, QMessageBox, QSplitter,
    QToolButton, QMenu, QSizePolicy, QScrollArea, QFrame,
    QCheckBox, QSpinBox, QFileDialog, QApplication, QProgressDialog
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtGui import (QColor, QFont, QIcon, QPainter, QPixmap, QAction,
                         QTextCharFormat, QTextCursor)

from core.project import Claim, ClaimElement, ClaimTerm
from core.claim_parser import parse_claim
from core.claims_extractor import (ExtractedClaim,
                                   diagnose_extraction_failure)
from utils.color_utils import (generate_colors, rgb_to_hex, get_text_color,
                               term_color)



def highlight_terms_html(text: str, terms: list[ClaimTerm]) -> str:
    """텍스트 내 용어를 색상 span으로 감싼 HTML 반환 (대소문자 무시)."""
    valid = [t for t in terms if t.text.strip()]
    if not valid:
        return html.escape(text)
    # 긴 용어 우선 매칭 ("power line unit" > "power line")
    valid.sort(key=lambda t: -len(t.text))
    pattern = "|".join(re.escape(t.text) for t in valid)
    out = []
    last = 0
    for m in re.finditer(pattern, text, re.IGNORECASE):
        out.append(html.escape(text[last:m.start()]))
        matched = m.group(0)
        term = next((t for t in valid
                     if t.text.lower() == matched.lower()), valid[0])
        rgb = tuple(term.color_rgb)
        out.append(f'<span style="background:{rgb_to_hex(rgb)}; '
                   f'color:{get_text_color(rgb)}; border-radius:2px;">'
                   f'{html.escape(matched)}</span>')
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


class ElementCard(QFrame):
    """구성요소 하나를 카드 형태로 표시."""
    delete_requested = pyqtSignal(str)
    selected = pyqtSignal(str)  # element_id

    def __init__(self, elem: ClaimElement, terms: list[ClaimTerm] = None,
                 parent=None):
        super().__init__(parent)
        self.elem = elem
        self._terms = terms or []
        self._is_selected = False
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        rgb = tuple(self.elem.color_rgb)
        hex_color = rgb_to_hex(rgb)
        txt_color = get_text_color(rgb)

        self.setStyleSheet(f"""
            ElementCard {{
                border: 2px solid {hex_color};
                border-radius: 10px;
                padding: 4px;
                margin: 2px 0px;
                background: rgba({rgb[0]},{rgb[1]},{rgb[2]}, 25);
            }}
            ElementCard:hover {{
                background: rgba({rgb[0]},{rgb[1]},{rgb[2]}, 50);
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # 색상 라벨 배지
        self.label_btn = QPushButton(self.elem.element_id)
        self.label_btn.setFixedSize(44, 28)
        self.label_btn.setStyleSheet(
            f"background:{hex_color}; color:{txt_color}; "
            f"border-radius:8px; font-weight:bold; font-size:11px; border:none;")
        self.label_btn.clicked.connect(lambda: self.selected.emit(self.elem.element_id))
        layout.addWidget(self.label_btn)

        # 텍스트 (최대 3줄, 매칭 용어 색상 강조)
        self.text_label = QLabel()
        self.text_label.setTextFormat(Qt.TextFormat.RichText)
        self.text_label.setText(highlight_terms_html(self.elem.text,
                                                     self._terms))
        self.text_label.setWordWrap(True)
        self.text_label.setFont(QFont("맑은 고딕", 9))
        self.text_label.setMaximumHeight(60)
        self.text_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.text_label, stretch=1)

        # 삭제
        del_btn = QToolButton()
        del_btn.setText("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet("border: none; color: #888; font-size: 12px;")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.elem.element_id))
        layout.addWidget(del_btn)

    def set_highlight(self, on: bool):
        rgb = tuple(self.elem.color_rgb)
        hex_color = rgb_to_hex(rgb)
        alpha = 80 if on else 25
        border_w = 3 if on else 2
        self.setStyleSheet(f"""
            ElementCard {{
                border: {border_w}px solid {hex_color};
                border-radius: 10px;
                padding: 4px;
                margin: 2px 0px;
                background: rgba({rgb[0]},{rgb[1]},{rgb[2]}, {alpha});
            }}
        """)


class ClaimTab(QWidget):
    """단일 청구항 탭."""
    elements_changed = pyqtSignal()
    element_selected = pyqtSignal(str)  # element_id
    term_add_requested = pyqtSignal(str)  # 선택된 용어 텍스트
    terms_add_requested = pyqtSignal(list)  # 여러 용어 일괄 등록
    claims_split_requested = pyqtSignal(list)  # 여러 청구항 → 탭 분리 요청

    def __init__(self, claim: Claim, parent=None):
        super().__init__(parent)
        self.claim = claim
        self._terms: list[ClaimTerm] = []
        self._setup_ui()
        self._refresh_elements()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # 상단 버튼바
        btn_bar = QHBoxLayout()

        parse_btn = QPushButton("자동 분할")
        parse_btn.setToolTip(
            "청구항 = 도입부(preamble) + 연결부(transition) + 구성요소부(elements).\n"
            "구성요소부를 구성요소(1A, 1B...) 단위로 자동 분할합니다.")
        parse_btn.setStyleSheet("font-weight: bold; padding: 5px 12px;")
        parse_btn.clicked.connect(self._auto_parse)
        btn_bar.addWidget(parse_btn)

        add_elem_btn = QPushButton("+ 요소 추가")
        add_elem_btn.setToolTip("구성요소를 수동으로 추가합니다")
        add_elem_btn.clicked.connect(self._add_element_manual)
        btn_bar.addWidget(add_elem_btn)

        term_extract_btn = QPushButton("요소 추출")
        term_extract_btn.setToolTip(
            "구성요소부에서 요소(Element) 후보(power line, via hole 등)를\n"
            "자동 추출합니다. 요소를 수식하는 나머지 문구가 제한조건(Limitation)입니다.\n"
            "선택한 요소는 청구항과 대응부분에서 같은 색으로 표시됩니다.")
        term_extract_btn.setStyleSheet("font-weight: bold; padding: 5px 12px;")
        term_extract_btn.clicked.connect(self._extract_terms)
        btn_bar.addWidget(term_extract_btn)

        term_btn = QPushButton("요소 지정")
        term_btn.setToolTip(
            "청구항 전문에서 드래그로 선택한 요소(Element)를 매칭 요소로 등록합니다.\n"
            "같은 요소는 청구항과 선행문헌·표준에서 같은 색으로 표시됩니다.")
        term_btn.clicked.connect(self._add_term_from_selection)
        btn_bar.addWidget(term_btn)

        btn_bar.addStretch()

        # 종속항 설정
        self.dep_check = QCheckBox("종속항")
        self.dep_check.setChecked(not self.claim.is_independent)
        self.dep_check.toggled.connect(self._on_dep_toggled)
        btn_bar.addWidget(self.dep_check)

        self.parent_spin = QSpinBox()
        self.parent_spin.setMinimum(1)
        self.parent_spin.setMaximum(99)
        self.parent_spin.setPrefix("← 청구항 ")
        self.parent_spin.setValue(self.claim.parent_claim or 1)
        self.parent_spin.setVisible(not self.claim.is_independent)
        self.parent_spin.setFixedWidth(110)
        btn_bar.addWidget(self.parent_spin)

        layout.addLayout(btn_bar)

        # 원문 에디터
        text_header = QLabel("청구항 전문:")
        text_header.setStyleSheet("font-weight: bold;")
        layout.addWidget(text_header)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "여기에 청구항 전문을 붙여넣기 하세요.\n\n"
            "예: An apparatus comprising:\n"
            "  a first component configured to...;\n"
            "  a second component coupled to...;\n"
            "  wherein the first component...\n\n"
            "'자동 분할' 버튼을 누르면 세미콜론(;) 기준으로\n"
            "구성요소가 자동 분리됩니다.")
        self.text_edit.setFont(QFont("맑은 고딕", 10))
        self.text_edit.setMinimumHeight(100)
        self.text_edit.setMaximumHeight(200)
        self.text_edit.setText(self.claim.full_text)
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit)

        # 구성요소 헤더
        elem_header = QHBoxLayout()
        elem_label = QLabel("구성요소부:")
        elem_label.setStyleSheet("font-weight: bold;")
        elem_label.setToolTip(
            "구성요소부(elements): 청구항 도입부·연결부 뒤의 본문.\n"
            "각 구성요소는 요소(Element) + 제한조건(Limitation)으로 이루어집니다.")
        elem_header.addWidget(elem_label)
        self.elem_count_label = QLabel("0개")
        self.elem_count_label.setStyleSheet("color: #888;")
        elem_header.addWidget(self.elem_count_label)
        elem_header.addStretch()
        layout.addLayout(elem_header)

        # 구성요소 스크롤 영역
        self.elem_scroll = QScrollArea()
        self.elem_scroll.setWidgetResizable(True)
        self.elem_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.elem_container = QWidget()
        self.elem_layout = QVBoxLayout(self.elem_container)
        self.elem_layout.setSpacing(3)
        self.elem_layout.setContentsMargins(0, 0, 0, 0)
        self.elem_layout.addStretch()
        self.elem_scroll.setWidget(self.elem_container)
        layout.addWidget(self.elem_scroll, stretch=1)

        # 안내 라벨
        self.hint_label = QLabel(
            "💡 Claim Chart 작성 순서\n"
            "  ① '자동 분할' → 구성요소부를 구성요소(1A, 1B...)로 분리\n"
            "  ② '요소 추출' → 각 구성요소의 요소(Element)를 색상 지정\n"
            "  ③ 우측 PDF에서 대응부분(도면/문장)을 드래그해 매핑\n"
            "  ④ 같은 요소는 청구항·선행문헌에서 같은 색으로 대응 표시\n"
            "  ※ All Elements Rule: 모든 요소가 대응돼야 침해/무효 성립")
        self.hint_label.setStyleSheet(
            "color: #888; font-size: 9px; padding: 8px; "
            "border: 1px dashed #555; border-radius: 4px;")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

    def _on_text_changed(self):
        self.claim.full_text = self.text_edit.toPlainText()
        self._apply_term_highlights()

    # ------------------------------------------------- 매칭 용어

    def _add_term_from_selection(self):
        selected = self.text_edit.textCursor().selectedText().strip()
        if not selected:
            QMessageBox.information(
                self, "알림",
                "청구항 전문에서 용어로 등록할 단어/구문을\n"
                "드래그로 선택한 뒤 버튼을 눌러주세요.")
            return
        self.term_add_requested.emit(selected)

    def _extract_terms(self):
        """청구항에서 후보 용어를 자동 추출해 선택 다이얼로그 표시."""
        self.claim.full_text = self.text_edit.toPlainText()
        if not self.claim.full_text.strip() and not self.claim.elements:
            QMessageBox.information(self, "알림",
                                    "청구항 텍스트를 먼저 입력하세요.")
            return

        from core.term_extractor import extract_terms_from_claim
        from ui.term_picker_dialog import TermPickerDialog

        candidates = extract_terms_from_claim(self.claim)
        if not candidates:
            QMessageBox.information(
                self, "알림",
                "추출된 후보 용어가 없습니다.\n"
                "'용어 지정' 버튼으로 직접 드래그해서 등록해 주세요.")
            return

        dlg = TermPickerDialog(
            candidates,
            existing_terms=[t.text for t in self._terms],
            parent=self)
        if dlg.exec() != TermPickerDialog.DialogCode.Accepted:
            return
        selected = dlg.get_selected_terms()
        if selected:
            self.terms_add_requested.emit(selected)

    def set_terms(self, terms: list[ClaimTerm]):
        """프로젝트 전역 용어 목록을 받아 하이라이트 갱신."""
        self._terms = terms
        self._apply_term_highlights()
        self._refresh_elements()

    def _apply_term_highlights(self):
        """전문 에디터에서 용어 출현 위치를 색상으로 표시."""
        selections = []
        doc = self.text_edit.document()
        for term in self._terms:
            if not term.text.strip():
                continue
            rgb = tuple(term.color_rgb)
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(*rgb))
            fmt.setForeground(QColor(get_text_color(rgb)))
            cursor = QTextCursor(doc)
            while True:
                cursor = doc.find(term.text, cursor)
                if cursor.isNull():
                    break
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                selections.append(sel)
        self.text_edit.setExtraSelections(selections)

    def _on_dep_toggled(self, checked: bool):
        self.claim.is_independent = not checked
        self.parent_spin.setVisible(checked)
        if checked:
            self.claim.parent_claim = self.parent_spin.value()

    def _auto_parse(self):
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "알림", "청구항 텍스트를 먼저 입력하세요.")
            return

        # 여러 청구항을 한꺼번에 붙여넣은 경우 → 청구항별 탭으로 자동 분리
        from core.claims_extractor import extract_claims_from_text
        multi = extract_claims_from_text(text)
        if len(multi) >= 2:
            n_indep = sum(1 for c in multi if c.is_independent)
            r = QMessageBox.question(
                self, "여러 청구항 감지",
                f"입력한 텍스트에서 청구항 {len(multi)}개가 감지되었습니다.\n"
                f"(독립항 {n_indep}개, 종속항 {len(multi) - n_indep}개)\n\n"
                "청구항별 탭으로 자동 분리하고 구성요소도 나눌까요?\n\n"
                "'아니오'를 누르면 현재 탭에서 구성요소 분할만 수행합니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r == QMessageBox.StandardButton.Yes:
                self.claims_split_requested.emit(multi)
                return

        parsed = parse_claim(text, self.claim.claim_number)
        if not parsed:
            return

        colors = generate_colors(len(parsed))
        self.claim.elements = [
            ClaimElement(
                element_id=p.label,
                text=p.text,
                color_rgb=colors[i],
            )
            for i, p in enumerate(parsed)
        ]
        self._refresh_elements()
        self.elements_changed.emit()

    def _add_element_manual(self):
        """수동 구성요소 추가."""
        existing = self.claim.elements
        n = len(existing) + 1
        from utils.color_utils import generate_colors
        colors = generate_colors(n)
        # 기존 요소 색상은 유지하고, 새 요소에 마지막 색상 배정
        label = f"{self.claim.claim_number}"
        suffix = ""
        tmp = n - 1
        while True:
            suffix = chr(ord('A') + tmp % 26) + suffix
            tmp = tmp // 26 - 1
            if tmp < 0:
                break
        label += suffix

        new_elem = ClaimElement(
            element_id=label,
            text="(여기에 구성요소 텍스트를 입력하세요)",
            color_rgb=colors[-1],
        )
        self.claim.elements.append(new_elem)
        self._refresh_elements()
        self.elements_changed.emit()

    def _refresh_elements(self):
        # 기존 위젯 제거
        while self.elem_layout.count() > 1:
            item = self.elem_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for elem in self.claim.elements:
            card = ElementCard(elem, terms=self._terms)
            card.delete_requested.connect(self._delete_element)
            card.selected.connect(self.element_selected)
            self.elem_layout.insertWidget(self.elem_layout.count() - 1, card)

        self.elem_count_label.setText(f"{len(self.claim.elements)}개")
        self.hint_label.setVisible(len(self.claim.elements) == 0)

    def _delete_element(self, element_id: str):
        self.claim.elements = [e for e in self.claim.elements
                               if e.element_id != element_id]
        self._refresh_elements()
        self.elements_changed.emit()

    def get_claim(self) -> Claim:
        self.claim.full_text = self.text_edit.toPlainText()
        self.claim.is_independent = not self.dep_check.isChecked()
        if self.dep_check.isChecked():
            self.claim.parent_claim = self.parent_spin.value()
        return self.claim

    def reload(self, claim: Claim):
        self.claim = claim
        self.text_edit.blockSignals(True)
        self.text_edit.setText(claim.full_text)
        self.text_edit.blockSignals(False)
        self.dep_check.setChecked(not claim.is_independent)
        if claim.parent_claim:
            self.parent_spin.setValue(claim.parent_claim)
        self._refresh_elements()


class ClaimEditorPanel(QWidget):
    """좌측 청구항 에디터 전체 패널."""
    claim_changed = pyqtSignal()
    element_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._terms: list[ClaimTerm] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 탭바 + 추가/삭제 버튼
        top_bar = QHBoxLayout()
        title = QLabel("청구항 관리")
        title.setStyleSheet("font-weight: bold; font-size: 12px;")
        top_bar.addWidget(title)

        add_claim_btn = QPushButton("+ 청구항 추가")
        add_claim_btn.clicked.connect(self._add_claim)
        top_bar.addWidget(add_claim_btn)

        del_claim_btn = QPushButton("삭제")
        del_claim_btn.clicked.connect(self._del_claim)
        top_bar.addWidget(del_claim_btn)

        import_btn = QPushButton("PDF 가져오기")
        import_btn.setToolTip(
            "특허 PDF에서 청구범위를 자동 추출해서 청구항을 채웁니다")
        import_btn.clicked.connect(lambda: self.import_claims_from_pdf())
        top_bar.addWidget(import_btn)

        top_bar.addStretch()
        layout.addLayout(top_bar)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(False)
        layout.addWidget(self.tab_widget)

        # 매칭 요소(Element) 섹션
        term_header = QHBoxLayout()
        term_title = QLabel("매칭 요소 (Element)")
        term_title.setStyleSheet("font-weight: bold;")
        term_title.setToolTip(
            "청구항 요소(Element)와 선행문헌·표준에서 대응되는 부분.\n"
            "같은 요소는 양쪽에서 같은 색으로 표시됩니다.\n"
            "요소를 수식하는 문구는 제한조건(Limitation)입니다.")
        term_header.addWidget(term_title)
        self.term_count_label = QLabel("0개")
        self.term_count_label.setStyleSheet("color: #888;")
        term_header.addWidget(self.term_count_label)
        term_header.addStretch()
        term_del_btn = QPushButton("용어 삭제")
        term_del_btn.clicked.connect(self._delete_selected_term)
        term_header.addWidget(term_del_btn)
        layout.addLayout(term_header)

        self.term_list = QListWidget()
        self.term_list.setFlow(QListWidget.Flow.LeftToRight)
        self.term_list.setWrapping(True)
        self.term_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.term_list.setMaximumHeight(78)
        self.term_list.setToolTip("더블클릭으로 용어를 삭제할 수 있습니다")
        self.term_list.itemDoubleClicked.connect(
            lambda item: self._delete_term(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.term_list)

    def _connect_tab(self, tab: ClaimTab):
        tab.elements_changed.connect(self.claim_changed)
        tab.element_selected.connect(self.element_selected)
        tab.term_add_requested.connect(self._add_term)
        tab.terms_add_requested.connect(self.add_terms)
        tab.claims_split_requested.connect(self._split_claims_into_tabs)
        tab.set_terms(self._terms)

    def load_claims(self, claims: list[Claim]):
        self.tab_widget.clear()
        for claim in claims:
            tab = ClaimTab(claim)
            self._connect_tab(tab)
            self.tab_widget.addTab(tab, f"청구항 {claim.claim_number}")

    def get_claims(self) -> list[Claim]:
        result = []
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, ClaimTab):
                result.append(tab.get_claim())
        return result

    def get_current_claim(self) -> Claim | None:
        tab = self.tab_widget.currentWidget()
        if isinstance(tab, ClaimTab):
            return tab.get_claim()
        return None

    def _add_claim(self):
        existing = self.get_claims()
        next_num = max((c.claim_number for c in existing), default=0) + 1
        new_claim = Claim(claim_number=next_num, is_independent=True)
        tab = ClaimTab(new_claim)
        self._connect_tab(tab)
        self.tab_widget.addTab(tab, f"청구항 {next_num}")
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)
        self.claim_changed.emit()

    def _del_claim(self):
        idx = self.tab_widget.currentIndex()
        if idx < 0:
            return
        if self.tab_widget.count() <= 1:
            QMessageBox.warning(self, "삭제 불가", "청구항이 최소 1개 이상 있어야 합니다.")
            return
        reply = QMessageBox.question(
            self, "삭제 확인",
            "현재 탭의 청구항을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.tab_widget.removeTab(idx)
            self.claim_changed.emit()

    # ------------------------------------------ PDF에서 청구항 가져오기

    def import_claims_from_pdf(self, pdf_path: str | None = None):
        """특허 PDF에서 청구범위를 추출해 청구항 탭으로 가져온다.

        추출은 QProcess(별도 프로세스)로 실행 — QThread도 중첩 이벤트루프도
        쓰지 않는다. (모달 QProgressDialog.setValue가 내부적으로
        processEvents를 호출하므로, 중첩 QEventLoop와 결합하면 프리즈
        환경에서 재진입 크래시가 났다. 메인 루프 시그널만 사용하면 안전.)
        """
        if not pdf_path:
            pdf_path, _ = QFileDialog.getOpenFileName(
                self, "특허 PDF 선택", "",
                "PDF 파일 (*.pdf);;모든 파일 (*.*)")
            if not pdf_path:
                return
        if getattr(self, "_ext", None):      # 이미 추출 진행 중
            return

        import sys
        import tempfile
        from PyQt6.QtCore import QProcess, QProcessEnvironment

        fd, out_path = tempfile.mkstemp(suffix=".json",
                                        prefix="pcc_claims_")
        os.close(fd)

        progress = QProgressDialog(
            "PDF에서 청구범위 추출 중...\n(추출 엔진 시작 중)", "취소",
            0, 0, self)
        progress.setWindowTitle("청구항 가져오기")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        proc = QProcess(self)
        if getattr(sys, "frozen", False):
            program = sys.executable
            args = ["--extract-claims", pdf_path, out_path]
            # onefile 자기실행: 자식을 독립 인스턴스로 (부모 _MEI 보호)
            env = QProcessEnvironment.systemEnvironment()
            for key in list(env.keys()):
                if key.startswith("_PYI") or key.startswith("_MEIPASS"):
                    env.remove(key)
            env.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
            # 부모의 언어팩 경로(부모 임시폴더)를 물려주지 않는다 —
            # 자식이 자기 번들에서 다시 찾아야 한다
            env.remove("TESSDATA_PREFIX")
            proc.setProcessEnvironment(env)
        else:
            program = sys.executable
            main_py = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "main.py")
            args = ["-X", "utf8", main_py,
                    "--extract-claims", pdf_path, out_path]

        self._ext = {
            "proc": proc, "progress": progress, "out": out_path,
            "pdf": pdf_path, "buf": "", "err": None,
            "done": False, "canceled": False,
        }
        proc.readyReadStandardOutput.connect(self._on_extract_output)
        proc.finished.connect(self._on_extract_finished)
        proc.errorOccurred.connect(self._on_extract_proc_error)
        progress.canceled.connect(self._cancel_extract)

        proc.start(program, args)
        progress.show()

    def _on_extract_output(self):
        st = getattr(self, "_ext", None)
        if not st:
            return
        data = bytes(st["proc"].readAllStandardOutput())
        st["buf"] += data.decode("utf-8", errors="replace")
        while "\n" in st["buf"]:
            line, st["buf"] = st["buf"].split("\n", 1)
            line = line.strip()
            if line.startswith("PROGRESS "):
                try:
                    _, cur, total = line.split()
                    cur, total = int(cur), int(total)
                except ValueError:
                    continue
                p = st["progress"]
                p.setMaximum(total)
                p.setValue(cur)
                p.setLabelText(
                    f"스캔본 OCR: 뒤쪽부터 {cur}페이지 읽는 중 "
                    f"(전체 {total}페이지)\n"
                    "청구범위를 찾으면 자동으로 중단합니다.")
            elif line == "DONE":
                st["done"] = True
            elif line.startswith("ERROR "):
                st["err"] = line[6:]

    def _cancel_extract(self):
        st = getattr(self, "_ext", None)
        if st:
            st["canceled"] = True
            st["proc"].kill()

    def _on_extract_proc_error(self, _error):
        st = getattr(self, "_ext", None)
        if st and not st["canceled"] and st["err"] is None:
            st["err"] = "추출 프로세스를 시작하거나 실행하지 못했습니다."

    def _on_extract_finished(self, exit_code, _status):
        st = getattr(self, "_ext", None)
        if not st:
            return
        self._ext = None
        st["progress"].close()
        st["proc"].deleteLater()
        pdf_path = st["pdf"]
        out_path = st["out"]

        try:
            if st["canceled"]:
                return
            if st["err"]:
                QMessageBox.warning(self, "추출 실패", st["err"])
                return
            if not st["done"] or exit_code != 0:
                QMessageBox.warning(
                    self, "추출 실패",
                    f"PDF 처리 엔진이 비정상 종료했습니다 (코드 {exit_code}).\n"
                    "손상되었거나 지원되지 않는 PDF일 수 있습니다.\n"
                    "다른 PDF로 시도하거나 청구항을 직접 붙여넣어 주세요.")
                return

            import json
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                extracted = [ExtractedClaim(**{
                    k: v for k, v in c.items()
                    if k in ExtractedClaim.__dataclass_fields__
                }) for c in raw]
            except Exception as e:
                QMessageBox.warning(self, "추출 실패",
                                    f"추출 결과를 읽지 못했습니다: {e}")
                return

            if not extracted:
                QMessageBox.warning(self, "추출 실패",
                                    diagnose_extraction_failure(pdf_path))
                return
            self._show_import_dialog(extracted, pdf_path)
        finally:
            try:
                os.remove(out_path)
            except OSError:
                pass

    def _show_import_dialog(self, extracted: list, pdf_path: str):
        """추출된 청구항 선택 다이얼로그 → 탭 구성."""
        from ui.claims_import_dialog import ClaimsImportDialog
        dlg = ClaimsImportDialog(extracted, pdf_path, parent=self)
        if dlg.exec() != ClaimsImportDialog.DialogCode.Accepted:
            return
        selected = dlg.get_selected_claims()
        if not selected:
            QMessageBox.information(self, "알림", "선택된 청구항이 없습니다.")
            return

        new_claims = self._build_claims_from_extracted(
            selected, auto_split=dlg.auto_split_enabled())

        if dlg.replace_mode():
            self.load_claims(new_claims)
        else:
            for claim in new_claims:
                tab = ClaimTab(claim)
                self._connect_tab(tab)
                self.tab_widget.addTab(tab, f"청구항 {claim.claim_number}")
        self.claim_changed.emit()

    def _build_claims_from_extracted(self, extracted: list,
                                     auto_split: bool = True) -> list[Claim]:
        """ExtractedClaim 리스트 → Claim 객체 리스트 (구성요소 분할 포함)."""
        new_claims = []
        for ec in extracted:
            claim = Claim(
                claim_number=ec.number,
                is_independent=ec.is_independent,
                parent_claim=ec.parent_claim,
                full_text=ec.text,
            )
            if auto_split:
                parsed = parse_claim(ec.text, ec.number)
                colors = generate_colors(len(parsed))
                claim.elements = [
                    ClaimElement(
                        element_id=p.label,
                        text=p.text,
                        color_rgb=colors[i],
                    )
                    for i, p in enumerate(parsed)
                ]
            new_claims.append(claim)
        return new_claims

    def _split_claims_into_tabs(self, extracted: list):
        """텍스트로 붙여넣은 여러 청구항을 청구항별 탭으로 분리."""
        if not extracted:
            return
        new_claims = self._build_claims_from_extracted(extracted,
                                                       auto_split=True)
        self.load_claims(new_claims)
        self.tab_widget.setCurrentIndex(0)
        self.claim_changed.emit()

    # ------------------------------------------ 매칭 용어 관리

    def set_terms(self, terms: list[ClaimTerm]):
        """프로젝트의 용어 리스트(참조)를 설정하고 UI 갱신."""
        self._terms = terms
        self._refresh_term_ui()

    def get_terms(self) -> list[ClaimTerm]:
        return self._terms

    def _next_term_num(self) -> int:
        """삭제된 번호는 재사용하지 않는다 (기존 용어 색 안정)."""
        max_num = 0
        for t in self._terms:
            m = re.match(r'T(\d+)$', t.term_id)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return max_num + 1

    def ensure_term(self, text: str) -> str:
        """용어를 등록하고 term_id 반환. 이미 있으면 기존 id 반환."""
        text = text.strip()
        if not text:
            return ""
        for t in self._terms:
            if t.text.lower() == text.lower():
                return t.term_id
        num = self._next_term_num()
        term_id = f"T{num}"
        self._terms.append(ClaimTerm(
            term_id=term_id,
            text=text,
            color_rgb=term_color(num - 1),
        ))
        return term_id

    def add_alias(self, term_id: str, text: str) -> bool:
        """선행문헌 쪽 표기를 기존 용어의 별칭으로 등록 (같은 색으로 표시)."""
        text = (text or "").strip()
        if not text or not term_id:
            return False
        for t in self._terms:
            if t.term_id != term_id:
                continue
            existing = [t.text] + list(t.aliases or [])
            if any((e or "").lower() == text.lower() for e in existing):
                return False
            t.aliases = list(t.aliases or []) + [text]
            self._refresh_term_ui()
            self.claim_changed.emit()
            return True
        return False

    def add_terms(self, texts: list[str]):
        """여러 용어 일괄 등록."""
        added = 0
        for text in texts:
            before = len(self._terms)
            self.ensure_term(text)
            if len(self._terms) > before:
                added += 1
        if added:
            self._refresh_term_ui()
            self.claim_changed.emit()

    def _add_term(self, text: str):
        text = text.strip()
        if not text:
            return
        if any(t.text.lower() == text.lower() for t in self._terms):
            QMessageBox.information(self, "알림",
                                    f'"{text}" 은(는) 이미 등록된 용어입니다.')
            return
        self.ensure_term(text)
        self._refresh_term_ui()
        self.claim_changed.emit()

    def _delete_term(self, term_id: str):
        if not term_id:
            return
        self._terms[:] = [t for t in self._terms if t.term_id != term_id]
        self._refresh_term_ui()
        self.claim_changed.emit()

    def _delete_selected_term(self):
        item = self.term_list.currentItem()
        if not item:
            QMessageBox.information(self, "알림",
                                    "삭제할 용어를 목록에서 선택해 주세요.")
            return
        self._delete_term(item.data(Qt.ItemDataRole.UserRole))

    def _refresh_term_ui(self):
        # 칩 목록 갱신
        self.term_list.clear()
        for t in self._terms:
            rgb = tuple(t.color_rgb)
            aliases = [a for a in (t.aliases or []) if (a or "").strip()]
            label = f" {t.term_id}  {t.text} "
            if aliases:
                label += f"= {' / '.join(aliases)} "
            item = QListWidgetItem(label)
            item.setBackground(QColor(*rgb))
            item.setForeground(QColor(get_text_color(rgb)))
            item.setData(Qt.ItemDataRole.UserRole, t.term_id)
            tip = f"{t.term_id}: {t.text}"
            if aliases:
                tip += "\n선행문헌 표기: " + ", ".join(aliases)
            item.setToolTip(tip + "\n(더블클릭으로 삭제)")
            self.term_list.addItem(item)
        self.term_count_label.setText(f"{len(self._terms)}개")

        # 모든 탭 하이라이트 갱신
        for i in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(i)
            if isinstance(tab, ClaimTab):
                tab.set_terms(self._terms)

    def get_all_elements_flat(self) -> list[tuple[int, ClaimElement]]:
        result = []
        for claim in self.get_claims():
            for elem in claim.elements:
                result.append((claim.claim_number, elem))
        return result
