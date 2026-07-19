"""특허/선행문헌 PDF에서 청구범위(Claims) 섹션을 찾아 청구항별로 추출."""
import os
import re
from dataclasses import dataclass
from typing import Optional

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

from typing import Callable

from core.ocr_engine import extract_text_from_page, is_ocr_available


@dataclass
class ExtractedClaim:
    number: int
    text: str
    is_independent: bool = True
    parent_claim: Optional[int] = None


# 청구범위 섹션 시작 마커 (영문/국문)
_CLAIMS_START_PATTERNS = [
    r'what\s+is\s+claimed\s+is\s*[:\.]?',
    r'we\s+claim\s*[:\.]?',
    r'i\s+claim\s*[:\.]?',
    r'the\s+invention\s+claimed\s+is\s*[:\.]?',
    r'claims?\s+claimed\s+(?:is|are)\s*[:\.]?',
    r'(?:특허\s*)?청구\s*(?:의\s*)?범위',
    r'【\s*청구\s*범위\s*】',
    r'(?:patent\s+)?claims?\s*[:：]',
]

# 페이지 헤더/꼬리말 등 청구항 본문이 아닌 줄
_NOISE_LINE_PATTERNS = [
    r'^\s*US\s*\d{1,2}\s*[,.]?\s*\d{3}\s*[,.]?\s*\d{3}\s*[A-Z]\d?\s*$',
    r'^\s*US\s+\d{4}/\d+',
    r'^\s*\d+\s*$',                      # 단독 숫자 (행번호/페이지번호/컬럼번호)
    r'^\s*\d+\s+\d+\s*$',                # "43 44" 형태 컬럼 번호
    r'^\s*Sheet\s+\d+\s+of\s+\d+\s*$',
    r'^\s*[A-Z][a-z]{2}\.\s+\d{1,2},\s+\d{4}\s*$',   # "Jun. 21, 2022"
    r'^\s*U\.?S\.?\s+Patent\s*$',
    r'^\s*[\*\s]+$',                     # "* * * * *"
]
_NOISE_RE = re.compile('|'.join(_NOISE_LINE_PATTERNS))

# 종속항 판별
_DEP_PATTERNS = [
    r'(?:of|in|according\s+to|as\s+(?:claimed|recited|defined)\s+in)\s+'
    r'(?:any\s+(?:one\s+)?of\s+)?claims?\s+(\d+)',
    r'제\s*(\d+)\s*항',
]


def _page_text_two_column(page) -> str:
    """
    2단 레이아웃 페이지를 좌→우 컬럼 순서로 재구성.
    USPTO 특허처럼 기본 추출 시 좌우 컬럼 줄이 섞이는 문제 대응.
    중앙 여백(gutter)의 행번호(5, 10, 15...)는 제거.
    """
    words = page.get_text("words")
    if not words:
        return ""
    width = page.rect.width
    mid = width / 2
    gutter_band = width * 0.045
    header_limit = page.rect.height * 0.07  # 페이지 상단 헤더 영역

    cols: tuple[list, list] = ([], [])
    for w in words:
        x0, y0, x1, _, token = w[0], w[1], w[2], w[3], w[4]
        cx = (x0 + x1) / 2
        # 상단 헤더 (특허번호, 날짜 등) 제외
        if y0 < header_limit:
            continue
        # 컬럼 사이 여백에 있는 순수 숫자 = 행번호 → 제외
        if token.isdigit() and abs(cx - mid) < gutter_band:
            continue
        cols[0 if cx < mid else 1].append((y0, x0, token))

    lines_out = []
    for col in cols:
        col.sort(key=lambda k: k[0])
        # y좌표 3pt 이내는 같은 줄로 그룹핑
        groups: list[list] = []
        for y, x, token in col:
            if groups and abs(y - groups[-1][0]) <= 3:
                groups[-1][1].append((x, token))
            else:
                groups.append([y, [(x, token)]])
        for _, items in groups:
            items.sort()
            lines_out.append(" ".join(t for _, t in items))
    return "\n".join(lines_out)


