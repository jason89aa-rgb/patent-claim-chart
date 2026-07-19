"""드래그한 영역을 문장/문단 단위로 확장(스냅)해서 덩어리로 가져온다.

US 특허 같은 2단 레이아웃 대응:
PyMuPDF의 line/span은 좌우 단을 하나로 합쳐 반환하는 경우가 있어
(단 사이 간격이 좁으면 span 하나가 양쪽 단을 걸치기도 함),
단어(word) 좌표 기반으로 드래그한 단(column)의 x-범위를 플러드필로
탐지한 뒤 그 단에 속한 단어만으로 줄을 재구성한다.
"""
import re

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False


# 문장 끝 판정 (영문 마침표 + 한국어 종결)
_SENT_END = re.compile(r'[.;:!?]\s*$|[다요함음]\.\s*$')

# 문장 확장 상한 (한 방향, 폭주 방지)
_MAX_EXTEND = 25


def _rects_overlap(a, b, min_ratio: float = 0.3) -> bool:
    """b(텍스트 줄/단어)가 a(드래그 영역)에 걸쳤는지 판정.

    작은 드래그도 잡히도록 '드래그와 대상 중 더 작은 쪽 높이' 대비
    세로 겹침 비율로 본다.
    """
    inter = a & b
    if inter.is_empty:
        return False
    base_h = min(a.height, b.height)
    if base_h <= 0:
        return False
    return (inter.height / base_h) >= min_ratio


def _column_bounds(words, seed_cx: float, page_rect) -> tuple:
    """
    페이지 본문 단어들의 x-구간을 합쳐 컬럼 클러스터를 만들고,
    드래그 지점(seed_cx)이 속한 클러스터의 [x0, x1]을 반환.

    같은 단의 단어들은 x-커버리지가 연속되지만, 다른 단과는 가운데
    여백(글자가 전혀 없는 x-구간)으로 분리되므로 클러스터가 나뉜다.
    상단 헤더(특허번호 등 가운데를 걸치는 텍스트)와 행번호(숫자)는 제외.
    """
    top_cut = page_rect.y0 + page_rect.height * 0.08
    intervals = sorted(
        (w[0], w[2]) for w in words
        if w[4].strip() and not w[4].strip().isdigit()
        and w[1] > top_cut)
    if not intervals:
        return page_rect.x0, page_rect.x1

    merged = [list(intervals[0])]
    for a, b in intervals[1:]:
        if a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    for a, b in merged:
        if a - 2 <= seed_cx <= b + 2:
            return a, b
    return page_rect.x0, page_rect.x1


def _column_sublines(words, col_x0: float, col_x1: float) -> list:
    """해당 단에 속한 단어만으로 줄(sub-line)들을 재구성.

    반환: [(fitz.Rect, text), ...] — 위→아래 정렬.
    행번호 등 숫자만 있는 줄은 제외.
    """
    lines: dict = {}
    for w in words:
        t = w[4].strip()
        if not t:
            continue
        cx = (w[0] + w[2]) / 2
        if not (col_x0 - 2 <= cx <= col_x1 + 2):
            continue
        lines.setdefault((w[5], w[6]), []).append(w)

    sublines = []
    for ws in lines.values():
        ws.sort(key=lambda w: w[0])
        text = " ".join(w[4] for w in ws).strip()
        if not text or (text.isdigit() and len(text) <= 3):
            continue      # 행번호/페이지번호
        r = fitz.Rect(ws[0][0], ws[0][1], ws[0][2], ws[0][3])
        for w in ws[1:]:
            r |= fitz.Rect(w[0], w[1], w[2], w[3])
        sublines.append((r, text))

    sublines.sort(key=lambda s: (round(s[0].y0, 1), s[0].x0))
    return sublines


