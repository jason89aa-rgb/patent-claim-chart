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


from ui.theme import build_style


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

        # 좌측: 사건정보 탭 + 청구항 에디터
        left_tabs = QTabWidget()
        left_tabs.setMinimumWidth(420)

        self.claim_editor = ClaimEditorPanel()
        self.claim_editor.claim_changed.connect(self._on_claim_changed)
        left_tabs.addTab(self.claim_editor, "청구항")

        self.case_info_panel = CaseInfoPanel()
        self.case_info_panel.changed.connect(self._on_case_info_changed)
        left_tabs.addTab(self.case_info_panel, "사건정보")

        self.main_splitter.addWidget(left_tabs)

        # 우측: PDF 뷰어
        self.pdf_viewer = PDFViewerPanel()
        self.pdf_viewer.mapping_requested.connect(self._on_mapping_requested)
        self.pdf_viewer.alias_requested.connect(self._on_alias_requested)
        self.main_splitter.addWidget(self.pdf_viewer)

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
        dock = QDockWidget("매핑 목록", self)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea)
        self.mapping_list_panel = MappingListPanel()
        self.mapping_list_panel.delete_requested.connect(self._delete_mapping)
        self.mapping_list_panel.edit_requested.connect(self._edit_mapping)
        self.mapping_list_panel.jump_requested.connect(self._jump_to_mapping)
        dock.setWidget(self.mapping_list_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.setMaximumHeight(180)

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
        self.claim_editor.set_terms(self._pm.data.terms)
        self.claim_editor.load_claims(self._pm.data.claims)
        self.case_info_panel.load(self._pm.data.case_info)
        for path in self._pm.data.doc_paths:
            if os.path.exists(path):
                self.pdf_viewer.open_document(path)
        self._refresh_mapping_panel()

    def _refresh_mapping_panel(self):
        current_claim = self.claim_editor.get_current_claim()
        claim_num = current_claim.claim_number if current_claim else 0
        ratio = self._engine.completion_ratio(claim_num)
        self.mapping_list_panel.refresh(self._pm.data.mappings, ratio)
        # 구성요소/용어 색상 맵 생성
        element_colors = {}
        for claim in self._pm.data.claims:
            for elem in claim.elements:
                element_colors[elem.element_id] = tuple(elem.color_rgb)
        # 용어는 청구항 패널이 실제 보유자 (프로젝트 데이터는 저장 시 동기화)
        terms = self.claim_editor.get_terms()
        term_colors = {t.term_id: tuple(t.color_rgb) for t in terms}
        self.pdf_viewer.set_terms(terms)
        self.pdf_viewer.update_mappings(self._pm.data.mappings,
                                        element_colors, term_colors)
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

    def _on_mapping_changed(self):
        self._pm.mark_dirty()
        self._refresh_mapping_panel()

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
        self.pdf_viewer.open_document(doc_path)
        # 해당 뷰어로 페이지 이동 (viewer에 public api 추가 필요)
        viewer = self.pdf_viewer._viewers.get(doc_path)
        if not viewer:
            return
        if hasattr(viewer, "goto_offset"):   # 텍스트 문서: rect = 문자 오프셋
            r = list(rect or [0, 0, 0, 0])
            viewer.goto_offset(int(r[0]), int(r[1]))
        else:
            viewer._goto_page(page)

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
            "④ 내보내기(PPTX/Excel/Word)"
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
