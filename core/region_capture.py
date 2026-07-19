"""PDF 영역(도면/문장)을 이미지로 캡처. 내보내기에서 사용."""
import hashlib
import os
import re
import tempfile

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False


_CACHE_DIR = os.path.join(tempfile.gettempdir(), "pcc_region_cache")

# 캡처 시 영역 바깥으로 남기는 여백 (PDF pt)
DEFAULT_PADDING = 12.0


def _cache_path(key: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
    return os.path.join(_CACHE_DIR, f"{digest}.png")


_EDGE_PUNCT = ".,;:()[]{}\"'`·-–—"


def _norm_token(s: str) -> str:
    return s.strip().strip(_EDGE_PUNCT).lower()


def _is_whole_word_hit(rect, target: str, page_words: list) -> bool:
    """rect가 target '단어 전체'를 가리키는지 검증.

    search_for는 부분 문자열도 잡는다(HVDDL 안의 VDDL). 게다가
    get_text(clip=히트영역)은 클립 밖 글자(H)를 잘라내고 남은 부분을
    단어로 재구성해 버리므로, 반드시 **클립 없는 페이지 전체 단어 목록**
    (page_words)과 대조해야 한다.
    """
    want = [_norm_token(t) for t in target.split() if _norm_token(t)]
    if not want:
        return False

    got = []
    for w in page_words:
        wr = fitz.Rect(w[0], w[1], w[2], w[3])
        # 같은 줄 판정: 세로 겹침이 충분해야
        vy = min(wr.y1, rect.y1) - max(wr.y0, rect.y0)
        if vy < min(rect.height, wr.height) * 0.5:
            continue
        # 가로 겹침이 실질적이어야 (살짝 스치는 이웃 라벨 제외)
        hx = min(wr.x1, rect.x1) - max(wr.x0, rect.x0)
        if hx <= max(0.5, min(rect.width, wr.width) * 0.2):
            continue
        got.append((wr.x0, _norm_token(w[4])))
    got.sort()
    # 히트 줄에 걸친 단어들이 정확히 target 토큰 열과 일치해야 함
    # (HVDDL이 걸치면 got=["hvddl"] ≠ ["vddl"] → 탈락)
    return [t for _, t in got if t] == want


def _find_word_rects(page, clip, text: str) -> list:
    """clip 영역 안에서 text가 '단어 단위로' 나타나는 위치들을 검색.

    HVDDL과 VDDL처럼 일부만 다른 단어가 섞이지 않도록 단어 경계를 검증한다.
    """
    text = (text or "").strip()
    if not text:
        return []

    try:
        page_words = page.get_text("words")   # 클립 없이 (경계 검증용)
    except Exception:
        page_words = []

    def search(q):
        try:
            return page.search_for(q, clip=clip) or []
        except Exception:
            return []

    rects = [r for r in search(text)
             if _is_whole_word_hit(r, text, page_words)]
    if rects:
        return rects

    # 구문 전체가 안 잡히면(줄바꿈 등) 단어 단위로 재시도 — 역시 경계 검증
    out = []
    for token in text.split():
        if len(_norm_token(token)) < 2:
            continue
        out.extend(r for r in search(token)
                   if _is_whole_word_hit(r, token, page_words))
    return out


def capture_region(doc_path: str, page_index: int, rect: list,
                   highlights: list = None,
                   word_marks: list = None,
                   padding: float = DEFAULT_PADDING,
                   dpi: int = 200) -> str | None:
    """
    PDF의 특정 영역을 PNG로 캡처하고 파일 경로를 반환.

    highlights:  [(rect, (r,g,b), label), ...] — 영역 테두리 박스.
    word_marks:  [(text, (r,g,b)), ...] — 영역 안에서 해당 단어를 찾아
                 형광펜처럼 반투명 색으로 칠한다 (요소 색 매칭 표시).
    반환값: PNG 경로 (실패 시 None)
    """
    if not FITZ_AVAILABLE or not os.path.exists(doc_path):
        return None

    highlights = highlights or []
    word_marks = word_marks or []
    key = (f"{doc_path}|{page_index}|{rect}|{highlights}|{word_marks}|"
           f"{padding}|{dpi}")
    out_path = _cache_path(key)
    if os.path.exists(out_path):
        return out_path

    try:
        doc = fitz.open(doc_path)
        if page_index >= len(doc):
            doc.close()
            return None
        page = doc[page_index]

        clip = fitz.Rect(*rect)
        if clip.is_empty or clip.is_infinite:
            doc.close()
            return None

        # 여백 추가 후 페이지 경계로 클램프
        clip = fitz.Rect(clip.x0 - padding, clip.y0 - padding,
                         clip.x1 + padding, clip.y1 + padding)
        clip = clip & page.rect
        if clip.is_empty:
            doc.close()
            return None

        # 하이라이트 박스를 페이지에 임시 주석으로 그린 뒤 렌더링
        annots = []
        for h_rect, color, _label in highlights:
            r = fitz.Rect(*h_rect)
            rgb = tuple(c / 255.0 for c in color)
            annot = page.add_rect_annot(r)
            annot.set_colors(stroke=rgb)
            annot.set_border(width=1.5)
            annot.set_opacity(0.9)
            annot.update()
            annots.append(annot)

        # 단어 형광펜: 영역 안에서 단어 위치를 찾아 반투명 색으로 칠함
        base_clip = fitz.Rect(*rect)
        for mark_text, color in word_marks:
            rgb = tuple(c / 255.0 for c in color)
            for wr in _find_word_rects(page, base_clip, mark_text):
                annot = page.add_rect_annot(wr)
                annot.set_colors(stroke=rgb, fill=rgb)
                annot.set_border(width=0)
                annot.set_opacity(0.35)
                annot.update()
                annots.append(annot)

        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip,
                              alpha=False)

        for annot in annots:
            page.delete_annot(annot)

        pix.save(out_path)
        doc.close()
        return out_path
    except Exception as e:
        print(f"[region_capture] error: {e}")
        return None


