"""우측 PDF/이미지 뷰어 - 드래그 선택, 매핑 연결, 키워드 검색, 썸네일 네비게이션."""
import os
from typing import Optional

import fitz  # PyMuPDF
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QPushButton, QSlider, QLineEdit, QToolButton,
    QSizePolicy, QFrame, QListWidget, QListWidgetItem,
    QSplitter, QTabWidget, QComboBox, QMessageBox
)
from PyQt6.QtCore import (pyqtSignal, Qt, QPoint, QRect, QRectF,
                           QSize, QTimer)
from PyQt6.QtGui import (QImage, QPixmap, QPainter, QPen, QColor,
                          QBrush, QFont, QCursor, QWheelEvent, QIcon)

from core.project import MappingEntry, ClaimElement
from core.text_doc import is_text_doc, doc_title
from utils.color_utils import rgb_to_hex
from utils.term_format import term_texts
from ui.text_viewer import TextDocumentViewer, parse_keywords


class PageCanvas(QLabel):
    """PDF 단일 페이지 렌더링 + 드래그 선택."""
    selection_made = pyqtSignal(list, str)
    right_clicked = pyqtSignal(QPoint, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setMouseTracking(True)

        self._pdf_page: Optional[fitz.Page] = None
        self._scale = 1.5
        self._drag_start: Optional[QPoint] = None
        self._drag_rect: Optional[QRect] = None
        self._pixmap_base: Optional[QPixmap] = None
        self._mappings: list[MappingEntry] = []
        self._search_rects: list[fitz.Rect] = []
        self._page_index = 0
        self._element_colors: dict[str, tuple] = {}
        self._term_colors: dict[str, tuple] = {}
        self._snap_mode = "sentence"   # sentence | line | none

    def set_page(self, page: fitz.Page, page_index: int, scale: float = 1.5):
        self._pdf_page = page
        self._page_index = page_index
        self._scale = scale
        self._drag_rect = None
        self._render()

    def set_element_colors(self, colors: dict[str, tuple]):
        self._element_colors = colors

    def set_term_colors(self, colors: dict[str, tuple]):
        self._term_colors = colors

    def set_snap_mode(self, mode: str):
        self._snap_mode = mode

    def set_mappings(self, mappings: list[MappingEntry]):
        self._mappings = mappings
        self._render()

    def set_search_rects(self, rects: list[fitz.Rect]):
        self._search_rects = rects
        self._render()

    def set_scale(self, scale: float):
        self._scale = scale
        self._render()

    def _render(self):
        if not self._pdf_page:
            return
        mat = fitz.Matrix(self._scale, self._scale)
        pix = self._pdf_page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height,
                     pix.stride, QImage.Format.Format_RGB888)
        base = QPixmap.fromImage(img)
        self._pixmap_base = base

        overlay = QPixmap(base)
        painter = QPainter(overlay)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 매핑 하이라이트 — 같은 영역에 여러 구성요소가 매핑되면
        # 테두리를 색상별로 분할하고 라벨을 나란히 표시한다.
        from core.region_capture import group_mappings_by_region

        page_maps = [m for m in self._mappings if m.page == self._page_index]
        for _key, group in group_mappings_by_region(page_maps).items():
            # 같은 도면을 따로 드래그해도 병합된 합집합 영역으로 표시
            from core.region_capture import _union_rect
            r = self._pdf_rect_to_screen(
                _union_rect([list(m.rect) for m in group]))
            colors = [self._get_mapping_color(m) for m in group]

            # 채우기: 첫 색상 옅게
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(*colors[0], 40)))
            painter.drawRect(r)

            # 테두리: 매핑 수만큼 굵기를 겹쳐 그려 여러 색이 동시에 보이게
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for i, color_rgb in enumerate(colors):
                painter.setPen(QPen(QColor(*color_rgb), 2))
                painter.drawRect(r.adjusted(-2 * i, -2 * i, 2 * i, 2 * i))

            # 라벨: 좌상단에 가로로 나란히
            painter.setFont(QFont("맑은 고딕", 8, QFont.Weight.Bold))
            lx = r.left()
            ly = r.top() - 18
            for m, color_rgb in zip(group, colors):
                label = self._get_mapping_label(m)
                w = max(28, 9 * len(label) + 8)
                label_rect = QRect(lx, ly, w, 16)
                painter.fillRect(label_rect, QColor(*color_rgb, 220))
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter,
                                 label)
                lx += w + 2

        # 검색 결과 하이라이트 — 키워드별 색상, 현재 히트는 굵은 테두리
        for item in self._search_rects:
            if isinstance(item, tuple) and len(item) == 3:
                rect, color, active = item
            else:                      # 구버전 호환 (rect만)
                rect, color, active = item, (255, 220, 0), False
            r = self._pdf_rect_to_screen(
                [rect.x0, rect.y0, rect.x1, rect.y1])
            painter.setBrush(QBrush(QColor(*color, 110)))
            if active:
                painter.setPen(QPen(QColor(220, 40, 40), 3))
                painter.drawRect(r.adjusted(-2, -2, 2, 2))
            else:
                painter.setPen(QPen(QColor(*color), 1))
                painter.drawRect(r)

        # 드래그 선택 영역
        if self._drag_rect:
            painter.setPen(QPen(QColor(0, 120, 215), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(0, 120, 215, 30)))
            painter.drawRect(self._drag_rect)
            # 드래그 크기 표시
            painter.setPen(QColor(0, 120, 215))
            painter.setFont(QFont("맑은 고딕", 8))
            w = self._drag_rect.width()
            h = self._drag_rect.height()
            painter.drawText(
                self._drag_rect.bottomRight() + QPoint(4, 14),
                f"{w}x{h}")

        painter.end()
        self.setPixmap(overlay)
        self.resize(overlay.size())

    def _get_mapping_color(self, m: MappingEntry) -> tuple:
        # 매칭 용어가 지정된 매핑은 용어 색 우선 (청구항 쪽과 동일 색)
        if m.term_id and m.term_id in self._term_colors:
            return self._term_colors[m.term_id]
        return self._element_colors.get(m.element_id, (70, 130, 180))

    def _get_mapping_label(self, m: MappingEntry) -> str:
        if m.term_id and m.term_id in self._term_colors:
            return m.term_id
        return m.element_id

    def _pdf_rect_to_screen(self, rect: list) -> QRect:
        x0, y0, x1, y1 = rect
        return QRect(
            int(x0 * self._scale), int(y0 * self._scale),
            int((x1 - x0) * self._scale), int((y1 - y0) * self._scale)
        )

    def _screen_to_pdf(self, qrect: QRect) -> list:
        s = self._scale
        return [
            qrect.x() / s, qrect.y() / s,
            (qrect.x() + qrect.width()) / s,
            (qrect.y() + qrect.height()) / s,
        ]

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.position().toPoint()
            self._drag_rect = None

    def mouseMoveEvent(self, e):
        if self._drag_start and e.buttons() & Qt.MouseButton.LeftButton:
            self._drag_rect = QRect(self._drag_start,
                                    e.position().toPoint()).normalized()
            self._render()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._drag_rect:
            if self._drag_rect.width() > 10 and self._drag_rect.height() > 10:
                pdf_rect = self._screen_to_pdf(self._drag_rect)
                extracted = ""
                if self._pdf_page:
                    from core.text_snap import snap_selection
                    snapped, extracted = snap_selection(
                        self._pdf_page, pdf_rect, self._snap_mode)
                    # 텍스트가 잡히면 문장 전체 영역으로 확장,
                    # 안 잡히면(도면) 드래그 영역 그대로 사용
                    if extracted:
                        pdf_rect = snapped
                self.selection_made.emit(pdf_rect, extracted)
            self._drag_start = None
            self._drag_rect = None
            self._render()

    def wheelEvent(self, e: QWheelEvent):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = e.angleDelta().y()
            factor = 1.15 if delta > 0 else 0.87
            new_scale = max(0.3, min(5.0, self._scale * factor))
            self.set_scale(new_scale)
            e.accept()
        else:
            super().wheelEvent(e)


