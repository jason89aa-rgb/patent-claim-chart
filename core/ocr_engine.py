"""OCR 엔진 (pytesseract 래퍼, 선택적 활성화)."""
import io
import os
from typing import Optional

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False


# PATH에 없어도 표준 설치 경로에서 Tesseract를 자동 감지
_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
]


def _configure_tesseract():
    if not OCR_AVAILABLE:
        return
    try:
        pytesseract.get_tesseract_version()
        return  # PATH에 이미 있음
    except Exception:
        pass
    for p in _TESSERACT_CANDIDATES:
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            return


_configure_tesseract()

_available_langs: Optional[set] = None


def _resolve_lang(lang: str) -> str:
    """설치된 언어팩과 교집합으로 lang 문자열 조정 (kor 미설치 시 eng만)."""
    global _available_langs
    if _available_langs is None:
        try:
            _available_langs = set(pytesseract.get_languages(config=""))
        except Exception:
            _available_langs = set()
    if not _available_langs:
        return lang
    parts = [p for p in lang.split("+") if p in _available_langs]
    if parts:
        return "+".join(parts)
    return "eng" if "eng" in _available_langs else lang


def is_ocr_available() -> bool:
    if not OCR_AVAILABLE:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _pixmap_to_pil(pix):
    """
    fitz Pixmap을 PIL Image로 안전하게 변환.

    Image.frombytes(...pix.samples)는 채널 수(알파/CMYK)와 stride 패딩을
    무시하므로 픽스맵이 RGB가 아니면 메모리를 잘못 읽어 크래시한다.
    PyMuPDF가 인코딩한 PNG를 거쳐 변환하면 채널/stride를 안전하게 처리한다.
    """
    # PNG는 CMYK/알파 조합을 지원하지 않으므로 RGB로 정규화
    if pix.alpha or pix.colorspace is None or pix.n > 3:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _render_page_pixmap(page, dpi: int = 300, clip=None):
    """OCR용 페이지 렌더링. 항상 알파 없는 RGB로 강제.

    비정상적으로 큰 페이지(도면 원본 등)에서 메모리 폭주로
    네이티브 크래시가 나지 않도록 픽셀 수를 제한한다.
    """
    zoom = dpi / 72.0
    rect = clip if clip is not None else page.rect
    w = rect.width * zoom
    h = rect.height * zoom
    max_side = 3500.0          # 긴 변 최대 픽셀
    scale = min(1.0, max_side / max(w, h, 1.0))
    mat = fitz.Matrix(zoom * scale, zoom * scale)
    return page.get_pixmap(matrix=mat, clip=clip, alpha=False,
                           colorspace=fitz.csRGB)


def extract_text_from_page(doc_path: str, page_index: int,
                            use_ocr: bool = False,
                            lang: str = "kor+eng") -> str:
    """
    PDF/이미지에서 텍스트 추출.
    use_ocr=True이면 스캔본에도 대응.
    """
    if not FITZ_AVAILABLE:
        return ""

    ext = os.path.splitext(doc_path)[1].lower()

    if ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"):
        if use_ocr and OCR_AVAILABLE:
            img = Image.open(doc_path)
            return pytesseract.image_to_string(img, lang=_resolve_lang(lang))
        return ""

    # PDF 처리
    try:
        doc = fitz.open(doc_path)
        if page_index >= len(doc):
            return ""
        page = doc[page_index]
        text = page.get_text()

        # 텍스트가 거의 없으면 스캔본으로 판단 → OCR
        if use_ocr and OCR_AVAILABLE and len(text.strip()) < 30:
            pix = _render_page_pixmap(page, dpi=300)
            img = _pixmap_to_pil(pix)
            text = pytesseract.image_to_string(img, lang=_resolve_lang(lang))

        doc.close()
        return text
    except Exception as e:
        print(f"[OCR] extract error: {e}")
        return ""


def extract_text_from_rect(doc_path: str, page_index: int,
                            rect: list, use_ocr: bool = False,
                            lang: str = "kor+eng") -> str:
    """PDF에서 특정 영역(rect)의 텍스트만 추출."""
    if not FITZ_AVAILABLE:
        return ""
    try:
        doc = fitz.open(doc_path)
        if page_index >= len(doc):
            return ""
        page = doc[page_index]
        fitz_rect = fitz.Rect(rect)
        text = page.get_text(clip=fitz_rect)

        if use_ocr and OCR_AVAILABLE and len(text.strip()) < 10:
            pix = _render_page_pixmap(page, dpi=300, clip=fitz_rect)
            img = _pixmap_to_pil(pix)
            text = pytesseract.image_to_string(img, lang=_resolve_lang(lang))

        doc.close()
        return text.strip()
    except Exception as e:
        print(f"[OCR] rect extract error: {e}")
        return ""