def _word_marks_for_mapping(m, colors: dict, terms: list) -> list:
    """매핑에서 이미지에 형광펜으로 칠할 (단어, 색) 목록을 도출.

    우선순위는 텍스트 색칠(evidence_chunks)과 동일:
    1) 사용자가 직접 칠한 단어 범위(term_spans)
    2) 텍스트에 등록 요소 단어가 그대로 등장하면 그 단어
    3) 짧은 라벨(예: 'VDDL')에 매칭 요소가 지정된 경우 라벨 자체
    """
    text = getattr(m, "extracted_text", "") or ""
    marks = []

    spans = getattr(m, "term_spans", None) or []
    if spans:
        for s in spans:
            try:
                start, end, tid = int(s[0]), int(s[1]), s[2]
            except (ValueError, TypeError, IndexError):
                continue
            frag = text[start:end].strip()
            color = colors.get(tid)
            if frag and color:
                marks.append((frag, tuple(color)))
        return marks

    matched = False
    for t in (terms or []):
        t_text = getattr(t, "text", "").strip()
        if t_text and re.search(re.escape(t_text) + r"s?", text,
                                re.IGNORECASE):
            marks.append((t_text, tuple(t.color_rgb)))
            matched = True
    if matched:
        return marks

    term_id = getattr(m, "term_id", "") or ""
    stripped = text.strip()
    color = colors.get(term_id)
    if (term_id and color and stripped and len(stripped) <= 30
            and "\n" not in stripped):
        marks.append((stripped, tuple(color)))
    return marks


