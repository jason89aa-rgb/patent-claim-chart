"""청구항 텍스트에서 매칭 후보 용어(명사구)를 자동 추출."""
import re
from dataclasses import dataclass, field


@dataclass
class TermCandidate:
    text: str                       # 정규화된 용어 (예: "power line")
    count: int = 1                  # 청구항 내 출현 횟수
    element_ids: list = field(default_factory=list)  # 등장하는 구성요소들


# 명사구 앞에 붙는 한정사 (영문)
_DETERMINERS = (
    r'(?:a|an|the|said|each|one|at\s+least\s+one\s+of|'
    r'a\s+plurality\s+of|the\s+plurality\s+of|respective|corresponding)'
)

# 명사구를 구성할 수 없는 단어 (기능어/청구항 상투어)
_STOPWORDS = {
    'a', 'an', 'the', 'said', 'and', 'or', 'of', 'in', 'on', 'at', 'to',
    'for', 'with', 'by', 'from', 'along', 'between', 'through', 'into',
    'is', 'are', 'be', 'being', 'which', 'that', 'wherein', 'whereby',
    'comprising', 'comprises', 'including', 'includes', 'consisting',
    'configured', 'adapted', 'arranged', 'disposed', 'provided', 'formed',
    'connected', 'coupled', 'extending', 'extends', 'having', 'has',
    'least', 'one', 'plurality', 'each', 'other', 'another', 'same',
    'such', 'respective', 'corresponding', 'thereof', 'therein', 'claim',
    'according', 'device', 'apparatus', 'method', 'system',
    'first', 'second', 'third', 'fourth', 'fifth',
    'wherein', 'further', 'may', 'can', 'used', 'use', 'so', 'as', 'it',
    'their', 'its', 'above', 'below',
}

# 명사구가 여기서 끝난다고 보는 경계 단어 (접속사/전치사/동사)
# "a base substrate intersect" → "base substrate"
_BOUNDARY_WORDS = {
    'and', 'or', 'but', 'which', 'that', 'wherein', 'whereby', 'while',
    'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'from', 'along',
    'between', 'through', 'into', 'onto', 'over', 'under', 'across',
    'is', 'are', 'was', 'were', 'be', 'being', 'been', 'has', 'have',
    'comprising', 'comprises', 'including', 'includes', 'consisting',
    'configured', 'adapted', 'arranged', 'disposed', 'provided', 'formed',
    'connected', 'coupled', 'extending', 'extends', 'extend', 'having',
    'intersect', 'intersects', 'form', 'forms', 'providing', 'provides',
    'used', 'passing', 'passes', 'overlapping', 'overlaps', 'according',
    'cause', 'causes', 'emit', 'emits', 'emitting', 'said',
}

# 한국어 조사/기능어
_KO_STOPWORDS = {
    '상기', '있어서', '포함하는', '포함하고', '구비하는', '및', '또는',
    '제1', '제2', '제3', '복수의', '각각', '적어도', '하나의', '것을',
    '특징으로', '하는', '장치', '방법',
}

# 명사구 후보: (한정사)? + 형용사/명사 1~4개
_NP_PATTERN = re.compile(
    rf'\b{_DETERMINERS}\s+((?:[a-z][a-z\-]*\s+){{0,3}}[a-z][a-z\-]*s?)\b',
    re.IGNORECASE)

# 한국어 명사구: "상기 XXX" 또는 2글자 이상 한글 연쇄
_KO_NP_PATTERN = re.compile(r'(?:상기\s*)?([가-힣]{2,}(?:\s+[가-힣]{2,}){0,2})')


def _clean_phrase(phrase: str) -> str:
    """구문 앞쪽 기능어 제거 + 경계 단어에서 절단 + 정규화."""
    words = phrase.lower().split()
    # 앞쪽 기능어 제거
    while words and words[0] in _STOPWORDS:
        words.pop(0)
    # 경계 단어(접속사/전치사/동사)가 나오면 그 앞에서 절단
    for i, w in enumerate(words):
        if w in _BOUNDARY_WORDS:
            words = words[:i]
            break
    # 뒤쪽 기능어 제거
    while words and words[-1] in _STOPWORDS:
        words.pop()
    return " ".join(words)


def _singularize(phrase: str) -> str:
    """복수형 마지막 단어를 단수로 (power lines → power line)."""
    words = phrase.split()
    if not words:
        return phrase
    last = words[-1]
    if len(last) > 3 and last.endswith('ies'):
        words[-1] = last[:-3] + 'y'
    elif len(last) > 3 and last.endswith('es') and last[-3] in 'sxzh':
        words[-1] = last[:-2]
    elif len(last) > 3 and last.endswith('s') and not last.endswith('ss'):
        words[-1] = last[:-1]
    return " ".join(words)


def _is_valid(phrase: str) -> bool:
    if not phrase or len(phrase) < 3:
        return False
    words = phrase.split()
    if not words or len(words) > 4:
        return False
    # 모든 단어가 기능어면 제외
    if all(w in _STOPWORDS for w in words):
        return False
    # 숫자만 있는 경우 제외
    if all(w.isdigit() for w in words):
        return False
    return True


def extract_terms(text: str, min_count: int = 1) -> list[TermCandidate]:
    """
    청구항 텍스트에서 후보 용어(명사구)를 빈도순으로 추출.
    복수형은 단수형으로 통합 ("power lines"와 "power line"은 같은 용어).
    """
    if not text or not text.strip():
        return []

    counts: dict[str, int] = {}
    display: dict[str, str] = {}   # 정규형 -> 사용자에게 보여줄 원형

    def add(raw: str):
        cleaned = _clean_phrase(raw)
        if not _is_valid(cleaned):
            return
        key = _singularize(cleaned)
        if not _is_valid(key):
            return
        counts[key] = counts.get(key, 0) + 1
        # 더 짧은(단수) 표기를 대표형으로
        if key not in display or len(cleaned) < len(display[key]):
            display[key] = cleaned

    for m in _NP_PATTERN.finditer(text):
        add(m.group(1))

    # 한국어
    for m in _KO_NP_PATTERN.finditer(text):
        phrase = m.group(1).strip()
        words = [w for w in phrase.split() if w not in _KO_STOPWORDS]
        phrase = " ".join(words)
        if len(phrase) >= 2 and phrase not in _KO_STOPWORDS:
            counts[phrase] = counts.get(phrase, 0) + 1
            display.setdefault(phrase, phrase)

    result = [
        TermCandidate(text=display[k], count=v)
        for k, v in counts.items() if v >= min_count
    ]
    # 빈도 내림차순 → 단어 수 많은 순(구체적) → 알파벳순
    result.sort(key=lambda t: (-t.count, -len(t.text.split()), t.text))
    return result


def extract_terms_from_claim(claim) -> list[TermCandidate]:
    """
    Claim 객체에서 후보 용어 추출.
    구성요소가 분할되어 있으면 어떤 구성요소에 등장하는지도 기록.
    """
    text = claim.full_text or ""
    if not text.strip() and claim.elements:
        text = " ".join(e.text for e in claim.elements)

    candidates = extract_terms(text)

    if claim.elements:
        for cand in candidates:
            pattern = re.compile(
                re.escape(cand.text).replace(r'\ ', r'\s+') + r's?',
                re.IGNORECASE)
            for elem in claim.elements:
                if pattern.search(elem.text):
                    cand.element_ids.append(elem.element_id)
    return candidates