def _extract_candidate_texts(pdf_path: str) -> list[str]:
    """
    PDF 전체 텍스트(내장 텍스트 레이어)를 두 가지 방식으로 추출.
    1) 기본 추출 (단일 컬럼 문서용)
    2) 2단 컬럼 재구성 (USPTO 등 2단 문서용)
    """
    if not FITZ_AVAILABLE:
        return []

    raw_pages = []
    col_pages = []
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            try:
                raw_pages.append(page.get_text())
            except Exception:
                raw_pages.append("")
            try:
                col_pages.append(_page_text_two_column(page))
            except Exception:
                col_pages.append("")
        doc.close()
    except Exception as e:
        print(f"[ClaimsExtractor] open error: {e}")
        return []

    candidates = ["\n".join(raw_pages)]
    col_text = "\n".join(col_pages)
    if col_text.strip():
        candidates.append(col_text)
    return candidates


def _clean_lines(text: str) -> str:
    """헤더/행번호 등 노이즈 줄 제거 + 하이픈 줄바꿈 결합."""
    lines = [ln for ln in text.splitlines() if not _NOISE_RE.match(ln)]
    text = "\n".join(lines)
    # "compris-\ning" → "comprising"
    text = re.sub(r'([a-zA-Z])-\s*\n\s*([a-z])', r'\1\2', text)
    return text


def _find_claims_section(text: str) -> str:
    """청구범위 섹션 시작 이후 텍스트를 반환. 못 찾으면 전체 반환."""
    best = -1
    for pat in _CLAIMS_START_PATTERNS:
        matches = list(re.finditer(pat, text, re.IGNORECASE))
        if matches:
            # 마지막 매치 사용 (요약/명세서 본문에서 언급되는 경우 회피)
            pos = matches[-1].end()
            if pos > best:
                best = pos
    if best >= 0:
        return text[best:]
    return text


def _split_numbered(section: str) -> list[tuple[int, str]]:
    """'1. ...' 또는 '청구항 1' 형식으로 청구항 분리."""
    patterns = [
        re.compile(r'(?m)^\s*【?\s*청구항\s*(\d{1,3})\s*】?\s*[\.]?\s*'),
        re.compile(r'(?m)^\s*(\d{1,3})\s*\.\s+'),
    ]

    best_chain: list[tuple[int, re.Match]] = []
    for pat in patterns:
        matches = list(pat.finditer(section))
        # 번호가 1부터 순차 증가하는 체인만 채택 (본문 속 "2." 오탐 방지)
        chain: list[tuple[int, re.Match]] = []
        expected = 1
        for m in matches:
            n = int(m.group(1))
            if n == expected:
                chain.append((n, m))
                expected += 1
        if len(chain) > len(best_chain):
            best_chain = chain

    if not best_chain:
        return []

    result = []
    for idx, (num, m) in enumerate(best_chain):
        start = m.end()
        end = best_chain[idx + 1][1].start() if idx + 1 < len(best_chain) \
            else len(section)
        body = section[start:end].strip()
        # 마지막 청구항 뒤 "* * * * *" 등 제거
        body = re.sub(r'[\*\s]+$', '', body)
        if body:
            result.append((num, body))
    return result


def _detect_dependency(claim_text: str, own_number: int) -> Optional[int]:
    """종속항이면 인용하는 청구항 번호 반환, 독립항이면 None."""
    head = claim_text[:300]
    for pat in _DEP_PATTERNS:
        m = re.search(pat, head, re.IGNORECASE)
        if m:
            ref = int(m.group(1))
            if ref < own_number:
                return ref
    return None