def capture_for_mappings(mappings: list, colors: dict,
                         terms: list = None) -> str | None:
    """
    같은 영역(도면/문장)에 매핑된 여러 구성요소를 한 장의 이미지로 캡처.
    매핑된 요소에 대응하는 단어는 이미지 안에서 형광펜 색으로 표시된다.

    mappings: 같은 doc_path/page/rect를 공유하는 MappingEntry 리스트
    colors:   {element_id 또는 term_id: (r,g,b)}
    terms:    ClaimTerm 리스트 (단어 자동 매칭용)
    """
    if not mappings:
        return None
    first = mappings[0]
    # 같은 도면을 따로 드래그한 매핑들이 묶인 경우 → 합집합 영역으로 캡처
    region = _union_rect([list(m.rect) for m in mappings])
    highlights = []
    word_marks = []
    seen = set()
    for m in mappings:
        key = m.term_id if m.term_id and m.term_id in colors else m.element_id
        color = colors.get(key, (220, 50, 50))
        label = m.term_id or m.element_id
        highlights.append((tuple(m.rect), tuple(color), label))
        for mark in _word_marks_for_mapping(m, colors, terms or []):
            if mark not in seen:
                seen.add(mark)
                word_marks.append(mark)
    return capture_region(first.doc_path, first.page, region,
                          highlights=highlights, word_marks=word_marks)


def _rects_similar(r1, r2) -> bool:
    """두 영역이 '같은 도면/문장'을 가리키는지 판정 (겹침 기반).

    사용자가 같은 도면을 두 번 드래그하면 좌표가 조금씩 달라지므로
    정확히 일치하지 않아도 겹침이 크면 같은 영역으로 본다.
    """
    ix0, iy0 = max(r1[0], r2[0]), max(r1[1], r2[1])
    ix1, iy1 = min(r1[2], r2[2]), min(r1[3], r2[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    inter = (ix1 - ix0) * (iy1 - iy0)
    a1 = max((r1[2] - r1[0]) * (r1[3] - r1[1]), 1e-6)
    a2 = max((r2[2] - r2[0]) * (r2[3] - r2[1]), 1e-6)
    union = a1 + a2 - inter
    # IoU가 크거나, 한쪽이 다른 쪽에 대부분 포함되면 같은 영역
    return (inter / union) >= 0.5 or (inter / min(a1, a2)) >= 0.8


def _union_rect(rects: list) -> list:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[2] for r in rects)
    y1 = max(r[3] for r in rects)
    return [x0, y0, x1, y1]


def group_mappings_by_region(mappings: list) -> dict:
    """
    같은 영역(도면/문장)을 가리키는 매핑들을 묶는다.

    좌표가 정확히 같지 않아도 겹침이 크면(같은 도면을 따로 드래그)
    하나의 그룹으로 병합한다 → 보고서에 도면이 한 번만 들어가고
    여러 구성요소의 색이 함께 표시된다.

    반환: {(doc_path, page, union_rect_tuple): [MappingEntry, ...]}
    """
    clusters: list = []   # [doc, page, union_rect(list), [mappings]]
    for m in mappings:
        rect = list(m.rect)
        placed = False
        for c in clusters:
            if (c[0] == m.doc_path and c[1] == m.page
                    and _rects_similar(c[2], rect)):
                c[2] = _union_rect([c[2], rect])
                c[3].append(m)
                placed = True
                break
        if not placed:
            clusters.append([m.doc_path, m.page, rect, [m]])

    return {
        (doc, page, tuple(round(v, 1) for v in rect)): members
        for doc, page, rect, members in clusters
    }


def build_region_index(mappings: list) -> dict:
    """매핑ID → (그룹키, 그룹 전체 매핑들) 인덱스.

    보고서에서 같은 도면(그룹)이 여러 구성요소 행에 걸칠 때,
    이미지는 첫 행에만 넣고 나머지 행은 참조 표기하기 위해 사용.
    """
    index = {}
    for key, members in group_mappings_by_region(mappings).items():
        for m in members:
            index[m.mapping_id] = (key, members)
    return index


def clear_cache():
    """캡처 캐시 삭제."""
    if not os.path.isdir(_CACHE_DIR):
        return
    for name in os.listdir(_CACHE_DIR):
        try:
            os.remove(os.path.join(_CACHE_DIR, name))
        except OSError:
            pass
