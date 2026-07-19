"""청구항 텍스트를 구성요소(1A, 1B, ...) 단위로 자동 분할."""
import re
from dataclasses import dataclass


@dataclass
class ParsedElement:
    label: str    # "1A", "1B", ...
    text: str


def _make_labels(claim_num: int, n: int) -> list[str]:
    labels = []
    for i in range(n):
        suffix = ""
        tmp = i
        while True:
            suffix = chr(ord('A') + tmp % 26) + suffix
            tmp = tmp // 26 - 1
            if tmp < 0:
                break
        labels.append(f"{claim_num}{suffix}")
    return labels


def _find_preamble_split(text: str) -> int:
    """
    전문(preamble)과 본문(body) 분리점을 찾는다.
    핵심: 콜론이 붙은 transition keyword를 최우선으로 사용.
    "comprises:", "comprising:" 등 콜론이 있으면 그곳이 진짜 전환점.
    """
    # 1순위: 콜론이 붙은 transition keyword (가장 신뢰도 높음)
    colon_keywords = [
        r'(?:comprises|comprising|consists?\s+(?:essentially\s+)?of|including)\s*:',
        r'(?:포함하는|구비하는|이루어진)\s*:',
    ]
    colon_pattern = '|'.join(colon_keywords)
    colon_matches = list(re.finditer(colon_pattern, text, re.IGNORECASE))
    if colon_matches:
        # 마지막 콜론 transition 사용 (중첩 구조 대응)
        return colon_matches[-1].end()

    # 2순위: 콜론 없는 transition keyword (단독 문장인 경우)
    simple_keywords = [
        r'\bcomprising\b', r'\bconsisting\s+of\b', r'\bincluding\b',
        r'포함하는', r'구비하는', r'이루어진',
    ]
    simple_pattern = '|'.join(simple_keywords)
    # 뒤에 세미콜론이나 줄바꿈이 있는 패턴 우선
    for m in re.finditer(simple_pattern, text, re.IGNORECASE):
        after = text[m.end():m.end()+20].strip()
        # 뒤에 세미콜론으로 구분된 리스트가 오면 여기가 분리점
        remaining = text[m.end():]
        if ';' in remaining:
            return m.end()

    return -1


def _split_body(body: str) -> list[str]:
    """본문을 구성요소 단위로 분할. 우선순위: 세미콜론 > (a)(b) > 줄바꿈."""
    body = body.strip()

    # 1순위: 세미콜론 기준 (가장 일반적 특허 형식)
    # ";" 또는 "; and" 또는 "; 및" 패턴
    semi_parts = re.split(r';\s*(?:and\s+|및\s+)?', body)
    semi_parts = [p.strip() for p in semi_parts if p.strip()]
    if len(semi_parts) >= 2:
        return semi_parts

    # 2순위: (a)(b)(c) 또는 (i)(ii)(iii) 형식
    alpha_pattern = re.compile(r'(?:^|\n)\s*\([a-zA-Z가-힣]+\)\s*', re.MULTILINE)
    alpha_parts = alpha_pattern.split(body)
    alpha_parts = [p.strip() for p in alpha_parts if p.strip()]
    if len(alpha_parts) >= 2:
        return alpha_parts

    # 3순위: 줄바꿈 기준
    line_parts = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(line_parts) >= 2:
        return line_parts

    return [body]


def parse_claim(claim_text: str, claim_number: int = 1) -> list[ParsedElement]:
    """
    청구항 텍스트를 구성요소 리스트로 분할.
    반환값: ParsedElement 리스트 (label="1A", text="...")
    """
    text = claim_text.strip()
    if not text:
        return []

    # 청구항 번호 제거 (앞에 "1." 또는 "청구항 1." 등)
    text = re.sub(r'^\s*(?:청구항\s*)?\d+\.\s*', '', text)

    # 전문(preamble) / 본문(body) 분리
    split_pos = _find_preamble_split(text)

    if split_pos > 0:
        preamble = text[:split_pos].strip()
        body = text[split_pos:].strip()
    else:
        # transition word가 없으면 전체를 하나의 body로
        preamble = ""
        body = text

    # 본문 구성요소 분할
    body_parts = _split_body(body) if body else []

    # 최종 조합
    all_parts = []
    if preamble:
        all_parts.append(preamble)
    all_parts.extend(body_parts)

    # 빈 파트 제거
    all_parts = [p for p in all_parts if p.strip()]

    if not all_parts:
        all_parts = [text]

    labels = _make_labels(claim_number, len(all_parts))
    return [ParsedElement(label=lbl, text=txt) for lbl, txt in zip(labels, all_parts)]