class DocumentViewer(QWidget):
    """단일 문서(PDF/이미지) 뷰어 탭."""
    mapping_requested = pyqtSignal(str, int, list, str)
    # (term_id, 검색 키워드) — 키워드를 그 용어의 선행문헌 표기로 등록 요청
    alias_requested = pyqtSignal(str, str)

    def __init__(self, doc_path: str, use_ocr: bool = False, parent=None):
        super().__init__(parent)
        self.doc_path = doc_path
        self.use_ocr = use_ocr
        self._doc: Optional[fitz.Document] = None
        self._current_page = 0
        self._scale = 1.5
        self._terms: list = []
        self._setup_ui()
        self._load_document()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 도구바
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        prev_btn = QPushButton("◀")
        prev_btn.setFixedWidth(42)
        prev_btn.clicked.connect(self._prev_page)
        toolbar.addWidget(prev_btn)

        self.page_label = QLabel("0 / 0")
        self.page_label.setStyleSheet("font-weight: bold; min-width: 60px;")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(self.page_label)

        next_btn = QPushButton("▶")
        next_btn.setFixedWidth(42)
        next_btn.clicked.connect(self._next_page)
        toolbar.addWidget(next_btn)

        toolbar.addSpacing(8)

        zoom_out = QPushButton("−")
        zoom_out.setFixedWidth(42)
        zoom_out.clicked.connect(lambda: self._zoom(0.8))
        toolbar.addWidget(zoom_out)

        self.zoom_label = QLabel("150%")
        self.zoom_label.setFixedWidth(40)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(self.zoom_label)

        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(42)
        zoom_in.clicked.connect(lambda: self._zoom(1.25))
        toolbar.addWidget(zoom_in)

        fit_btn = QPushButton("맞춤")
        fit_btn.setFixedWidth(54)
        fit_btn.clicked.connect(self._zoom_fit)
        toolbar.addWidget(fit_btn)

        toolbar.addSpacing(8)

        # 드래그 선택 스냅 모드
        toolbar.addWidget(QLabel("선택:"))
        self.snap_combo = QComboBox()
        self.snap_combo.addItem("문장 단위", "sentence")
        self.snap_combo.addItem("줄 단위", "line")
        self.snap_combo.addItem("영역 그대로", "none")
        self.snap_combo.setFixedWidth(112)
        self.snap_combo.setToolTip(
            "문장 단위: 드래그가 문장 일부만 걸쳐도 문장 전체를 가져옵니다\n"
            "줄 단위: 걸친 줄 전체를 가져옵니다\n"
            "영역 그대로: 드래그한 영역만 (도면 캡처용)")
        self.snap_combo.currentIndexChanged.connect(
            lambda: self.canvas.set_snap_mode(self.snap_combo.currentData()))
        toolbar.addWidget(self.snap_combo)

        toolbar.addStretch()

        # 키워드 검색 (여러 키워드 동시, 색상별 하이라이트 + 히트 네비게이션)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("키워드 검색 (쉼표/공백으로 여러 개)")
        self.search_input.setMinimumWidth(180)
        self.search_input.setMaximumWidth(260)
        self.search_input.setToolTip(
            "여러 키워드를 쉼표(,) 또는 공백으로 구분해 입력하면\n"
            "키워드마다 다른 색으로 문서 전체에 하이라이트됩니다.\n"
            "Enter/▼: 다음 결과로 이동, ▲: 이전 결과")
        self.search_input.returnPressed.connect(self._search_or_next)
        search_btn = QPushButton("검색")
        search_btn.setFixedWidth(58)
        search_btn.clicked.connect(self._search_or_next)
        self.hit_label = QLabel("")
        self.hit_label.setStyleSheet("color: #69737E; min-width: 52px;")
        self.hit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_hit_btn = QPushButton("▲")
        prev_hit_btn.setFixedWidth(42)
        prev_hit_btn.setToolTip("이전 검색 결과")
        prev_hit_btn.clicked.connect(lambda: self._goto_hit(-1))
        next_hit_btn = QPushButton("▼")
        next_hit_btn.setFixedWidth(42)
        next_hit_btn.setToolTip("다음 검색 결과")
        next_hit_btn.clicked.connect(lambda: self._goto_hit(1))
        self.term_btn = QPushButton("용어 색")
        self.term_btn.setFixedWidth(64)
        self.term_btn.setToolTip(
            "검색한 단어를 청구항 용어의 '선행문헌 표기'로 등록합니다.\n"
            "등록하면 그 단어가 용어와 같은 색으로 표시되고,\n"
            "매핑·도면 캡처·보고서에서도 같은 색이 적용됩니다.")
        self.term_btn.clicked.connect(self._show_term_menu)
        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(42)
        clear_btn.setToolTip("검색 지우기")
        clear_btn.clicked.connect(self._clear_search)
        toolbar.addWidget(self.search_input)
        toolbar.addWidget(search_btn)
        toolbar.addWidget(prev_hit_btn)
        toolbar.addWidget(next_hit_btn)
        toolbar.addWidget(self.hit_label)
        toolbar.addWidget(self.term_btn)
        toolbar.addWidget(clear_btn)

        # 검색 상태
        self._search_hits: list = []      # [(page, fitz.Rect, kw_idx)]
        self._search_kws: list = []
        self._search_idx: int = -1
        self._last_query: str = ""

        layout.addLayout(toolbar)

        # 메인 스플리터: 썸네일(좌) + 페이지(우)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 썸네일
        self.thumb_list = QListWidget()
        self.thumb_list.setFixedWidth(100)
        self.thumb_list.setIconSize(QSize(80, 110))
        self.thumb_list.currentRowChanged.connect(self._goto_page)
        self.thumb_list.setStyleSheet("QListWidget::item { padding: 2px; }")
        splitter.addWidget(self.thumb_list)

        # 페이지 캔버스
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.canvas = PageCanvas()
        self.canvas.selection_made.connect(self._on_selection)
        self.scroll_area.setWidget(self.canvas)
        splitter.addWidget(self.scroll_area)

        splitter.setSizes([100, 700])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

    def _load_document(self):
        if not os.path.exists(self.doc_path):
            return
        try:
            ext = os.path.splitext(self.doc_path)[1].lower()
            if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".gif"):
                img_doc = fitz.open(self.doc_path)
                pdfbytes = img_doc.convert_to_pdf()
                img_doc.close()
                self._doc = fitz.open("pdf", pdfbytes)
            else:
                self._doc = fitz.open(self.doc_path)
            self._build_thumbnails()
            self._goto_page(0)
        except Exception as e:
            print(f"[DocumentViewer] load error: {e}")
            import traceback
            traceback.print_exc()

    def _build_thumbnails(self):
        if not self._doc:
            return
        self.thumb_list.clear()
        for i in range(len(self._doc)):
            page = self._doc[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(0.15, 0.15), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height,
                         pix.stride, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(img)
            icon = QIcon(pixmap)
            item = QListWidgetItem(icon, f"{i+1}")
            self.thumb_list.addItem(item)

    def _goto_page(self, index: int):
        if not self._doc or index < 0 or index >= len(self._doc):
            return
        self._current_page = index
        page = self._doc[index]
        self.canvas.set_page(page, index, self._scale)
        self.page_label.setText(f"{index+1} / {len(self._doc)}")
        self.thumb_list.blockSignals(True)
        self.thumb_list.setCurrentRow(index)
        self.thumb_list.blockSignals(False)
        # 검색 중이면 이 페이지의 하이라이트 표시 유지
        if getattr(self, "_search_hits", None):
            self._refresh_search_display()

    def _prev_page(self):
        self._goto_page(self._current_page - 1)

    def _next_page(self):
        self._goto_page(self._current_page + 1)

    def _zoom(self, factor: float):
        self._scale = max(0.3, min(5.0, self._scale * factor))
        self.canvas.set_scale(self._scale)
        self.zoom_label.setText(f"{int(self._scale * 100)}%")

    def _zoom_fit(self):
        """뷰어 너비에 맞춰 줌."""
        if not self._doc or not self._doc[self._current_page]:
            return
        page = self._doc[self._current_page]
        pw = page.rect.width
        view_w = self.scroll_area.viewport().width() - 20
        if pw > 0 and view_w > 0:
            self._scale = view_w / pw
            self.canvas.set_scale(self._scale)
            self.zoom_label.setText(f"{int(self._scale * 100)}%")

    # ---------------------------------------------- 키워드 검색 (WIPS ON식)

    # 키워드별 하이라이트 색 (형광펜 팔레트, 순환)
    SEARCH_COLORS = [
        (255, 235, 59),   # 노랑
        (129, 199, 132),  # 초록
        (79, 195, 247),   # 하늘
        (244, 143, 177),  # 분홍
        (255, 183, 77),   # 주황
        (179, 157, 219),  # 보라
        (128, 222, 234),  # 청록
        (197, 225, 165),  # 연두
    ]

    def _parse_keywords(self, query: str) -> list:
        """쉼표 기준 구문 검색 + 등록된 여러 단어 용어는 한 덩어리로 유지.

        'host material'처럼 두 단어가 합쳐져 하나의 구성요소인 용어를
        host / material로 쪼개 검색하면 material만 따로 색칠된다.
        """
        return parse_keywords(query, self._terms)

    def set_terms(self, terms: list):
        """프로젝트 매칭 용어 리스트(참조)를 설정."""
        self._terms = terms or []
        if getattr(self, "_search_hits", None):
            self._refresh_search_display()

    def _term_for_keyword(self, kw: str):
        """검색 키워드가 등록 용어(또는 그 별칭)와 일치하면 해당 용어 반환."""
        low = (kw or "").strip().lower()
        if not low:
            return None
        for t in self._terms:
            for txt in term_texts(t):
                tl = txt.lower()
                if low == tl or low == tl + "s" or low + "s" == tl:
                    return t
        return None

    def _hit_color(self, ki: int) -> tuple:
        """등록 용어와 일치하는 키워드는 용어 색, 아니면 형광펜 팔레트."""
        if 0 <= ki < len(self._search_kws):
            t = self._term_for_keyword(self._search_kws[ki])
            if t is not None:
                return tuple(t.color_rgb)
        return self.SEARCH_COLORS[ki % len(self.SEARCH_COLORS)]

    def _show_term_menu(self):
        """검색어를 어느 용어의 선행문헌 표기로 등록할지 고르는 메뉴."""
        from PyQt6.QtGui import QAction, QPixmap
        from PyQt6.QtWidgets import QMenu, QMessageBox

        kws = self._search_kws or self._parse_keywords(
            self.search_input.text().strip())
        if not kws:
            QMessageBox.information(
                self, "알림",
                "먼저 색을 지정할 단어를 검색해 주세요.")
            return
        if not self._terms:
            QMessageBox.information(
                self, "알림",
                "등록된 매칭 용어가 없습니다.\n"
                "왼쪽 청구항 패널에서 용어를 먼저 등록해 주세요.")
            return

        kw = kws[0] if len(kws) == 1 else ", ".join(kws)
        menu = QMenu(self)
        menu.addAction(f'"{kw}" → 아래 용어와 같은 색으로').setEnabled(False)
        menu.addSeparator()
        for t in self._terms:
            pm = QPixmap(14, 14)
            pm.fill(QColor(*tuple(t.color_rgb)))
            act = QAction(QIcon(pm), f"{t.term_id}  {t.text}", menu)
            act.triggered.connect(
                lambda _checked=False, tid=t.term_id: self._assign_terms(tid))
            menu.addAction(act)
        menu.exec(self.term_btn.mapToGlobal(
            self.term_btn.rect().bottomLeft()))

    def _assign_terms(self, term_id: str):
        kws = self._search_kws or self._parse_keywords(
            self.search_input.text().strip())
        for kw in kws:
            self.alias_requested.emit(term_id, kw)

    def _search_or_next(self):
        """검색어가 바뀌었으면 새로 검색, 같으면 다음 결과로."""
        query = self.search_input.text().strip()
        if not query:
            self._clear_search()
            return
        if query != self._last_query:
            self._run_search(query)
        else:
            self._goto_hit(1)

    def _run_search(self, query: str):
        self._last_query = query
        self._search_hits = []
        self._search_idx = -1
        self._search_kws = self._parse_keywords(query)
        if not self._doc or not self._search_kws:
            self._refresh_search_display()
            return

        from PyQt6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for pno in range(len(self._doc)):
                page = self._doc[pno]
                for ki, kw in enumerate(self._search_kws):
                    try:
                        for r in page.search_for(kw):
                            self._search_hits.append((pno, r, ki))
                    except Exception:
                        pass
            # 페이지 → 위→아래 → 좌→우 순서로 정렬
            self._search_hits.sort(
                key=lambda h: (h[0], round(h[1].y0, 1), h[1].x0))
        finally:
            QApplication.restoreOverrideCursor()

        if self._search_hits:
            self._goto_hit(1)          # 첫 결과로 이동
        else:
            self._refresh_search_display()

    def _goto_hit(self, delta: int):
        """이전/다음 검색 결과로 이동 (문서 전체 순환)."""
        if not self._search_hits:
            return
        self._search_idx = (self._search_idx + delta) % len(self._search_hits)
        pno, rect, _ki = self._search_hits[self._search_idx]
        if pno != self._current_page:
            self._goto_page(pno)
        self._refresh_search_display()
        # 히트 위치로 스크롤
        cx = int((rect.x0 + rect.x1) / 2 * self._scale)
        cy = int((rect.y0 + rect.y1) / 2 * self._scale)
        self.scroll_area.ensureVisible(cx, cy, 220, 180)

    def _refresh_search_display(self):
        """현재 페이지의 검색 하이라이트와 카운터 갱신."""
        items = []
        for i, (pno, rect, ki) in enumerate(self._search_hits):
            if pno == self._current_page:
                items.append((rect, self._hit_color(ki),
                              i == self._search_idx))
        self.canvas.set_search_rects(items)

        if not self._last_query:
            self.hit_label.setText("")
        elif not self._search_hits:
            self.hit_label.setText("0건")
        else:
            self.hit_label.setText(
                f"{self._search_idx + 1}/{len(self._search_hits)}")

    def _clear_search(self):
        self.search_input.clear()
        self._search_hits = []
        self._search_kws = []
        self._search_idx = -1
        self._last_query = ""
        self.canvas.set_search_rects([])
        self.hit_label.setText("")

    def _on_selection(self, rect: list, extracted_text: str):
        self.mapping_requested.emit(
            self.doc_path, self._current_page, rect, extracted_text)

    def update_mappings(self, mappings: list[MappingEntry],
                        element_colors: dict[str, tuple] = None,
                        term_colors: dict[str, tuple] = None):
        page_mappings = [m for m in mappings if m.doc_path == self.doc_path]
        if element_colors:
            self.canvas.set_element_colors(element_colors)
        if term_colors is not None:
            self.canvas.set_term_colors(term_colors)
        self.canvas.set_mappings(page_mappings)

    def close_doc(self):
        if self._doc:
            self._doc.close()
            self._doc = None


class PDFViewerPanel(QWidget):
    """우측 PDF 뷰어 전체 패널 (여러 문서 탭)."""
    mapping_requested = pyqtSignal(str, int, list, str)
    alias_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._viewers: dict[str, DocumentViewer] = {}
        self._terms: list = []
        self._setup_ui()
        self._use_ocr = False

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 상단 버튼
        btn_bar = QHBoxLayout()
        open_btn = QPushButton("문서 열기")
        open_btn.setStyleSheet("font-weight: bold; padding: 5px 12px;")
        open_btn.clicked.connect(self.open_document_dialog)
        btn_bar.addWidget(open_btn)

        paste_btn = QPushButton("텍스트 붙여넣기")
        paste_btn.setToolTip(
            "PDF 대신 명세서 텍스트를 복사해 붙여넣습니다.\n"
            "문서 탭으로 변환되어 드래그 선택·검색·매핑이 그대로 동작합니다.")
        paste_btn.clicked.connect(self.open_pasted_text_dialog)
        btn_bar.addWidget(paste_btn)

        close_btn = QPushButton("현재 탭 닫기")
        close_btn.clicked.connect(self._close_current_tab)
        btn_bar.addWidget(close_btn)

        btn_bar.addStretch()

        self.ocr_label = QLabel("OCR 비활성")
        self.ocr_label.setStyleSheet("color: #888; font-size: 10px;")
        btn_bar.addWidget(self.ocr_label)
        layout.addLayout(btn_bar)

        # 탭 위젯 + 빈 상태 안내를 스택으로 겹침
        # (숨김/표시 방식은 레이아웃이 아래로 쏠리는 문제가 있어 스택 사용)
        from PyQt6.QtWidgets import QStackedWidget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)

        self.empty_label = QLabel(
            "선행문헌 (PDF/이미지)을 열어주세요\n\n"
            "1. 위의 '문서 열기' 버튼 클릭\n"
            "   (PDF가 없으면 '텍스트 붙여넣기'로 명세서 본문을 붙여넣어도 됩니다)\n"
            "2. PDF 또는 이미지 파일 선택\n"
            "3. 문서에서 영역을 마우스로 드래그\n"
            "4. 팝업에서 청구항 구성요소와 매핑\n\n"
            "여러 문서를 동시에 열어 비교할 수 있습니다.\n"
            "Ctrl+마우스 휠로 줌 인/아웃 가능합니다."
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            "color: #98A2AD; font-size: 12px; "
            "border: 2px dashed #C9D2D9; border-radius: 12px;")
        self.empty_label.setWordWrap(True)

        empty_page = QWidget()
        empty_lay = QVBoxLayout(empty_page)
        empty_lay.setContentsMargins(16, 10, 16, 16)
        empty_lay.addWidget(self.empty_label)   # 남는 공간 전체를 채움

        self.stack = QStackedWidget()
        self.stack.addWidget(empty_page)        # index 0: 빈 상태
        self.stack.addWidget(self.tab_widget)   # index 1: 문서 탭
        layout.addWidget(self.stack, stretch=1)

        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self._update_empty_state()

    def _update_empty_state(self):
        has_tabs = self.tab_widget.count() > 0
        self.stack.setCurrentIndex(1 if has_tabs else 0)

    def _on_tab_changed(self):
        self._update_empty_state()

    def open_document(self, path: str, label: str = ""):
        # 경로 정규화 (중복 방지)
        path = os.path.normpath(os.path.abspath(path))

        if path in self._viewers:
            for i in range(self.tab_widget.count()):
                w = self.tab_widget.widget(i)
                if w == self._viewers[path]:
                    self.tab_widget.setCurrentIndex(i)
                    return

        if is_text_doc(path):
            # 붙여넣은 텍스트는 PDF로 변환하지 않고 텍스트 그대로 보여준다
            viewer = TextDocumentViewer(path)
            label = label or doc_title(path)
        else:
            viewer = DocumentViewer(path, use_ocr=self._use_ocr)
        viewer.mapping_requested.connect(self.mapping_requested)
        viewer.alias_requested.connect(self.alias_requested)
        viewer.set_terms(self._terms)
        self._viewers[path] = viewer
        idx = self.tab_widget.addTab(viewer, label or os.path.basename(path))
        self.tab_widget.setCurrentIndex(idx)
        self._update_empty_state()

    def open_document_dialog(self):
        from PyQt6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self, "선행문헌 열기", "",
            "문서 파일 (*.pdf *.txt *.png *.jpg *.jpeg *.tiff *.bmp);;"
            "PDF (*.pdf);;텍스트 (*.txt);;이미지 (*.png *.jpg *.jpeg)"
        )
        for p in paths:
            self.open_document(p)

    def open_pasted_text_dialog(self):
        """명세서 텍스트를 붙여넣어 문서 탭으로 연다."""
        from ui.paste_text_dialog import PasteTextDialog
        from core.text_doc import save_text_doc

        dlg = PasteTextDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        title, text = dlg.get_result()
        if not text.strip():
            return
        path = save_text_doc(text, title)
        if not path:
            QMessageBox.warning(self, "오류",
                                "텍스트를 문서로 저장하지 못했습니다.")
            return
        self.open_document(path, label=title or "붙여넣은 명세서")

    def set_terms(self, terms: list):
        self._terms = terms or []
        for viewer in self._viewers.values():
            viewer.set_terms(self._terms)

    def _close_current_tab(self):
        idx = self.tab_widget.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    def _close_tab(self, index: int):
        widget = self.tab_widget.widget(index)
        if isinstance(widget, (DocumentViewer, TextDocumentViewer)):
            path = widget.doc_path
            widget.close_doc()
            self._viewers.pop(path, None)
            # 정규화된 경로로도 제거
            norm_path = os.path.normpath(os.path.abspath(path))
            self._viewers.pop(norm_path, None)
        self.tab_widget.removeTab(index)
        self._update_empty_state()

    def update_mappings(self, mappings: list[MappingEntry],
                        element_colors: dict[str, tuple] = None,
                        term_colors: dict[str, tuple] = None):
        for viewer in self._viewers.values():
            viewer.update_mappings(mappings, element_colors, term_colors)

    def get_open_paths(self) -> list[str]:
        return list(self._viewers.keys())

    def set_ocr(self, enabled: bool):
        self._use_ocr = enabled
        status = "OCR 활성" if enabled else "OCR 비활성"
        self.ocr_label.setText(status)
        self.ocr_label.setStyleSheet(
            "color: #4CAF50; font-weight: bold; font-size: 10px;" if enabled
            else "color: #888; font-size: 10px;")
