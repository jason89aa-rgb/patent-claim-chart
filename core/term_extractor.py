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

# 한국어 기능어 (명사 후보에서 제외)
_KO_STOPWORDS = {
    '상기', '있어서', '포함', '구비', '및', '또는', '이때', '여기서',
    '복수', '각각', '적어도', '하나', '것', '특징', '경우', '위해', '통해',
    '대하', '의하', '따르', '이상', '이하', '동안', '수', '때', '등',
    '다수', '소정', '일측', '타측', '내지', '사이', '다른', '각',
    '제1항', '제2항', '제3항', '제4항', '제5항', '청구항',
}

# 조사 — 명사 뒤에 붙는다. 긴 것부터 떼어낸다.
_KO_PARTICLES = sorted([
    '으로써', '으로서', '에서의', '에게서', '으로부터', '로부터',
    '에서', '에게', '으로', '이나', '이며', '이고', '까지', '부터',
    '보다', '처럼', '만큼', '마다', '조차', '라도', '이라', '와의', '과의',
    '의', '을', '를', '이', '가', '은', '는', '에', '로', '와', '과',
    '도', '만', '나', '며', '고',
], key=len, reverse=True)

# 용언(동사/형용사) 어미 — 이걸로 끝나면 서술부이므로 용어가 아니다.
# "배출시켜", "방지하는", "생산하도록", "가동하여" 등을 걸러낸다.
_KO_VERB_TAIL = re.compile(
    r'(?:하는|하여|하고|하며|하도록|하지|한다|해서|해야|했|하기|'
    r'되는|되어|되며|되고|되도록|된다|됐|되기|'
    r'시켜|시키는|시키고|시킨|시킬|'
    r'지는|지고|진다|짐|도록|'
    r'있는|있고|있어|있음|없는|없이|없음|같은|같이|'
    r'위해|위한|따라|따른|의해|의한|대한|대해|'
    r'이며|이고|이다|인|일|할|한|될|된|줄|주는)$')

# 명사로 보기 어려운 어미.
# '기'·'음'은 넣지 않는다 — 증발기·전환기처럼 기계 명칭에 흔히 쓰인다
# (하기·되기·있음 같은 명사형은 위 용언 어미에서 이미 걸러진다).
_KO_NON_NOUN = re.compile(r'(?:함|됨|짐)$')

_HANGUL_RE = re.compile(r'[가-힣]')

# 명사구 후보: (한정사)? + 형용사/명사 1~4개
_NP_PATTERN = re.compile(
    rf'\b{_DETERMINERS}\s+((?:[a-z][a-z\-]*\s+){{0,3}}[a-z][a-z\-]*s?)\b',
    re.IGNORECASE)

# 어절 단위 토큰 (제1증발기, S-HTL1 같은 혼합 표기 유지)
_KO_TOKEN_RE = re.compile(r'[가-힣A-Za-z0-9][가-힣A-Za-z0-9\-]*')


def _strip_particle(token: str) -> tuple:
    """어절에서 조사를 떼어낸다. 반환: (명사 어간, 조사가 있었는지).

    조사를 떼면 한 글자만 남는 어절('것을', '항에')은 명사 후보가
    아니므로 빈 어간을 돌려준다.
    """
    for p in _KO_PARTICLES:
        if token.endswith(p):
            stem = token[:-len(p)]
            return (stem, True) if len(stem) >= 2 else ("", True)
    return token, False


def _ko_noun(token: str) -> str:
    """어절이 명사(구성요소 후보)면 어간을, 아니면 빈 문자열을 반환."""
    if not _HANGUL_RE.search(token):
        return ""
    if _KO_VERB_TAIL.search(token):        # 서술부는 용어가 아니다
        return ""
    stem, _had = _strip_particle(token)
    if len(stem) < 2 or stem in _KO_STOPWORDS:
        return ""
    if _KO_VERB_TAIL.search(stem) or _KO_NON_NOUN.search(stem):
        return ""
    # 숫자만 남은 경우 제외
    if not _HANGUL_RE.search(stem):
        return ""
    return stem


# 단독으로는 용어가 아니지만 뒤 명사와 묶이면 의미가 있는 서수 ('제1 전극')
_KO_ORDINAL = re.compile(r'제\s*\d+')