def _normalize(text: str) -> str:
    """청구항 본문 정리: 줄바꿈을 공백으로, 추출 아티팩트 정리."""
    text = re.sub(r'\s*\n\s*', ' ', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # "intra - pixel" → "intra-pixel"
    text = re.sub(r'(?<=[a-zA-Z]) - (?=[a-zA-Z])', '-', text)
    # 구두점 앞 공백 제거: "claim 11 ," → "claim 11,"
    text = re.sub(r'\s+([,;.:])', r'\1', text)
    return text.strip()


# 진행률 콜백: cb(현재 페이지 수, 전체 페이지 수) -> False 반환 시 취소
ProgressCallback = Callable[[int, int], bool]


def extract_claims_from_pdf(pdf_path: str,
                            use_ocr: bool = True,
                            progress_cb: Optional[ProgressCallback] = None
                            ) -> list[ExtractedClaim]:
    """
    특허 PDF에서 청구항 목록을 추출.
    텍스트 레이어 우선, 없으면(스캔본) OCR로 폴백.
    반환값: ExtractedClaim 리스트 (비어 있으면 추출 실패/취소).
    """
    if not os.path.exists(pdf_path):
        return []

    best: list[ExtractedClaim] = []
    for candidate in _extract_candidate_texts(pdf_path):
        if not candidate.strip():
            continue
        claims = extract_claims_from_text(candidate)
        if len(claims) > len(best):
            best = claims
    if best:
        return best

    # 텍스트 레이어로 실패 → 스캔본 가능성, OCR 시도
    if use_ocr and is_ocr_available():
        return _extract_claims_via_ocr(pdf_path, progress_cb)
    return []


def _has_claims_marker(text: str) -> bool:
    """청구범위 섹션 시작 마커가 텍스트에 있는지."""
    for pat in _CLAIMS_START_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def _extract_claims_via_ocr(pdf_path: str,
                            progress_cb: Optional[ProgressCallback] = None
                            ) -> list[ExtractedClaim]:
    """
    스캔본 PDF를 OCR로 추출.

    청구범위는 명세서 맨 뒤에 있으므로 **마지막 페이지부터 거꾸로** OCR하며
    페이지를 읽을 때마다 추출을 시도하고, 청구범위 마커와 청구항이 잡히는
    즉시 중단한다 → 전체 명세서를 읽지 않아 빠르고 안전하다.
    """
    if not FITZ_AVAILABLE:
        return []
    try:
        doc = fitz.open(pdf_path)
        n_pages = len(doc)
        doc.close()
    except Exception:
        return []

    ocr_texts: dict[int, str] = {}
    processed = 0

    for i in range(n_pages - 1, -1, -1):
        if progress_cb and not progress_cb(processed + 1, n_pages):
            return []   # 사용자 취소
        ocr_texts[i] = extract_text_from_page(pdf_path, i, use_ocr=True)
        processed += 1

        joined = "\n".join(ocr_texts[k] for k in sorted(ocr_texts))
        # 마커까지 확인된 경우에만 조기 종료 (뒷장의 번호 목록 오탐 방지)
        if _has_claims_marker(joined):
            claims = extract_claims_from_text(joined)
            if claims:
                return claims

    # 전체를 읽었는데 마커를 못 찾은 경우 마지막으로 한 번 더 시도
    joined = "\n".join(ocr_texts[k] for k in sorted(ocr_texts))
    return extract_claims_from_text(joined)


def diagnose_extraction_failure(pdf_path: str) -> str:
    """추출 실패 원인을 사용자에게 보여줄 한국어 메시지로 진단."""
    if not FITZ_AVAILABLE:
        return "PDF 처리 모듈(PyMuPDF)을 사용할 수 없습니다."
    try:
        doc = fitz.open(pdf_path)
        n_pages = len(doc)
        text_pages = sum(1 for p in doc if len(p.get_text().strip()) > 30)
        doc.close()
    except Exception as e:
        return f"PDF 파일을 열 수 없습니다: {e}"

    if text_pages == 0:
        if not is_ocr_available():
            return (f"이 PDF는 텍스트 레이어가 없는 스캔본입니다 "
                    f"(전체 {n_pages}페이지).\n\n"
                    "OCR(Tesseract)을 사용할 수 없어 추출이 불가능합니다.\n"
                    "Tesseract 설치 후 다시 시도하거나, 텍스트가 포함된 PDF\n"
                    "(예: Google Patents에서 받은 PDF)를 사용해 주세요.")
        return (f"이 PDF는 스캔본이라 OCR로 추출을 시도했지만 "
                f"청구범위를 찾지 못했습니다 (전체 {n_pages}페이지).\n\n"
                "스캔 품질이 낮거나 청구범위 형식이 인식되지 않았을 수 있습니다.\n"
                "청구범위 텍스트를 직접 붙여넣고 '자동 분할'을 사용해 주세요.")
    return ("PDF에 텍스트는 있지만 청구범위 섹션을 찾지 못했습니다.\n\n"
            "- 청구범위가 포함된 특허 공보 PDF인지 확인해 주세요.\n"
            "- 청구범위 텍스트를 직접 붙여넣고 '자동 분할'을 사용할 수도 있습니다.")


# ---------------------------------------------------------- 프로세스 격리
def extract_claims_in_subprocess(pdf_path: str,
                                 progress_cb: Optional[ProgressCallback]
                                 = None) -> tuple:
    """
    청구항 추출을 별도 프로세스에서 실행 (크래시 격리).

    자기 자신(exe 또는 main.py)을 `--extract-claims` 플래그로 실행하고
    stdout 라인 프로토콜(PROGRESS/DONE/ERROR)로 통신한다.
    PyInstaller onefile에서 multiprocessing이 부모 GUI까지 무너뜨리는
    문제가 있어 단순 CLI 자식 프로세스 방식을 사용한다.

    반환: (claims 리스트, 오류 메시지 또는 None)
    - 자식이 네이티브 크래시로 죽어도 GUI는 살아남는다.
    - progress_cb가 False를 반환하면 자식을 종료하고 취소한다.
    """
    import json
    import subprocess
    import sys
    import tempfile

    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="pcc_claims_")
    os.close(fd)

    env = None
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--extract-claims", pdf_path, out_path]
        # PyInstaller onefile 필수: 자식을 '완전히 독립된 인스턴스'로 실행.
        # 기본값으로 두면 자식이 부모의 압축해제 임시폴더(_MEI)를 공유하고,
        # 자식 종료 시 그 폴더가 정리되면서 부모 GUI의 DLL이 사라져
        # 부모가 흔적 없이 즉사한다 (창이 그냥 꺼지는 크래시의 원인).
        if not os.environ.get("PCC_NO_ENV_RESET"):   # A/B 테스트용 우회
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith("_PYI")
                   and not k.startswith("_MEIPASS")}
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    else:
        main_py = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main.py")
        cmd = [sys.executable, "-X", "utf8", main_py,
               "--extract-claims", pdf_path, out_path]

    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    claims: list = []
    error: Optional[str] = None
    canceled = False
    done = False

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, text=True, env=env,
            encoding="utf-8", errors="replace", creationflags=creation)
    except Exception as e:
        return [], f"추출 프로세스를 시작하지 못했습니다: {e}"

    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("PROGRESS "):
                try:
                    _, cur, total = line.split()
                    cur, total = int(cur), int(total)
                except ValueError:
                    continue
                if progress_cb and not progress_cb(cur, total):
                    canceled = True
                    proc.kill()
                    break
            elif line == "DONE":
                done = True
            elif line.startswith("ERROR "):
                error = line[6:]
        rc = proc.wait(timeout=60)
    except Exception:
        proc.kill()
        rc = -1
    finally:
        if proc.poll() is None:
            proc.kill()

    if canceled:
        _silent_remove(out_path)
        return [], None
    if error is None and (not done or rc != 0):
        error = (f"PDF 처리 엔진이 비정상 종료했습니다 (코드 {rc}).\n"
                 "손상되었거나 지원되지 않는 PDF일 수 있습니다.\n"
                 "다른 PDF로 시도하거나 청구항을 직접 붙여넣어 주세요.")
    if error is None:
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            claims = [ExtractedClaim(**{
                k: v for k, v in c.items()
                if k in ExtractedClaim.__dataclass_fields__
            }) for c in raw]
        except Exception as e:
            error = f"추출 결과를 읽지 못했습니다: {e}"

    _silent_remove(out_path)
    return claims, error


def _silent_remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def extract_claims_from_text(raw_text: str) -> list[ExtractedClaim]:
    """텍스트(전문 또는 청구범위만)에서 청구항 목록을 추출."""
    text = _clean_lines(raw_text)
    section = _find_claims_section(text)
    numbered = _split_numbered(section)

    # 섹션 마커 기준으로 못 찾았으면 전체 텍스트에서 재시도
    if not numbered and section is not text:
        numbered = _split_numbered(text)

    claims = []
    for num, body in numbered:
        norm = _normalize(body)
        parent = _detect_dependency(norm, num)
        claims.append(ExtractedClaim(
            number=num,
            text=norm,
            is_independent=(parent is None),
            parent_claim=parent,
        ))
    return claims
