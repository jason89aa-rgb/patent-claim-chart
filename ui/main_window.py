"""메인 윈도우 - 좌우 스플리터, 메뉴바, 사건정보 패널, 자동저장."""
import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTabWidget, QLabel, QPushButton,
    QStatusBar, QMenuBar, QMenu, QFileDialog,
    QMessageBox, QDockWidget, QProgressBar, QToolBar,
    QApplication
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QAction, QKeySequence, QIcon, QFont

from core.project import (ProjectManager, Claim, ClaimElement,
                           AUTOSAVE_INTERVAL_MS)
from core.mapping_engine import MappingEngine
from ui.claim_editor import ClaimEditorPanel
from ui.pdf_viewer import PDFViewerPanel
from ui.case_info_panel import CaseInfoPanel
from ui.mapping_widget import MappingDialog, MappingListPanel
from ui.coverage_panel import CoveragePanel
from ui.search_panel import SearchPanel
from ui.prior_art_panel import PriorArtPanel
from utils.errlog import log_exception


from ui.theme import build_style


def _section(style_id: str, title: str, desc: str, body: QWidget) -> QWidget:
    """섹션 머리말(제목 + 설명)을 붙인 패널을 만든다.

    왼쪽(대상 특허)과 오른쪽(선행문헌)이 무엇을 넣는 자리인지
    한눈에 구분되도록 색 띠와 안내문을 얹는다.
    """
    from PyQt6.QtWidgets import QFrame

    header = QFrame()
    header.setObjectName(style_id)
    head_lay = QVBoxLayout(header)
    head_lay.setContentsMargins(12, 7, 12, 7)
    head_lay.setSpacing(1)

    kind = "Subject" if style_id == "sectionSubject" else "Prior"
    title_label = QLabel(title)
    title_label.setObjectName("sectionTitle" + kind)
    head_lay.addWidget(title_label)

    desc_label = QLabel(desc)
    desc_label.setObjectName("sectionDesc")
    desc_label.setWordWrap(True)
    head_lay.addWidget(desc_label)

    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lay.addWidget(header)
    lay.addWidget(body, stretch=1)
    return panel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("특허 Claim Chart 생성기 v1.0")
        self.resize(1600, 900)
        self.setFont(QFont("맑은 고딕", 10))

        self._pm = ProjectManager()
        self._engine = MappingEngine(self._pm.data, self._on_mapping_changed)
        self._dark_mode = False

        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_autosave()
        self._apply_style()
        self._new_project()

        # 크래시 복구 확인
        if self._pm.has_crash_recovery():
            self._ask_crash_recovery()

    # ------------------------------------------------------------------ UI

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # 메인 스플리터
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 좌측: 대상 특허 (검토 대상) — 청구항 + 서지사항
        left_tabs = QTabWidget()
        left_tabs.setMinimumWidth(420)

        self.claim_editor = ClaimEditorPanel()
        self.claim_editor.claim_changed.connect(self._on_claim_changed)
        left_tabs.addTab(self.claim_editor, "청구항")

        self.case_info_panel = CaseInfoPanel()
        self.case_info_panel.changed.connect(self._on_case_info_changed)
        self.case_info_panel.biblio_import_requested.connect(
            self._import_biblio)
        left_tabs.addTab(self.case_info_panel, "서지사항")

        self.main_splitter.addWidget(_section(
            "sectionSubject", "◀  대상 특허",
            "무효·침해를 검토할 특허입니다. 청구항을 구성요소로 나누고 "
            "서지사항을 입력하세요.", left_tabs))

        # 우측: 선행문헌 (대비 자료)
        self.pdf_viewer = PDFViewerPanel()
        self.pdf_viewer.mapping_requested.connect(self._on_mapping_requested)
        self.pdf_viewer.alias_requested.connect(self._on_alias_requested)
        self.pdf_viewer.document_opened.connect(self._on_document_opened)
        self.main_splitter.addWidget(_section(
            "sectionPrior", "선행문헌  ▶",
            "대상 특허와 대비할 선행기술입니다. 문서를 열고 대응 부분을 "
            "드래그해 왼쪽 구성요소와 연결하세요.", self.pdf_viewer))

        self.main_splitter.setSizes([500, 1100])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        root_layout.addWidget(self.main_splitter)

        # 하단 매핑 패널 (도킹)
        self._setup_mapping_dock()

        # 상태바
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("준비")
        self.status_bar.addWidget(self.status_label)

    def _setup_mapping_dock(self):
        dock = self.mapping_dock = QDockWidget("매핑 목록 / 대응 현황", self)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea)

        self.mapping_list_panel = MappingListPanel()
        self.mapping_list_panel.delete_requested.connect(self._delete_mapping)
        self.mapping_list_panel.edit_requested.connect(self._edit_mapping)
        self.mapping_list_panel.jump_requested.connect(self._jump_to_mapping)

        self.coverage_panel = CoveragePanel()
        self.coverage_panel.jump_requested.connect(self._jump_to_mapping)
        self.coverage_panel.inherit_changed.connect(self._on_panel_inherit)

        self.search_panel = SearchPanel()
        self.search_panel.jump_requested.connect(self._jump_to_mapping)
        self.search_panel.mapping_requested.connect(self._on_mapping_requested)
        self.search_panel.search_requested.connect(self._run_global_search)

        self.prior_art_panel = PriorArtPanel()
        self.prior_art_panel.changed.connect(self._on_prior_art_edited)
        self.prior_art_panel.open_requested.connect(
            self.pdf_viewer.open_document)
        self.prior_art_panel.reread_requested.connect(self._reread_prior_art)

        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.addTab(self.mapping_list_panel, "매핑 목록")
        self.bottom_tabs.addTab(self.coverage_panel, "대응 현황")
        self.bottom_tabs.addTab(self.search_panel, "문헌 통합 검색")
        self.bottom_tabs.addTab(self.prior_art_panel, "선행문헌 정보")

        dock.setWidget(self.bottom_tabs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.setMaximumHeight(240)

    # ---------------------------------------------------------------- Menu

    def _setup_menu(self):
        mb = self.menuBar()

        # 파일
        file_menu = mb.addMenu("파일(&F)")
        self._add_action(file_menu, "새 프로젝트", self._new_project, "Ctrl+N")
        self._add_action(file_menu, "열기...", self._open_project, "Ctrl+O")
        self._add_action(file_menu, "PDF에서 청구항 가져오기...",
                         lambda: self.claim_editor.import_claims_from_pdf(),
                         "Ctrl+I")
        self._add_action(file_menu, "저장", self._save_project, "Ctrl+S")
        self._add_action(file_menu, "다른 이름으로 저장...", self._save_as_project, "Ctrl+Shift+S")
        file_menu.addSeparator()
        self.recent_menu = file_menu.addMenu("최근 파일")
        self._refresh_recent_menu()
        file_menu.addSeparator()
        self._add_action(file_menu, "종료", self.close, "Alt+F4")

        # 편집
        edit_menu = mb.addMenu("편집(&E)")
        self._add_action(edit_menu, "실행 취소", self._undo, "Ctrl+Z")
        self._add_action(edit_menu, "다시 실행", self._redo, "Ctrl+Y")
        edit_menu.addSeparator()

        self.inherit_action = QAction(
            "종속항에 인용항 구성요소 함께 넣기", self)
        self.inherit_action.setCheckable(True)
        self.inherit_action.setChecked(True)
        self.inherit_action.setStatusTip(
            "예: 3항이 1항을 인용하면 3항 대비표에 1항 구성요소도 함께 "
            "실립니다 (대응 현황·PPTX·Word·Excel 모두 적용).")
        self.inherit_action.toggled.connect(self._toggle_inherit)
        edit_menu.addAction(self.inherit_action)

        self.lint_action = QAction("내보내기 전 점검", self)
        self.lint_action.setCheckable(True)
        self.lint_action.setChecked(True)
        self.lint_action.setStatusTip(
            "내보내기 직전에 근거 없는 구성요소·빈 논거 등을 확인해 "
            "알려줍니다.")
        self.lint_action.toggled.connect(self._toggle_lint)
        edit_menu.addAction(self.lint_action)

        # 선행문헌
        doc_menu = mb.addMenu("선행문헌(&D)")
        self._add_action(doc_menu, "문서 열기...", self.pdf_viewer.open_document_dialog)
        doc_menu.addSeparator()
        self._add_action(doc_menu, "OCR 켜기/끄기", self._toggle_ocr)

        # Export
        export_menu = mb.addMenu("내보내기(&X)")
        self._add_action(export_menu, "PPTX (Type A)...",
                         lambda: self._export_pptx("A"))
        self._add_action(export_menu, "PPTX (Type B)...",
                         lambda: self._export_pptx("B"))
        self._add_action(export_menu, "PPTX (Type C - 조합)...",
                         lambda: self._export_pptx("C"))
        export_menu.addSeparator()
        self._add_action(export_menu, "Excel 대비표...", self._export_excel)
        self._add_action(export_menu, "Word 표 형식...", self._export_word)

        # 보기
        view_menu = mb.addMenu("보기(&V)")
        self.dock_action = self.mapping_dock.toggleViewAction()
        self.dock_action.setText("매핑 목록 / 대응 현황 패널")
        view_menu.addAction(self.dock_action)
        self._add_action(view_menu, "구성요소별 대응 현황 보기",
                         self._show_coverage_tab)
        self._add_action(view_menu, "문헌 통합 검색 보기",
                         self._show_search_tab, "Ctrl+F")
        view_menu.addSeparator()
        self._add_action(view_menu, "다크모드 전환", self._toggle_theme)

        # 도움말
        help_menu = mb.addMenu("도움말(&H)")
        self._add_action(help_menu, "Claim Chart 작성 방법", self._show_methodology)
        help_menu.addSeparator()
        self._add_action(help_menu, "정보", self._show_about)

    def _add_action(self, menu: QMenu, text: str, slot,
                    shortcut: str = None) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # --------------------------------------------------------------- Toolbar

    def _setup_toolbar(self):
        tb = QToolBar("도구")
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(tb)

        for label, slot, tip in [
            ("새 프로젝트", self._new_project, "Ctrl+N"),
            ("열기", self._open_project, "Ctrl+O"),
            ("저장", self._save_project, "Ctrl+S"),
            ("|", None, None),
            ("실행취소", self._undo, "Ctrl+Z"),
            ("다시실행", self._redo, "Ctrl+Y"),
            ("|", None, None),
            ("PPTX", lambda: self._export_pptx("A"), ""),
            ("Excel", self._export_excel, ""),
            ("Word", self._export_word, ""),
        ]:
            if label == "|":
                tb.addSeparator()
            else:
                action = QAction(label, self)
                if tip:
                    action.setShortcut(QKeySequence(tip))
                action.triggered.connect(slot)
                tb.addAction(action)

    # ----------------------------------------------------------- Autosave

    def _setup_autosave(self):
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(AUTOSAVE_INTERVAL_MS)

    def _autosave(self):
        self._sync_data_from_ui()
        self._pm.autosave()
        self.status_label.setText("자동저장 완료")

    # --------------------------------------------------------- Data Sync

    def _sync_data_from_ui(self):
        """UI → 프로젝트 데이터 동기화."""
        self._pm.data.claims = self.claim_editor.get_claims()
        self._pm.data.terms = self.claim_editor.get_terms()
        self.case_info_panel.save_to(self._pm.data.case_info)
        self._pm.data.doc_paths = self.pdf_viewer.get_open_paths()

    def _sync_ui_from_data(self):
        """프로젝트 데이터 → UI 동기화."""
        inherit = getattr(self._pm.data, "inherit_dependent", True)
        if hasattr(self, "inherit_action"):
            self.inherit_action.blockSignals(True)
            self.inherit_action.setChecked(inherit)
            self.inherit_action.blockSignals(False)
            self.coverage_panel.set_inherit(inherit)
        self.claim_editor.set_terms(self._pm.data.terms)
        self.claim_editor.load_claims(self._pm.data.claims)
        self.case_info_panel.load(self._pm.data.case_info)
        # 문서를 여는 동안 문헌별 적격성 경고 모달이 연달아 뜨지 않도록 억제
        self._loading = True
        try:
            for path in self._pm.data.doc_paths:
                if os.path.exists(path):
                    self.pdf_viewer.open_document(path)
        finally:
            self._loading = False
        self._refresh_mapping_panel()

    def _refresh_mapping_panel(self):
        current_claim = self.claim_editor.get_current_claim()
        claim_num = current_claim.claim_number if current_claim else 0
        ratio = self._engine.completion_ratio(claim_num)
        self.mapping_list_panel.refresh(self._pm.data.mappings, ratio)
        self.coverage_panel.refresh(self.claim_editor.get_claims(),
                                    self._pm.data.mappings,
                                    self.pdf_viewer.get_open_paths())
        # 구성요소/용어 색상 맵 생성
        element_colors = {}
        for claim in self._pm.data.claims:
            for elem in claim.elements:
                element_colors[elem.element_id] = tuple(elem.color_rgb)
        # 용어는 청구항 패널이 실제 보유자 (프로젝트 데이터는 저장 시 동기화)
        terms = self.claim_editor.get_terms()
        term_colors = {t.term_id: tuple(t.color_rgb) for t in terms}
        self.pdf_viewer.set_terms(terms)
        self.search_panel.set_terms(terms)
        self.pdf_viewer.update_mappings(self._pm.data.mappings,
                                        element_colors, term_colors)
        self._refresh_prior_art_ui()
        self._update_title()

    def _update_title(self):
        path = self._pm.current_path
        name = os.path.basename(path) if path else "새 프로젝트"
        dirty = "• " if self._pm.is_dirty() else ""
        self.setWindowTitle(f"{dirty}{name} — 특허 Claim Chart 생성기")

    # --------------------------------------------------------- Callbacks

    def _on_claim_changed(self):
        self._pm.mark_dirty()
        self._refresh_mapping_panel()

    def _on_case_info_changed(self):
        self._pm.mark_dirty()
        self._update_title()
        # 우선일이 바뀌면 선행문헌 적격성도 다시 판정한다
        self._refresh_prior_art_ui()

    def _on_mapping_changed(self):
        self._pm.mark_dirty()
        self._refresh_mapping_panel()

    def _import_biblio(self):
        """특허 PDF 1페이지에서 서지사항을 읽어 사건정보를 채운다."""
        from core.biblio_extractor import extract_biblio
        from ui.biblio_import_dialog import BiblioImportDialog

        path = self._pick_biblio_source()
        if not path:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            biblio = extract_biblio(path)
        except Exception as e:
            log_exception(e)
            biblio = None
        finally:
            QApplication.restoreOverrideCursor()

        if not biblio:
            QMessageBox.warning(self, "오류",
                                "서지사항을 읽는 중 오류가 발생했습니다.")
            return

        # 텍스트 레이어가 없는 스캔본이면 OCR 제안
        if not any(v for k, v in biblio.items() if k != "_source"):
            biblio = self._try_biblio_ocr(path) or biblio

        dlg = BiblioImportDialog(biblio, self.case_info_panel.current_values(),
                                 parent=self)
        if dlg.exec() == BiblioImportDialog.DialogCode.Accepted:
            picked = dlg.selected()
            if picked:
                self.case_info_panel.apply_biblio(picked)
                self.status_label.setText(
                    f"서지사항 {len(picked)}개 항목을 가져왔습니다 "
                    f"({os.path.basename(path)})")

    def _try_biblio_ocr(self, path: str) -> dict:
        """스캔본이면 사용자 동의를 받아 OCR로 다시 읽는다."""
        from core.biblio_extractor import is_scanned
        from core.biblio_worker import extract_biblio_ocr
        from core.ocr_engine import is_ocr_available

        if not is_scanned(path):
            return None
        if not is_ocr_available():
            QMessageBox.information(
                self, "스캔본",
                "이 PDF는 텍스트가 없는 스캔본입니다.\n"
                "OCR 엔진(Tesseract)이 설치되어 있지 않아 읽을 수 없습니다.")
            return None

        reply = QMessageBox.question(
            self, "스캔본 OCR",
            "이 PDF는 텍스트가 없는 스캔본입니다.\n"
            "OCR로 서지 페이지를 읽어볼까요? (30초~2분 정도 걸립니다)\n\n"
            "※ OCR 결과에는 오탈자가 있을 수 있으니\n"
            "   적용 전에 값을 확인해 주세요.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            return None

        self.status_label.setText("스캔본 OCR 처리 중… (잠시 기다려 주세요)")
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            biblio, err = extract_biblio_ocr(path)
        finally:
            QApplication.restoreOverrideCursor()
            self.status_label.setText("")

        if err:
            QMessageBox.warning(self, "OCR 실패", err)
            return None
        return biblio

    def _pick_biblio_source(self) -> str:
        """서지사항을 읽을 PDF 선택 — 열려 있는 문서가 있으면 먼저 제시."""
        from PyQt6.QtWidgets import QFileDialog, QInputDialog

        opened = [p for p in self.pdf_viewer.get_open_paths()
                  if p.lower().endswith(".pdf")]
        if opened:
            choices = [os.path.basename(p) for p in opened]
            choices.append("다른 파일 선택…")
            pick, ok = QInputDialog.getItem(
                self, "서지사항을 읽을 PDF",
                "특허 PDF의 1페이지에서 서지사항을 읽습니다:",
                choices, 0, False)
            if not ok:
                return ""
            if pick != "다른 파일 선택…":
                return opened[choices.index(pick)]

        path, _ = QFileDialog.getOpenFileName(
            self, "특허 PDF 선택", "", "PDF (*.pdf)")
        return path

    def _on_alias_requested(self, term_id: str, keyword: str):
        """뷰어에서 검색한 단어를 해당 용어의 선행문헌 표기로 등록."""
        term = next((t for t in self.claim_editor.get_terms()
                     if t.term_id == term_id), None)
        if term is None:
            return
        if self.claim_editor.add_alias(term_id, keyword):
            self.status_label.setText(
                f'"{keyword}" → {term.term_id} {term.text} 과(와) 같은 색으로 표시')
            self._pm.mark_dirty()
            self._refresh_mapping_panel()
        else:
            self.status_label.setText(f'"{keyword}" 은(는) 이미 등록되어 있습니다')

    def _on_mapping_requested(self, doc_path: str, page: int,
                               rect: list, extracted_text: str):
        """PDF 뷰어에서 드래그 선택 시 매핑 다이얼로그 표시."""
        claims = self.claim_editor.get_claims()
        if not claims:
            QMessageBox.information(self, "알림",
                                    "청구항을 먼저 입력하고 구성요소를 분할해 주세요.")
            return
        if not any(c.elements for c in claims):
            QMessageBox.information(self, "알림",
                                    "청구항의 '자동 분할' 버튼으로 구성요소를 먼저 생성해 주세요.")
            return

        dlg = MappingDialog(claims, doc_path, page, rect, extracted_text,
                            terms=self._pm.data.terms, parent=self)
        if dlg.exec() == MappingDialog.DialogCode.Accepted:
            result = dlg.get_result()
            elem_ids = result["element_ids"]
            if not elem_ids:
                QMessageBox.warning(self, "경고", "구성요소를 선택해 주세요.")
                return
            term_id = self._resolve_term_id(result)
            # 체크된 구성요소마다 같은 영역으로 매핑 생성
            for elem_id in elem_ids:
                self._engine.add_mapping(
                    element_id=elem_id,
                    claim_number=result["claim_number"],
                    doc_path=doc_path,
                    page=page,
                    rect=rect,
                    extracted_text=result["extracted_text"],
                    judgment=result["judgment"],
                    interpretation=result["interpretation"],
                    note=result["note"],
                    term_id=term_id,
                    term_spans=result.get("term_spans", []),
                )

    def _delete_mapping(self, mapping_id: str):
        reply = QMessageBox.question(
            self, "삭제 확인", "이 매핑을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._engine.delete_mapping(mapping_id)

    def _edit_mapping(self, mapping_id: str):
        m = next((x for x in self._pm.data.mappings
                  if x.mapping_id == mapping_id), None)
        if not m:
            return
        claims = self.claim_editor.get_claims()
        dlg = MappingDialog(claims, m.doc_path, m.page, m.rect,
                            m.extracted_text, existing=m,
                            terms=self._pm.data.terms, parent=self)
        if dlg.exec() == MappingDialog.DialogCode.Accepted:
            result = dlg.get_result()
            self._engine.update_mapping(
                mapping_id,
                element_id=result["element_id"],
                claim_number=result["claim_number"],
                extracted_text=result["extracted_text"],
                judgment=result["judgment"],
                interpretation=result["interpretation"],
                note=result["note"],
                term_id=self._resolve_term_id(result),
                term_spans=result.get("term_spans", []),
            )

    def _resolve_term_id(self, result: dict) -> str:
        """매핑 다이얼로그에서 신규 후보 용어를 골랐으면 등록 후 id 반환."""
        new_text = result.get("new_term_text", "")
        if new_text:
            term_id = self.claim_editor.ensure_term(new_text)
            self.claim_editor._refresh_term_ui()
            self._pm.data.terms = self.claim_editor.get_terms()
            return term_id
        return result.get("term_id", "")

    def _jump_to_mapping(self, doc_path: str, page: int, rect: list):
        """매핑 목록·커버리지 격자에서 해당 근거 위치로 이동한다."""
        if not doc_path or not os.path.exists(doc_path):
            self.status_label.setText(
                f"문서를 찾을 수 없습니다: {os.path.basename(doc_path or '')}")
            return
        self.pdf_viewer.open_document(doc_path)
        viewer = self.pdf_viewer.viewer_for(doc_path)
        if not viewer:
            return
        if hasattr(viewer, "goto_offset"):   # 텍스트 문서: rect = 문자 오프셋
            r = list(rect or [0, 0, 0, 0])
            viewer.goto_offset(int(r[0]), int(r[1]))
        else:
            viewer.goto_rect(page, rect)

    # ------------------------------------------ Project CRUD

    def _new_project(self):
        if self._pm.is_dirty():
            r = QMessageBox.question(
                self, "저장 확인",
                "저장되지 않은 변경사항이 있습니다. 저장하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return
            if r == QMessageBox.StandardButton.Yes:
                self._save_project()

        self._pm.new_project()
        self._engine.set_data(self._pm.data)

        # 기본 청구항 1 추가
        default_claim = Claim(claim_number=1, is_independent=True)
        self._pm.data.claims = [default_claim]
        self._sync_ui_from_data()
        self.status_label.setText("새 프로젝트 생성됨")

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "프로젝트 열기", "",
            "특허 Claim Chart 프로젝트 (*.pcc);;모든 파일 (*.*)")
        if path:
            self._load_project(path)

    def _load_project(self, path: str):
        if self._pm.load(path):
            self._engine.set_data(self._pm.data)
            self._sync_ui_from_data()
            self._refresh_recent_menu()
            self.status_label.setText(f"열기 완료: {os.path.basename(path)}")
        else:
            QMessageBox.critical(self, "오류", f"프로젝트를 열 수 없습니다:\n{path}")

    def _save_project(self):
        if not self._pm.current_path:
            return self._save_as_project()
        self._sync_data_from_ui()
        if self._pm.save():
            self.status_label.setText("저장 완료")
            self._update_title()
        else:
            QMessageBox.critical(self, "오류", "저장에 실패했습니다.")

    def _save_as_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "다른 이름으로 저장", "",
            "특허 Claim Chart 프로젝트 (*.pcc)")
        if path:
            if not path.endswith(".pcc"):
                path += ".pcc"
            self._sync_data_from_ui()
            if self._pm.save(path):
                self.status_label.setText(f"저장 완료: {os.path.basename(path)}")
                self._update_title()
                self._refresh_recent_menu()
            else:
                QMessageBox.critical(self, "오류", "저장에 실패했습니다.")

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        for path in self._pm.get_recent_files():
            action = QAction(os.path.basename(path), self)
            action.setToolTip(path)
            action.triggered.connect(lambda checked, p=path: self._load_project(p))
            self.recent_menu.addAction(action)

    # ------------------------------------------ Undo / Redo

    def _undo(self):
        if self._engine.undo():
            self.status_label.setText("실행 취소")
        else:
            self.status_label.setText("더 이상 취소할 작업이 없습니다")

    def _redo(self):
        if self._engine.redo():
            self.status_label.setText("다시 실행")
        else:
            self.status_label.setText("다시 실행할 작업이 없습니다")

    # ------------------------------------------ Export

    def _export_pptx(self, template_type: str):
        from utils.export_pptx import export_pptx
        self._sync_data_from_ui()
        if not self._lint_gate("PPTX"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, f"PPTX 내보내기 (Type {template_type})", "",
            "PowerPoint 파일 (*.pptx)")
        if path:
            if not path.endswith(".pptx"):
                path += ".pptx"
            self._run_export(
                "PPTX", path,
                lambda p: export_pptx(self._pm.data, p,
                                      template_type=template_type))

    def _export_excel(self):
        from utils.export_excel import export_excel
        self._sync_data_from_ui()
        if not self._lint_gate("Excel"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Excel 내보내기", "", "Excel 파일 (*.xlsx)")
        if path:
            if not path.endswith(".xlsx"):
                path += ".xlsx"
            self._run_export("Excel", path,
                             lambda p: export_excel(self._pm.data, p))

    def _export_word(self):
        from utils.export_word import export_word
        self._sync_data_from_ui()
        if not self._lint_gate("Word"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Word 내보내기", "", "Word 파일 (*.docx)")
        if path:
            if not path.endswith(".docx"):
                path += ".docx"
            self._run_export("Word", path,
                             lambda p: export_word(self._pm.data, p))

    @staticmethod
    def _is_lock_error(detail: str) -> bool:
        low = detail.lower()
        return ("permission" in low or "denied" in low
                or "winerror 32" in low or "errno 13" in low)

    @staticmethod
    def _next_free_path(path: str) -> str:
        """열려 있어 잠긴 파일을 피해 'name (1).ext' 형태의 빈 경로를 찾는다."""
        base, ext = os.path.splitext(path)
        for i in range(1, 100):
            cand = f"{base} ({i}){ext}"
            if not os.path.exists(cand):
                return cand
        # 그래도 못 찾으면 타임스탬프
        import time
        return f"{base} {int(time.time())}{ext}"

    def _toggle_inherit(self, on: bool):
        """종속항에 인용항 구성요소를 포함할지 전환."""
        self._pm.data.inherit_dependent = on
        self._pm.mark_dirty()
        if hasattr(self, "coverage_panel"):
            self.coverage_panel.set_inherit(on)
        self._refresh_mapping_panel()
        self.status_label.setText(
            "종속항에 인용항 구성요소를 함께 넣습니다" if on
            else "종속항은 자기 구성요소만 표시합니다")

    def _on_panel_inherit(self, on: bool):
        """커버리지 패널의 체크박스로 바꾼 경우 메뉴·프로젝트에 반영."""
        self._pm.data.inherit_dependent = on
        self._pm.mark_dirty()
        if self.inherit_action.isChecked() != on:
            self.inherit_action.blockSignals(True)
            self.inherit_action.setChecked(on)
            self.inherit_action.blockSignals(False)

    def _toggle_lint(self, on: bool):
        self._skip_lint = not on
        self.status_label.setText(
            "내보내기 전 점검을 사용합니다" if on
            else "내보내기 전 점검을 건너뜁니다")

    def _run_global_search(self, keywords: list):
        """열려 있는 모든 선행문헌에서 한 번에 찾는다."""
        if not self.pdf_viewer.get_open_paths():
            QMessageBox.information(
                self, "알림", "먼저 선행문헌을 열어 주세요.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            hits = self.pdf_viewer.search_all(keywords)
        except Exception as e:
            log_exception(e)
            hits = []
        finally:
            QApplication.restoreOverrideCursor()
        self.search_panel.show_results(hits, keywords)
        self.status_label.setText(
            f"통합 검색: {len(hits)}건" if hits else "통합 검색 결과 없음")

    def _show_search_tab(self):
        """문헌 통합 검색 패널을 열고 앞으로 가져온다."""
        self.mapping_dock.show()
        self.mapping_dock.raise_()
        self.bottom_tabs.setCurrentWidget(self.search_panel)
        self.search_panel.query_edit.setFocus()

    # ------------------------------------------ 선행문헌 등록·적격성

    def _base_date_live(self) -> tuple:
        """기준일 (서지사항 탭의 현재 입력값 기준 — 저장 전 편집도 반영)."""
        from core.prior_art import subject_base_date
        vals = self.case_info_panel.current_values()

        class _CI:
            priority_date = vals.get("priority_date", "")
            application_date = vals.get("application_date", "")
        return subject_base_date(_CI)

    def _on_document_opened(self, path: str):
        """문헌이 열리면 등록부에 올리고 서지·적격성을 자동 확인."""
        from core.prior_art import ensure_prior_art, eligibility, STATUS_BAD

        doc, created = ensure_prior_art(self._pm.data, path)
        if created:
            self._pm.mark_dirty()
            self._fill_prior_art_biblio(doc, use_ocr=False)

        base, _kind = self._base_date_live()
        status, detail = eligibility(doc, base)
        self.status_label.setText(f"{doc.label} 등록 — {status}: {detail}")
        # 프로젝트 로드 중에는 모달을 띄우지 않는다 (문헌 수만큼 팝업 방지)
        if created and status == STATUS_BAD and not getattr(
                self, "_loading", False):
            QMessageBox.warning(
                self, "선행문헌 적격성",
                f"{doc.label} ({os.path.basename(path)})\n\n{detail}\n\n"
                "이 문헌으로는 무효 주장을 할 수 없습니다. 공개일이 잘못 "
                "읽혔다면 '선행문헌 정보' 탭에서 고쳐 주세요.")
        self._refresh_prior_art_ui()

    def _fill_prior_art_biblio(self, doc, use_ocr: bool) -> bool:
        """문헌 1페이지에서 서지를 읽어 채운다. 성공 여부 반환."""
        from core.biblio_extractor import extract_biblio, is_scanned
        from core.text_doc import is_text_doc, doc_title

        if is_text_doc(doc.path):
            doc.title = doc.title or doc_title(doc.path)
            return True
        if not os.path.exists(doc.path):
            return False
        try:
            if use_ocr:
                from core.biblio_worker import extract_biblio_ocr
                biblio, err = extract_biblio_ocr(doc.path)
                if err or not biblio:
                    QMessageBox.warning(self, "OCR 실패",
                                        err or "서지를 읽지 못했습니다.")
                    return False
            else:
                if is_scanned(doc.path):
                    return False          # OCR 은 사용자가 버튼으로 요청
                biblio = extract_biblio(doc.path)
        except Exception as e:
            log_exception(e)
            return False

        doc.title = biblio.get("title") or doc.title
        doc.pub_number = biblio.get("registration_number") or doc.pub_number
        doc.pub_date = biblio.get("publication_date") or doc.pub_date
        doc.reg_date = biblio.get("registration_date") or doc.reg_date
        return True

    def _reread_prior_art(self, path: str, use_ocr: bool):
        """패널의 '서지 다시 읽기' — 읽은 값으로 덮어쓴다."""
        from core.prior_art import find_prior_art
        doc = find_prior_art(self._pm.data, path)
        if doc is None:
            return
        if use_ocr:
            self.status_label.setText("스캔본 OCR 처리 중… (잠시 기다려 주세요)")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # 다시 읽기는 기존 값을 덮어써야 하므로 비우고 시작
            doc.title = doc.pub_number = doc.pub_date = doc.reg_date = ""
            done = self._fill_prior_art_biblio(doc, use_ocr=use_ocr)
        finally:
            QApplication.restoreOverrideCursor()
        if done:
            self._pm.mark_dirty()
            self.status_label.setText("서지를 다시 읽었습니다")
        elif not use_ocr:
            QMessageBox.information(
                self, "스캔본",
                "이 PDF는 텍스트가 없는 스캔본입니다.\n"
                "'OCR로 읽기' 버튼을 사용해 주세요.")
        self._refresh_prior_art_ui()

    def _on_prior_art_edited(self):
        self._pm.mark_dirty()
        self._refresh_prior_art_ui()

    def _refresh_prior_art_ui(self):
        """등록부 표·뷰어 탭 라벨·대응 현황 열머리를 갱신."""
        from core.prior_art import labels_map
        base, kind = self._base_date_live()
        self.prior_art_panel.refresh(self._pm.data.prior_arts, base, kind)
        for doc in self._pm.data.prior_arts:
            if (doc.label or "").strip():
                self.pdf_viewer.set_tab_label(
                    doc.path,
                    f"{doc.label} · {os.path.basename(doc.path)}")
        self.coverage_panel.set_doc_labels(labels_map(self._pm.data))

    def _show_coverage_tab(self):
        """대응 현황 패널을 열고 앞으로 가져온다."""
        self.mapping_dock.show()
        self.mapping_dock.raise_()
        self.bottom_tabs.setCurrentWidget(self.coverage_panel)

    def _lint_gate(self, target: str) -> bool:
        """내보내기 전 점검. 계속 진행하면 True."""
        if getattr(self, "_skip_lint", False):
            return True
        try:
            from core.export_lint import lint_project
            from ui.lint_dialog import LintDialog
            issues = lint_project(self._pm.data)
        except Exception as e:      # 점검 자체가 내보내기를 막으면 안 된다
            log_exception(e)
            return True
        if not issues:
            return True
        dlg = LintDialog(issues, target, parent=self)
        proceed = dlg.exec() == LintDialog.DialogCode.Accepted
        if proceed and dlg.skip_future():
            self._skip_lint = True
        return proceed

    def _run_export(self, kind: str, path: str, fn):
        """export 실행. 파일 잠김이면 자동으로 다른 이름으로 재시도."""
        err = fn(path)
        if err is None:
            self._open_file(path)
            self.status_label.setText(f"{kind} 저장: {os.path.basename(path)}")
            return

        # 파일이 열려 잠긴 경우 → 다른 이름으로 자동 저장
        if self._is_lock_error(err):
            alt = self._next_free_path(path)
            err2 = fn(alt)
            if err2 is None:
                self._open_file(alt)
                self.status_label.setText(
                    f"{kind} 저장(이름 변경): {os.path.basename(alt)}")
                QMessageBox.information(
                    self, "이름을 바꿔 저장했습니다",
                    f"'{os.path.basename(path)}' 파일이 열려 있어\n"
                    f"'{os.path.basename(alt)}'(으)로 저장했습니다.\n\n"
                    "원래 이름으로 저장하려면 열려 있는 파일을 닫고 다시 내보내세요.")
                return
            err = err2   # 대체 저장도 실패하면 원래 오류 표시

        self._show_export_error(kind, err)

    def _show_export_error(self, kind: str, detail: str):
        log_path = os.path.join(os.path.expanduser("~"),
                                "PatentClaimChart_logs", "crash.log")
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("내보내기 실패")
        msg.setText(f"{kind} 생성에 실패했습니다.")
        hint = ""
        low = detail.lower()
        if "permission" in low or "denied" in low or "winerror 32" in low:
            hint = ("\n\n같은 이름의 파일이 이미 열려 있을 수 있습니다.\n"
                    "해당 파일(또는 PowerPoint/Excel/Word)을 닫고 다시 시도하세요.")
        msg.setInformativeText(f"원인: {detail}{hint}")
        msg.setDetailedText(f"자세한 로그:\n{log_path}")
        msg.exec()

    def _open_file(self, path: str):
        import subprocess, sys
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.call(["open", path])
        else:
            subprocess.call(["xdg-open", path])

    # ------------------------------------------ Misc

    def _toggle_ocr(self):
        current = self.pdf_viewer._use_ocr
        self.pdf_viewer.set_ocr(not current)
        state = "켜짐" if not current else "꺼짐"
        self.status_label.setText(f"OCR {state}")

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self._apply_style()

    def _apply_style(self):
        QApplication.instance().setStyleSheet(
            build_style(self._dark_mode))

    def _show_methodology(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Claim Chart 작성 방법")
        dlg.setTextFormat(Qt.TextFormat.RichText)
        dlg.setText(
            "<b>청구항의 구조</b><br>"
            "각 청구항은 하나의 문장이며 3부분으로 나뉩니다.<br>"
            "&nbsp;• <b>도입부(preamble)</b>: \"An apparatus\"<br>"
            "&nbsp;• <b>연결부(transition)</b>: comprising(개방) / "
            "consisting of(폐쇄)<br>"
            "&nbsp;• <b>구성요소부(elements)</b>: 세미콜론으로 나열되는 본문<br><br>"
            "<b>구성요소부 = 요소(Element) + 제한조건(Limitation)</b><br>"
            "&nbsp;• 요소(Element): 핵심 구성 (예: case, cartridge, tip)<br>"
            "&nbsp;• 제한조건(Limitation): 요소를 수식하는 나머지 문구<br>"
            "&nbsp;• <b>All Elements Rule</b>: 모든 요소·제한조건이 대응돼야 "
            "침해/무효가 성립<br><br>"
            "<b>Claim Chart</b><br>"
            "청구항의 각 요소를 대상(선행문헌·표준·제품)에 <b>1:1</b>로 "
            "대응시켜 서술한 표.<br>"
            "&nbsp;• 좌측: 청구항 요소 (색상 구분)<br>"
            "&nbsp;• 우측: 대응부분 (같은 색으로 매칭)<br>"
            "&nbsp;• 보통 <b>독립항</b>에 대해 작성<br><br>"
            "<b>이 앱에서</b><br>"
            "① 자동 분할 → ② 요소 추출/지정 → ③ PDF 대응부분 드래그 매핑 → "
            "④ 내보내기(PPTX/Excel/Word)<br><br>"
            "<b>구성요소별 대응 현황</b> (화면 아래 탭)<br>"
            "가로줄은 청구항 구성요소, 세로칸은 선행문헌입니다. 둘이 만나는 "
            "칸에 대응 여부가 색으로 표시되고, <b>빈칸(—)은 아직 근거를 "
            "찾지 못한 곳</b>입니다. 모든 구성요소에 근거가 있어야 무효/침해가 "
            "성립하므로(All Elements Rule) 빈칸이 곧 남은 일감입니다.<br>"
            "칸을 클릭하면 그 근거가 있는 선행문헌 위치로 이동합니다.<br><br>"
            "<b>종속항에 인용항 구성요소 함께 넣기</b> (편집 메뉴)<br>"
            "3항이 1항을 인용하면 3항의 권리범위는 "
            "<i>1항 구성요소 전부 + 3항의 추가 한정</i>입니다. 이 설정을 켜면 "
            "3항 대비표에 1항 구성요소가 <b>(1항 인용)</b> 표시와 함께 자동으로 "
            "실리고, 1항에 이미 연결해 둔 근거가 그대로 나타납니다. "
            "같은 매핑을 두 번 만들 필요가 없습니다.<br><br>"
            "<b>선행문헌 적격성</b> (화면 아래 '선행문헌 정보' 탭)<br>"
            "선행문헌을 열면 공보번호·공개일이 자동으로 읽히고, 대상 특허 "
            "기준일(우선일, 없으면 출원일)보다 <b>먼저 공개됐는지</b> 판정합니다. "
            "기준일 이후에 공개된 문헌은 선행문헌 자격이 없어 붉게 표시되고, "
            "그 문헌을 인용한 채로 내보내면 점검에서 오류로 걸립니다. "
            "라벨(D1, 갑제3호증 등)과 날짜는 표에서 직접 고칠 수 있고, "
            "고친 라벨은 대응 현황·보고서에도 그대로 쓰입니다.<br><br>"
            "<b>자주 나온 단어</b> (매핑 창)<br>"
            "선행문헌을 드래그하면 매핑 창 위쪽에 그 안에서 자주 나온 단어가 "
            "칩으로 나옵니다. 도면처럼 부호가 많아도 원하는 단어를 눈으로 "
            "찾을 필요 없이 칩을 누르면 텍스트 안의 그 단어가 전부 요소 색으로 "
            "칠해집니다. 등록 용어와 일치하는 단어는 그 색을 미리 입혀 맨 앞에 "
            "옵니다.<br><br>"
            "<b>문헌 통합 검색</b> (화면 아래 탭 · Ctrl+F)<br>"
            "같은 구성요소를 문헌마다 다르게 부르는 경우"
            "(체결부 / 결합 / 고정 / fastening)를 위한 기능입니다. "
            "용어를 고르면 등록해 둔 표기를 모두 넣어 <b>열려 있는 모든 "
            "선행문헌을 한 번에</b> 찾습니다. 결과를 한 번 클릭하면 그 위치로 "
            "이동하고, 두 번 클릭하면 그 자리로 매핑을 만듭니다.<br><br>"
            "<b>내보내기 전 점검</b> (편집 메뉴)<br>"
            "근거 없는 구성요소, 균등론인데 논거가 빈 매핑, 파일이 사라진 "
            "선행문헌 등을 내보내기 직전에 알려줍니다."
        )
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.exec()

    def _show_about(self):
        QMessageBox.information(
            self, "정보",
            "특허 Claim Chart 생성기 v1.0\n\n"
            "오프라인 특허 무효/침해 Claim Chart 자동 생성 도구\n\n"
            "[주의] 사내 미서명 실행 파일은 보안 프로그램에 의해 차단될 수 있습니다.\n"
            "IT팀에 화이트리스트 등록을 요청하시기 바랍니다.\n\n"
            "[OCR 안내] 스캔본 PDF는 Tesseract OCR이 설치되어 있으면\n"
            "자동으로 텍스트를 추출합니다 (표준 설치 경로 자동 감지).\n"
            "영역 드래그 추출은 메뉴 > 선행문헌 > OCR 켜기/끄기에서 설정하세요."
        )

    def _ask_crash_recovery(self):
        reply = QMessageBox.question(
            self, "복구 파일 발견",
            "이전 비정상 종료로 인한 자동저장 파일이 발견되었습니다.\n"
            "복구하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self._pm.load_crash_recovery():
                self._engine.set_data(self._pm.data)
                self._sync_ui_from_data()
                self.status_label.setText("이전 작업이 복구되었습니다.")
            self._pm.clear_crash_recovery()
        else:
            self._pm.clear_crash_recovery()

    # ------------------------------------------ Close Event

    def closeEvent(self, event):
        if self._pm.is_dirty():
            r = QMessageBox.question(
                self, "종료 확인",
                "저장되지 않은 변경사항이 있습니다. 저장하고 종료하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if r == QMessageBox.StandardButton.Yes:
                self._save_project()
        self._pm.clear_crash_recovery()
        event.accept()