def _ko_phrases(text: str) -> list:
    """한국어 문장에서 명사(구) 후보를 뽑는다.

    조사 없이 이어지는 명사는 복합어로 묶는다:
    '증발기 전환장치는' → '증발기 전환장치'
    '사출 성형의 냉각 시스템' → '사출 성형', '냉각 시스템'
    """
    out = []
    for sentence in re.split(r'[.,;:()\[\]{}]|\n', text):
        run = []          # 조사 없이 이어지는 명사 묶음
        for token in _KO_TOKEN_RE.findall(sentence):
            noun = _ko_noun(token)
            if not noun:
                if len(run) > 1:
                    out.append(" ".join(run))
                run = []
                continue
            _stem, had_particle = _strip_particle(token)
            # 서수('제1')는 단독 후보로 내지 않고 복합어에만 참여시킨다
            if not _KO_ORDINAL.fullmatch(noun):
                out.append(noun)
            run.append(noun)
            if had_particle:
                # 조사가 붙었으면 명사구가 여기서 끊긴다
                if len(run) > 1:
                    out.append(" ".join(run))
                run = []
        if len(run) > 1:
            out.append(" ".join(run))
    return out


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

    # 한국어 (조사·어미 처리 후 명사구만)
    for phrase in _ko_phrases(text):
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


# ---------------------------------------------------------------- 색칠 후보

# 매핑 창의 '자주 나온 단어' 후보 토큰.
# 문자로 시작하는 부호(VDDL·CNT8·S1_1)뿐 아니라 순수 숫자 도면부호
# (130, 20R, 100a)도 잡는다 — 한국 도면은 부호가 대부분 숫자다.
_CHIP_TOKEN_RE = re.compile(
    r"[A-Za-z가-힣][A-Za-z0-9_\-가-힣]*|\d{1,4}[A-Za-z가-힣]?")

# 도면부호로 보기 어려운 숫자 (연도·페이지·아주 큰 수)
_NOT_FIG_NUM = re.compile(r"^(?:1[89]\d{2}|20[0-4]\d)$")   # 1800~2049 = 연도


def frequent_words(text: str, terms: list = None, limit: int = 20) -> list:
    """선택 영역 텍스트에서 색칠할 만한 단어 후보를 추린다.

    도면 캡처는 원하는 부호 외에 다른 부호가 잔뜩 섞여 나와서
    눈으로 찾는 게 일이다 — 등록 용어(별칭 포함)와 일치하는 단어를
    맨 앞에, 나머지는 빈도순으로 늘어놓아 눌러서 고르게 한다.

    반환: [(단어, 등장 횟수, 매칭 ClaimTerm 또는 None), ...]
    """
    from utils.term_format import term_texts

    if not (text or "").strip():
        return []

    out = []
    taken = set()          # 이미 후보로 올린 표기 (소문자)

    # 1) 등록 용어·별칭이 실제 등장하면 최우선 (용어 색 힌트와 함께)
    for term in (terms or []):
        for txt in term_texts(term):
            low = txt.lower()
            if low in taken:
                continue
            pat = re.compile(
                r"(?<![A-Za-z0-9_가-힣])" + re.escape(txt) +
                r"s?(?![A-Za-z0-9_])", re.IGNORECASE)
            n = len(pat.findall(text))
            if n:
                taken.add(low)
                out.append((txt, n, term))

    # 2) 나머지 토큰을 빈도순으로 (기능어·숫자·용언은 제외)
    counts: dict = {}
    forms: dict = {}
    for tok in _CHIP_TOKEN_RE.findall(text):
        low = tok.lower()
        if low in _STOPWORDS or low in taken:
            continue
        if tok[0].isdigit():
            # 도면부호 — 한 자리(1, 2)는 도면 번호일 때가 많아 제외,
            # 연도로 보이는 값도 제외
            if len(tok) < 2 or _NOT_FIG_NUM.match(tok):
                continue
        elif len(tok) < 2:
            continue
        elif _HANGUL_RE.search(tok):
            stem = _ko_noun(tok)          # 조사 떼고 서술부 걸러냄
            if not stem or stem.lower() in taken:
                continue
            tok, low = stem, stem.lower()
        counts[low] = counts.get(low, 0) + 1
        forms.setdefault(low, tok)

    rest = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    for low, n in rest:
        if len(out) >= limit:
            break
        out.append((forms[low], n, None))
    return out[:limit]
