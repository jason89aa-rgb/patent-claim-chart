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


def _column_clusters(words, page_rect) -> list:
    """본문 단어의 x-구간을 합쳐 단(column) 목록을 만든다.

    반환: [(x0, x1), ...] — 왼쪽부터.
    """
    top_cut = page_rect.y0 + page_rect.height * 0.08
    intervals = sorted(
        (w[0], w[2]) for w in words
        if w[4].strip() and not w[4].strip().isdigit()
        and w[1] > top_cut)
    if not intervals:
        return []
    merged = [list(intervals[0])]
    for a, b in intervals[1:]:
        if a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    # 아주 좁은 클러스터(행번호 띠 등)는 버린다
    width = page_rect.width
    return [(a, b) for a, b in merged if (b - a) > width * 0.12]


def _line_number_texts(lines: dict) -> set:
    """행번호(5, 10, 15 …)로 확신되는 단독 숫자줄만 골라낸다.

    도면부호도 3자리 이하 단독 숫자라 무조건 버리면 130·141·150 같은
    부호가 통째로 사라진다. 둘은 이렇게 다르다:
      행번호  — 같은 x대역에 세로로 늘어서고, 아래로 갈수록 값이 커지며
                대부분 5의 배수 (5, 10, 15 …)
      도면부호 — 값이 불규칙하고 증가 순서가 아니다 (190, 160, 143 …)
    두 조건을 모두 만족할 때만 행번호로 본다.
    """
    cands = []
    for ws in lines.values():
        ws.sort(key=lambda w: w[0])
        text = " ".join(w[4] for w in ws).strip()
        if text.isdigit() and len(text) <= 3:
            cx = (ws[0][0] + ws[-1][2]) / 2.0
            cands.append((cx, ws[0][1], text))
    if len(cands) < 4:
        return set()

    # x가 비슷한 것끼리 묶는다 (행번호는 한 줄로 정렬된다)
    out = set()
    cands.sort()
    band, bands = [cands[0]], []
    for c in cands[1:]:
        if abs(c[0] - band[-1][0]) <= 6.0:
            band.append(c)
        else:
            bands.append(band)
            band = [c]
    bands.append(band)

    for band in bands:
        if len(band) < 4:
            continue
        band.sort(key=lambda c: c[1])          # 위 → 아래
        vals = [int(c[2]) for c in band]
        increasing = all(b > a for a, b in zip(vals, vals[1:]))
        mult5 = sum(1 for v in vals if v % 5 == 0) >= len(vals) * 0.8
        if increasing and mult5:
            out.update(c[2] for c in band)
    return out


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

    # 행번호로 확신되는 것만 제외한다 (도면부호는 살린다)
    line_nums = _line_number_texts(lines)

    sublines = []
    for ws in lines.values():
        ws.sort(key=lambda w: w[0])
        text = " ".join(w[4] for w in ws).strip()
        if not text or text in line_nums:
            continue
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


# 문장이 끝났다고 볼 종결 부호 (약어 마침표는 아래에서 걸러낸다)
_SENT_TERM = re.compile(r'[.!?。？！]["\')\]]?\s*$')
# 문장 끝이 아닌 마침표 (Fig. 7 / No. 2 / U.S. / e.g.)
_ABBREV_END = re.compile(
    r'\b(?:Fig|FIG|No|Nos|Pat|Ser|Vol|Inc|Ltd|Co|Corp|et al|e\.g|i\.e|U\.S'
    r'|Dr|Mr|Ms|approx|cf|vs|[A-Z])\.\s*$')


def looks_unfinished(text: str) -> bool:
    """문단이 아직 안 끝났는지 (다음 장으로 이어지는지) 추정."""
    t = (text or "").strip()
    if not t:
        return False
    if _ABBREV_END.search(t):
        return True
    return not _SENT_TERM.search(t)


def reaches_page_bottom(page, rect: list, margin_ratio: float = 0.12) -> bool:
    """선택이 페이지 아래쪽 끝에 닿았는지 (본문이 잘렸을 가능성)."""
    try:
        page_h = page.rect.height
        return (page_h - float(rect[3])) <= page_h * margin_ratio
    except Exception:
        return False


def page_head_text(page, max_chars: int = 600) -> tuple:
    """페이지 맨 위 본문에서 첫 문장이 끝날 때까지의 텍스트.

    앞 페이지에서 이어지는 문단을 이어붙일 때 쓴다. 상단 머리글
    (특허번호 띠)과 여백의 행번호는 건너뛴다.
    반환: (rect, text) — 못 찾으면 (None, "")
    """
    if not FITZ_AVAILABLE or page is None:
        return None, ""
    try:
        words = page.get_text("words")
    except Exception:
        return None, ""

    page_rect = page.rect
    head_cut = page_rect.y0 + page_rect.height * 0.08   # 머리글 띠 제외
    body = [w for w in words
            if w[4].strip() and w[1] >= head_cut and not w[4].strip().isdigit()]
    if not body:
        return None, ""

    # 2단 조판에서 앞 페이지 끝 문단은 다음 페이지 '왼쪽 단 맨 위'로 이어진다.
    # 첫 줄로 단을 추정하면 좌우를 걸치는 줄에 속아 두 단이 섞이므로,
    # 단 클러스터를 직접 만들어 가장 왼쪽 단을 쓴다.
    cols = _column_clusters(words, page_rect)
    if not cols:
        return None, ""
    col_x0, col_x1 = cols[0]
    sublines = [(r, t) for r, t in _column_sublines(body, col_x0, col_x1)
                if r.y0 >= head_cut]
    if not sublines:
        return None, ""

    picked = []
    for r, t in sublines:
        picked.append((r, t))
        joined = " ".join(x[1] for x in picked)
        if not looks_unfinished(joined) or len(joined) >= max_chars:
            break
    return _finalize(picked)


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
