"""매핑 연결 다이얼로그 및 매핑 목록 패널."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QTextEdit, QDialogButtonBox,
    QPushButton, QWidget, QListWidget, QListWidgetItem,
    QMessageBox, QGroupBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor

from core.project import MappingEntry, Claim, ClaimElement, ClaimTerm
from utils.color_utils import rgb_to_hex, get_text_color


JUDGMENT_OPTIONS = ["미판단", "일치", "부분일치", "불일치"]
INTERPRETATION_OPTIONS = ["문언침해", "균등론", "넓게해석", "좁게해석"]

INTERPRETATION_DESC = {
    "문언침해": "Lit. — 청구항 문언 그대로 침해",
    "균등론":   "DOE — 균등한 방식으로 침해",
    "넓게해석": "Broad — 선행문헌과 겹치도록 넓게 해석 (무효 주장)",
    "좁게해석": "Narrow — 회피 불가하도록 좁게 해석 (침해 주장)",
}

JUDGMENT_COLORS = {
    "일치":    "#2E862E",
    "부분일치": "#FFA500",
    "불일치":  "#CC2222",
    "미판단":  "#888888",
}


class MappingDialog(QDialog):
    """선택 영역을 청구항 구성요소와 연결하는 다이얼로그."""

    def __init__(self, claims: list[Claim],
                 doc_path: str, page: int, rect: list,
                 extracted_text: str = "",
                 existing: MappingEntry = None,
                 terms: list[ClaimTerm] = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("매핑 연결")
        self.setMinimumWidth(520)
        self._claims = claims
        self._terms = terms or []
        self._doc_path = doc_path
        self._page = page
        self._rect = rect
        self._existing = existing
        self._setup_ui(extracted_text)

    def _setup_ui(self, extracted_text: str):
        layout = QVBoxLayout(self)

        # 선행문헌 정보
        info_group = QGroupBox("선행문헌 정보")
        info_form = QFormLayout(info_group)
        import os
        info_form.addRow("파일:", QLabel(os.path.basename(self._doc_path)))
        info_form.addRow("페이지:", QLabel(str(self._page + 1)))
        layout.addWidget(info_group)

        # 추출 텍스트
        text_group = QGroupBox("선택 영역 텍스트")
        text_layout = QVBoxLayout(text_group)
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(extracted_text)
        self.text_edit.setMaximumHeight(120)
        self.text_edit.setFont(QFont("맑은 고딕", 9))
        text_layout.addWidget(self.text_edit)

        # 단어별 요소 색칠 도구: 텍스트에서 단어를 드래그한 뒤 요소 색 적용
        hl_bar = QHBoxLayout()
        hl_bar.addWidget(QLabel("단어 색칠:"))
        self.hl_term_combo = QComboBox()
        for t in self._terms:
            self.hl_term_combo.addItem(f"{t.term_id}: {t.text}", t.term_id)
            idx = self.hl_term_combo.count() - 1
            self.hl_term_combo.setItemData(
                idx, QColor(*t.color_rgb), Qt.ItemDataRole.DecorationRole)
        self.hl_term_combo.setToolTip(
            "위 텍스트에서 요소에 대응되는 단어를 드래그한 뒤\n"
            "'적용'을 누르면 그 단어만 요소 색으로 칠해집니다.\n"
            "(요소는 청구항 패널의 '요소 추출/지정'으로 먼저 등록)")
        hl_bar.addWidget(self.hl_term_combo, stretch=1)
        hl_apply_btn = QPushButton("적용")
        hl_apply_btn.setFixedWidth(58)
        hl_apply_btn.setToolTip("드래그한 단어에 선택한 요소 색을 적용")
        hl_apply_btn.clicked.connect(self._apply_term_highlight)
        hl_bar.addWidget(hl_apply_btn)
        hl_clear_btn = QPushButton("지우기")
        hl_clear_btn.setFixedWidth(68)
        hl_clear_btn.setToolTip("드래그한 부분의 색을 지움 (선택 없으면 전체)")
        hl_clear_btn.clicked.connect(self._clear_term_highlight)
        hl_bar.addWidget(hl_clear_btn)
        text_layout.addLayout(hl_bar)

        if not self._terms:
            self.hl_term_combo.addItem("(등록된 요소 없음)", "")
            self.hl_term_combo.setEnabled(False)

        layout.addWidget(text_group)

        # 기존 매핑 편집 시 저장된 단어 색칠 복원
        if self._existing and getattr(self._existing, "term_spans", None):
            self._restore_term_spans(self._existing.term_spans)

        # 매핑 설정
        map_group = QGroupBox("매핑 설정")
        map_form = QFormLayout(map_group)

        # 청구항 선택
        self.claim_combo = QComboBox()
        for c in self._claims:
            self.claim_combo.addItem(f"청구항 {c.claim_number}", c.claim_number)
        self.claim_combo.currentIndexChanged.connect(self._on_claim_changed)
        map_form.addRow("청구항:", self.claim_combo)

        # 구성요소 선택 (복수 선택 가능 - 한 도면/문장에 여러 구성요소 대응)
        self.elem_list = QListWidget()
        self.elem_list.setMaximumHeight(110)
        self.elem_list.setToolTip(
            "이 도면/문장에 대응되는 구성요소를 모두 체크하세요.\n"
            "여러 개 체크하면 각각 매핑이 생성되고, 색상이 함께 표시됩니다.")
        map_form.addRow("구성요소:", self.elem_list)

        # 매칭 용어 선택: 등록된 용어 + 청구항에서 추출한 후보 용어
        self.term_combo = QComboBox()
        map_form.addRow("매칭 용어:", self.term_combo)

        term_hint = QLabel(
            "선택한 선행문헌 영역(예: VDDL)이 청구항의 어떤 용어에 대응하는지 "
            "고르면 양쪽이 같은 색으로 표시됩니다.")
        term_hint.setStyleSheet("color: #666; font-size: 9px;")
        term_hint.setWordWrap(True)
        map_form.addRow("", term_hint)

        # 판단
        self.judgment_combo = QComboBox()
        self.judgment_combo.addItems(JUDGMENT_OPTIONS)
        self.judgment_combo.currentTextChanged.connect(self._update_judgment_color)
        map_form.addRow("판단:", self.judgment_combo)

        # 해석강도
        self.interp_combo = QComboBox()
        self.interp_combo.addItems(INTERPRETATION_OPTIONS)
        self.interp_combo.currentTextChanged.connect(self._update_interp_desc)
        map_form.addRow("해석강도:", self.interp_combo)

        # 해석강도 설명
        self.interp_desc_label = QLabel()
        self.interp_desc_label.setStyleSheet("color: #666; font-size: 9px;")
        self.interp_desc_label.setWordWrap(True)
        map_form.addRow("", self.interp_desc_label)

        # 비고
        self.note_edit = QTextEdit()
        self.note_edit.setMaximumHeight(60)
        self.note_edit.setPlaceholderText("매핑 비고...")
        map_form.addRow("비고:", self.note_edit)

        layout.addWidget(map_group)

        # 기존 값 복원
        if self._existing:
            for i in range(self.claim_combo.count()):
                if self.claim_combo.itemData(i) == self._existing.claim_number:
                    self.claim_combo.setCurrentIndex(i)
                    break
            self._on_claim_changed()
            for i in range(self.elem_list.count()):
                item = self.elem_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == \
                        self._existing.element_id:
                    item.setCheckState(Qt.CheckState.Checked)
                    break
            if self._existing.term_id:
                for i in range(self.term_combo.count()):
                    data = self.term_combo.itemData(i)
                    if data and data[0] == "id" and \
                            data[1] == self._existing.term_id:
                        self.term_combo.setCurrentIndex(i)
                        break
            idx_j = JUDGMENT_OPTIONS.index(self._existing.judgment) \
                if self._existing.judgment in JUDGMENT_OPTIONS else 0
            self.judgment_combo.setCurrentIndex(idx_j)
            idx_i = INTERPRETATION_OPTIONS.index(self._existing.interpretation) \
                if self._existing.interpretation in INTERPRETATION_OPTIONS else 0
            self.interp_combo.setCurrentIndex(idx_i)
            self.note_edit.setPlainText(self._existing.note)
        else:
            self._on_claim_changed()

        self._update_interp_desc(self.interp_combo.currentText())

        # 버튼
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryBtn")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_claim_changed(self):
        self._refresh_elements()
        self._refresh_terms()

    def _refresh_elements(self):
        claim_num = self.claim_combo.currentData()
        self.elem_list.clear()
        claim = next((c for c in self._claims if c.claim_number == claim_num), None)
        if not claim:
            return
        for elem in claim.elements:
            item = QListWidgetItem(f"{elem.element_id}: {elem.text[:50]}...")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, elem.element_id)
            rgb = tuple(elem.color_rgb)
            item.setBackground(QColor(*rgb, 60))
            self.elem_list.addItem(item)

    def _refresh_terms(self):
        """등록된 용어 + 현재 청구항에서 추출한 미등록 후보 용어를 채운다.

        itemData 형식: ("id", term_id) 또는 ("new", 용어 텍스트)
        """
        self.term_combo.clear()
        self.term_combo.addItem("(없음 - 구성요소 색 사용)", ("", ""))

        for t in self._terms:
            self.term_combo.addItem(f"{t.term_id}: {t.text}", ("id", t.term_id))
            idx = self.term_combo.count() - 1
            self.term_combo.setItemData(
                idx, QColor(*t.color_rgb), Qt.ItemDataRole.DecorationRole)

        # 현재 청구항의 미등록 후보 용어
        claim_num = self.claim_combo.currentData()
        claim = next((c for c in self._claims
                      if c.claim_number == claim_num), None)
        if not claim:
            return
        from core.term_extractor import extract_terms_from_claim
        registered = {t.text.lower() for t in self._terms}
        candidates = [c for c in extract_terms_from_claim(claim)
                      if c.text.lower() not in registered]
        if not candidates:
            return

        sep_idx = self.term_combo.count()
        self.term_combo.addItem("── 청구항 용어 (선택 시 등록) ──", ("", ""))
        model = self.term_combo.model()
        model.item(sep_idx).setEnabled(False)
        for c in candidates:
            self.term_combo.addItem(f"+ {c.text}  ({c.count}회)",
                                    ("new", c.text))

    # ---------------------------------------------- 단어별 요소 색칠

    def _term_by_id(self, term_id: str):
        return next((t for t in self._terms if t.term_id == term_id), None)

    def _apply_term_highlight(self):
        """드래그한 단어에 선택한 요소 색을 적용."""
        term = self._term_by_id(self.hl_term_combo.currentData())
        if not term:
            return
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            QMessageBox.information(
                self, "알림",
                "먼저 위 텍스트에서 색칠할 단어를 드래그로 선택하세요.")
            return
        rgb = tuple(term.color_rgb)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(*rgb))
        fmt.setForeground(QColor(get_text_color(rgb)))
        fmt.setFontWeight(QFont.Weight.Bold)
        cursor.mergeCharFormat(fmt)

    def _clear_term_highlight(self):
        """드래그한 부분의 색을 지움. 선택이 없으면 전체 초기화."""
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            cursor = QTextCursor(self.text_edit.document())
            cursor.select(QTextCursor.SelectionType.Document)
        cursor.setCharFormat(QTextCharFormat())

    def _restore_term_spans(self, spans: list):
        """저장된 단어 색칠([[start, end, term_id], ...])을 다시 입힌다."""
        doc = self.text_edit.document()
        length = len(self.text_edit.toPlainText())
        for s in spans or []:
            try:
                start, end, tid = int(s[0]), int(s[1]), s[2]
            except (ValueError, TypeError, IndexError):
                continue
            term = self._term_by_id(tid)
            if not term or not (0 <= start < end <= length):
                continue
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            rgb = tuple(term.color_rgb)
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(*rgb))
            fmt.setForeground(QColor(get_text_color(rgb)))
            fmt.setFontWeight(QFont.Weight.Bold)
            cursor.mergeCharFormat(fmt)

    def get_term_spans(self) -> list:
        """텍스트 박스의 배경색 서식을 스캔해 [[start, end, term_id], ...] 반환.

        서식에서 역산하므로 사용자가 텍스트를 수정해도 위치가 어긋나지 않는다.
        """
        color_to_tid = {
            rgb_to_hex(tuple(t.color_rgb)).lower(): t.term_id
            for t in self._terms
        }
        spans = []
        block = self.text_edit.document().begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    bg = frag.charFormat().background()
                    if bg.style() != Qt.BrushStyle.NoBrush:
                        tid = color_to_tid.get(bg.color().name().lower())
                        if tid:
                            spans.append(
                                [frag.position(),
                                 frag.position() + frag.length(), tid])
                it += 1
            block = block.next()

        # 인접한 같은 요소 스팬 병합
        spans.sort()
        merged: list = []
        for s in spans:
            if merged and merged[-1][2] == s[2] and merged[-1][1] >= s[0]:
                merged[-1][1] = max(merged[-1][1], s[1])
            else:
                merged.append(list(s))
        return merged

    def _update_judgment_color(self, text: str):
        color = JUDGMENT_COLORS.get(text, "#000")
        self.judgment_combo.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _update_interp_desc(self, text: str):
        self.interp_desc_label.setText(INTERPRETATION_DESC.get(text, ""))

    def get_selected_element_ids(self) -> list:
        result = []
        for i in range(self.elem_list.count()):
            item = self.elem_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def get_result(self) -> dict:
        kind, value = self.term_combo.currentData() or ("", "")
        elem_ids = self.get_selected_element_ids()
        return {
            "claim_number": self.claim_combo.currentData(),
            "element_ids": elem_ids,
            "element_id": elem_ids[0] if elem_ids else "",
            # 기존 용어 선택 시 term_id, 후보 용어 선택 시 new_term_text
            "term_id": value if kind == "id" else "",
            "new_term_text": value if kind == "new" else "",
            "term_spans": self.get_term_spans(),
            "extracted_text": self.text_edit.toPlainText(),
            "judgment": self.judgment_combo.currentText(),
            "interpretation": self.interp_combo.currentText(),
            "note": self.note_edit.toPlainText(),
        }


class MappingListPanel(QWidget):
    """매핑 목록 및 관리 패널."""
    delete_requested = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    jump_requested = pyqtSignal(str, int, list)  # doc_path, page, rect

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mappings: list[MappingEntry] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        header = QHBoxLayout()
        header.addWidget(QLabel("매핑 목록"))
        header.addStretch()
        self.progress_label = QLabel("완료: 0%")
        self.progress_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        header.addWidget(self.progress_label)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.setFont(QFont("맑은 고딕", 8))
        layout.addWidget(self.list_widget, stretch=1)

        btn_bar = QHBoxLayout()
        btn_bar.addStretch()          # 우측 정렬 (전체 폭 확장 방지)
        edit_btn = QPushButton("편집")
        edit_btn.setFixedWidth(72)
        edit_btn.clicked.connect(self._on_edit)
        del_btn = QPushButton("삭제")
        del_btn.setFixedWidth(72)
        del_btn.clicked.connect(self._on_delete)
        jump_btn = QPushButton("위치 이동")
        jump_btn.setFixedWidth(96)
        jump_btn.clicked.connect(self._on_jump)
        btn_bar.addWidget(edit_btn)
        btn_bar.addWidget(del_btn)
        btn_bar.addWidget(jump_btn)
        layout.addLayout(btn_bar)

    def refresh(self, mappings: list[MappingEntry], completion: float = 0.0):
        self._mappings = mappings
        self.list_widget.clear()
        import os
        for m in mappings:
            j_color = JUDGMENT_COLORS.get(m.judgment, "#888")
            interp_short = {"문언침해": "Lit", "균등론": "DOE",
                            "넓게해석": "Broad", "좁게해석": "Narrow"}.get(
                m.interpretation, m.interpretation[:4])
            tag = f"{m.element_id}·{m.term_id}" if m.term_id else m.element_id
            text = (f"[{tag}] {os.path.basename(m.doc_path)} "
                    f"p.{m.page+1}  {m.judgment} / {interp_short}")
            item = QListWidgetItem(text)
            item.setForeground(QColor(j_color))
            item.setData(Qt.ItemDataRole.UserRole, m.mapping_id)
            self.list_widget.addItem(item)

        self.progress_label.setText(f"완료: {completion:.0%}")

    def _current_id(self) -> str | None:
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def _on_edit(self):
        mid = self._current_id()
        if mid:
            self.edit_requested.emit(mid)

    def _on_delete(self):
        mid = self._current_id()
        if mid:
            self.delete_requested.emit(mid)

    def _on_jump(self):
        mid = self._current_id()
        if not mid:
            return
        m = next((x for x in self._mappings if x.mapping_id == mid), None)
        if m:
            self.jump_requested.emit(m.doc_path, m.page, m.rect)