def _prepare(page, rect: list):
    """공통 전처리: 드래그가 걸린 단의 sub-line 목록과 hit 인덱스."""
    drag = fitz.Rect(*rect)
    try:
        words = page.get_text("words")
    except Exception:
        return None

    hit_words = [w for w in words
                 if w[4].strip() and _rects_overlap(
                     drag, fitz.Rect(w[0], w[1], w[2], w[3]))]
    if not hit_words:
        return None

    seed_cx = sum((w[0] + w[2]) / 2 for w in hit_words) / len(hit_words)
    col_x0, col_x1 = _column_bounds(words, seed_cx, page.rect)

    sublines = _column_sublines(words, col_x0, col_x1)
    hit_ks = [k for k, (r, t) in enumerate(sublines)
              if _rects_overlap(drag, r)]
    if not hit_ks:
        return None
    return sublines, hit_ks


def _finalize(selected: list) -> tuple:
    union = fitz.Rect(selected[0][0])
    for r, _ in selected[1:]:
        union |= r
    text = " ".join(t for _, t in selected)
    text = re.sub(r'([a-zA-Z])-\s+([a-z])', r'\1\2', text)
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return [union.x0, union.y0, union.x1, union.y1], text


def snap_to_lines(page, rect: list, min_ratio: float = 0.3) -> tuple:
    """드래그와 겹치는 줄 전체(같은 단만)로 확장."""
    prep = _prepare(page, rect)
    if not prep:
        return rect, ""
    sublines, hit_ks = prep
    selected = [sublines[k] for k in range(min(hit_ks), max(hit_ks) + 1)]
    return _finalize(selected)


def snap_to_sentences(page, rect: list) -> tuple:
    """줄 스냅에 더해, 잘린 문장의 앞뒤를 같은 단 안에서 보완해
    문장 덩어리 단위로 가져온다."""
    prep = _prepare(page, rect)
    if not prep:
        return rect, ""
    sublines, hit_ks = prep

    start_k, end_k = min(hit_ks), max(hit_ks)

    # 위로 확장: 이전 줄이 문장 끝이 아니면 문장 중간이므로 포함
    steps = 0
    while start_k > 0 and steps < _MAX_EXTEND:
        prev_text = sublines[start_k - 1][1]
        if _SENT_END.search(prev_text):
            break
        start_k -= 1
        steps += 1

    # 아래로 확장: 현재 줄이 문장 끝이 아니면 계속 포함
    steps = 0
    while end_k < len(sublines) - 1 and steps < _MAX_EXTEND:
        cur_text = sublines[end_k][1]
        if _SENT_END.search(cur_text):
            break
        end_k += 1
        steps += 1

    selected = [sublines[k] for k in range(start_k, end_k + 1)]
    return _finalize(selected)


def _is_region_drag(page, rect: list) -> bool:
    """사용자가 '영역'(도면/블록)을 의도적으로 크게 드래그했는지 판정.

    도면에도 라벨 텍스트가 많아 문장 스냅이 작동하면 엉뚱한 영역이
    잡히므로, 충분히 큰 드래그는 스냅하지 않고 그대로 존중한다.
    """
    try:
        pr = page.rect
        drag = fitz.Rect(*rect)
    except Exception:
        return False
    if pr.width <= 0 or pr.height <= 0:
        return False
    wr = drag.width / pr.width
    hr = drag.height / pr.height
    # 가로로 넓거나(단을 넘어섬) 세로로 큰 블록 → 영역 선택으로 간주
    if wr >= 0.45 and hr >= 0.12:
        return True
    if hr >= 0.30 and wr >= 0.25:
        return True
    return (drag.get_area() / pr.get_area()) >= 0.18


def snap_selection(page, rect: list, mode: str = "sentence") -> tuple:
    """
    mode: "sentence" (문장 덩어리) | "line" (줄) | "none" (원본 그대로)
    반환: (rect, text)

    mode가 sentence/line이어도 드래그가 크면(도면 등 영역 선택)
    지정한 영역을 그대로 유지한다.
    """
    if not FITZ_AVAILABLE or page is None:
        return rect, ""

    def clip_text() -> str:
        try:
            return page.get_text(clip=fitz.Rect(*rect)).strip()
        except Exception:
            return ""

    if mode == "none":
        return rect, clip_text()

    if _is_region_drag(page, rect):
        # 지정한 영역 그대로 + 그 안의 텍스트만 추출
        return rect, clip_text()

    if mode == "line":
        return snap_to_lines(page, rect)
    return snap_to_sentences(page, rect)
