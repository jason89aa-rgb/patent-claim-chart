"""붙여넣은 명세서 텍스트를 PDF 문서로 만들어 뷰어에서 그대로 쓰게 한다.

PDF로 변환해두면 기존 기능(드래그 선택, 문장 스냅, 영역 캡처, 매핑,
키워드 검색)이 전부 변경 없이 동작한다.
"""
import hashlib
import os
import re
import tempfile

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

_OUT_DIR = os.path.join(tempfile.gettempdir(), "pcc_text_docs")

PAGE_W, PAGE_H = 595, 842          # A4 (pt)
MARGIN = 56
FONT_SIZE = 10.5
LINE_H = 15.5

_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ㄰-㆏]")


def _safe_name(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", (title or "").strip())
    return name[:60] or "붙여넣은 문서"


def _pick_font(text: str) -> str:
    """내장 폰트 선택. 한글은 'korea'라야 글자가 나온다."""
    if _HANGUL.search(text):
        return "korea"
    if any(ord(c) > 0x2E80 for c in text):
        return "japan"
    return "helv"


def _wrap_lines(text: str, width: float, fontname: str,
                size: float) -> list:
    """폭에 맞춰 줄바꿈. 단어 단위, 긴 토큰은 글자 단위로 쪼갠다."""
    def w(s: str) -> float:
        try:
            return fitz.get_text_length(s, fontname=fontname, fontsize=size)
        except Exception:
            return len(s) * size * 0.5

    out = []
    for para in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        para = para.rstrip()
        if not para.strip():
            out.append("")
            continue
        cur = ""
        for token in para.split(" "):
            cand = token if not cur else cur + " " + token
            if w(cand) <= width:
                cur = cand
                continue
            if cur:
                out.append(cur)
                cur = ""
            # 한 토큰이 통째로 넘치면 글자 단위로 분해 (한글 문장 대응)
            piece = ""
            for ch in token:
                if w(piece + ch) <= width:
                    piece += ch
                else:
                    out.append(piece)
                    piece = ch
            cur = piece
        if cur:
            out.append(cur)
    return out


def make_text_pdf(text: str, title: str = "붙여넣은 명세서") -> str | None:
    """텍스트를 A4 PDF로 렌더링하고 파일 경로를 반환."""
    if not FITZ_AVAILABLE or not (text or "").strip():
        return None

    os.makedirs(_OUT_DIR, exist_ok=True)
    digest = hashlib.md5(
        (title + "\x00" + text).encode("utf-8")).hexdigest()[:12]
    out = os.path.join(_OUT_DIR, f"{_safe_name(title)}_{digest}.pdf")
    if os.path.exists(out):
        return out

    fontname = _pick_font(text)
    content_w = PAGE_W - MARGIN * 2
    lines = _wrap_lines(text, content_w, fontname, FONT_SIZE)
    per_page = max(1, int((PAGE_H - MARGIN * 2) // LINE_H))

    doc = fitz.open()
    for i in range(0, len(lines), per_page):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        y = MARGIN + FONT_SIZE
        for line in lines[i:i + per_page]:
            if line:
                try:
                    page.insert_text((MARGIN, y), line,
                                     fontname=fontname, fontsize=FONT_SIZE)
                except Exception:
                    pass
            y += LINE_H

    if doc.page_count == 0:
        doc.close()
        return None
    doc.save(out)
    doc.close()
    return out


def clear_cache():
    if not os.path.isdir(_OUT_DIR):
        return
    for name in os.listdir(_OUT_DIR):
        try:
            os.remove(os.path.join(_OUT_DIR, name))
        except OSError:
            pass
