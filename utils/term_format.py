"""청구항 텍스트를 매칭 용어 색상 단위로 분할 (PPTX/Word/Excel 공용)."""
import re


def term_texts(term) -> list:
    """용어가 가진 모든 표기 (청구항 용어 + 선행문헌 별칭)."""
    texts = [getattr(term, "text", "")]
    texts += list(getattr(term, "aliases", None) or [])
    seen, out = set(), []
    for t in texts:
        t = (t or "").strip()
        low = t.lower()
        if t and low not in seen:
            seen.add(low)
            out.append(t)
    return out


def _text_term_pairs(terms: list) -> list:
    """[(표기, 용어), ...] — 긴 표기 우선 정렬."""
    pairs = []
    for t in (terms or []):
        for txt in term_texts(t):
            pairs.append((txt, t))
    return sorted(pairs, key=lambda p: -len(p[0]))


def split_by_terms(text: str, terms: list) -> list:
    """
    텍스트를 용어 경계로 쪼갠다.
    반환: [(조각 텍스트, (r,g,b) 또는 None), ...]
    None = 일반 텍스트, 색 = 해당 용어 색.
    """
    if not text:
        return []
    pairs = _text_term_pairs(terms)
    if not pairs:
        return [(text, None)]

    # 복수형도 함께 매칭: "power line" → "power lines"
    pattern = "|".join(re.escape(txt) + r's?' for txt, _ in pairs)

    chunks = []
    last = 0
    for m in re.finditer(pattern, text, re.IGNORECASE):
        if m.start() > last:
            chunks.append((text[last:m.start()], None))
        matched = m.group(0)
        term = _find_term(matched, pairs)
        color = tuple(term.color_rgb) if term else None
        chunks.append((matched, color))
        last = m.end()
    if last < len(text):
        chunks.append((text[last:], None))
    return chunks or [(text, None)]


def _find_term(matched: str, pairs: list):
    low = matched.lower()
    for txt, t in pairs:
        tl = txt.lower()
        if low == tl or low == tl + "s":
            return t
    for txt, t in pairs:
        if low.startswith(txt.lower()):
            return t
    return None


def _term_by_id(term_id: str, terms: list):
    for t in (terms or []):
        if getattr(t, "term_id", None) == term_id:
            return t
    return None


def chunks_from_spans(text: str, spans: list, terms: list) -> list:
    """
    사용자가 직접 지정한 단어 범위(term_spans)를 색상 조각으로 변환.
    spans: [[start, end, term_id], ...] (extracted_text 기준 문자 오프셋)
    """
    by_id = {getattr(t, "term_id", None): t for t in (terms or [])}
    valid = []
    for s in spans or []:
        try:
            start, end, tid = int(s[0]), int(s[1]), s[2]
        except (ValueError, TypeError, IndexError):
            continue
        if tid in by_id and 0 <= start < end <= len(text):
            valid.append((start, end, tid))
    valid.sort()

    chunks = []
    last = 0
    for start, end, tid in valid:
        if start < last:          # 겹치는 스팬은 건너뜀
            continue
        if start > last:
            chunks.append((text[last:start], None))
        chunks.append((text[start:end], tuple(by_id[tid].color_rgb)))
        last = end
    if last < len(text):
        chunks.append((text[last:], None))
    return chunks or [(text, None)]


FIGURE_REF_NOTE = "(도면 표시 참조)"


def evidence_chunks(mapping, terms: list) -> list:
    """
    선행문헌 추출 텍스트를 색상 조각으로 반환.

    우선순위:
    1. 사용자가 직접 칠한 단어 범위(term_spans) — 그 단어만 색칠
    2. 텍스트 안에 등록 요소 단어가 있으면 그 단어만 색칠(split_by_terms)
    3. 짧은 라벨(예: 'VDDL')뿐이면 단어를 따로 적지 않고 도면 참조로 대체
       — 해당 단어는 도면 이미지 안에 형광펜으로 표시되므로 중복 표기 불필요
    → 긴 문단을 통째로 칠하지 않는다.
    """
    text = getattr(mapping, "extracted_text", "") or ""
    spans = getattr(mapping, "term_spans", None) or []
    if spans:
        return chunks_from_spans(text, spans, terms)

    chunks = split_by_terms(text, terms)
    if any(c for _, c in chunks):
        return chunks

    term_id = getattr(mapping, "term_id", "") or ""
    stripped = text.strip()
    # 도면 라벨 수준의 짧은 한 줄 텍스트 → 단어 자체는 도면에 표시되므로 생략
    if term_id and stripped and len(stripped) <= 30 and "\n" not in stripped:
        return [(FIGURE_REF_NOTE, None)]
    return chunks


def terms_in_text(text: str, terms: list) -> list:
    """텍스트에 실제로 등장하는 용어만 반환 (범례용)."""
    if not text:
        return []
    found = []
    for t in (terms or []):
        for txt in term_texts(t):
            if re.search(re.escape(txt) + r's?', text, re.IGNORECASE):
                found.append(t)
                break
    return found
