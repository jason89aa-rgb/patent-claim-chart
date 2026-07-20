"""특허 PDF 1페이지(서지 페이지)에서 서지사항을 추출한다.

US 등록특허는 INID 코드 (21) 출원번호 / (22) 출원일 / (30) 우선권 /
(45) 등록일 / (54) 명칭 / (71)(73) 출원인 이 붙어 있어 기계적으로 읽을 수
있다. KR 공보는 【출원번호】 같은 항목명 또는 같은 INID 코드를 쓴다.

네트워크를 쓰지 않는다 — 이미 열어둔 PDF에서만 읽는다.
"""
import re

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False


# ------------------------------------------------------------ 날짜 정규화

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "Feb. 12 , 2020" / "Jun . 21 , 2022" / "May 8 , 2017"
_DATE_EN = re.compile(
    r"\b([A-Z][a-z]{2,4})\s*\.?\s*(\d{1,2})\s*,\s*(\d{4})\b")
# "2019년 07월 17일" / "2019.07.17" / "2019-07-17" (KR/CN/ISO: 연-월-일)
_DATE_YMD = re.compile(
    r"(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?")
# "27.02.2014" (DE: 일.월.연)
_DATE_DMY = re.compile(r"\b(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\b")


def _iso(y, m, d) -> str:
    try:
        y, m, d = int(y), int(m), int(d)
    except (TypeError, ValueError):
        return ""
    if not (1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return ""
    return f"{y:04d}-{m:02d}-{d:02d}"


def parse_date(text: str) -> str:
    """텍스트에서 첫 번째 날짜를 YYYY-MM-DD로 반환.

    KR/CN '2019년07월17일', '2014.06.02' (연-월-일)
    DE '27.02.2014' (일.월.연)
    US 'Feb. 12 , 2020'
    """
    if not text:
        return ""
    m = _DATE_YMD.search(text)
    if m:
        iso = _iso(*m.groups())
        if iso:
            return iso
    m = _DATE_DMY.search(text)
    if m:
        d, mo, y = m.groups()
        iso = _iso(y, mo, d)
        if iso:
            return iso
    m = _DATE_EN.search(text)
    if m:
        mon = _MONTHS.get(m.group(1).lower().rstrip("."))
        if mon:
            return _iso(m.group(3), mon, m.group(2))
    return ""


# ------------------------------------------------------------ 페이지 재구성

def _front_page_text(page) -> str:
    """1페이지를 좌→우 컬럼 순서로 재구성.

    청구항용 재구성(_page_text_two_column)은 여백의 행번호를 지우느라
    INID 코드의 숫자까지 날려버리므로 여기서는 쓰지 않는다.
    """
    words = page.get_text("words")
    if not words:
        return page.get_text()

    mid = (page.rect.x0 + page.rect.x1) / 2.0
    cols = ([], [])
    for w in words:
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
        cx = (x0 + x1) / 2.0
        cols[0 if cx < mid else 1].append((y0, x0, text))

    out = []
    for col in cols:
        lines = {}
        for y0, x0, text in col:
            lines.setdefault(round(y0 / 3.0), []).append((x0, text))
        for key in sorted(lines):
            items = sorted(lines[key])
            out.append(" ".join(t for _, t in items))
    return "\n".join(out)


def _field(text: str, pattern: str, group: int = 1) -> str:
    m = re.search(pattern, text, re.IGNORECASE)
    return (m.group(group) or "").strip() if m else ""


# 다음 INID 항목의 시작 — 값 블록의 끝을 판단한다
_NEXT_INID = re.compile(r"^\s*\(\s*\d{2}\s*\)")


def _block_lines(text: str, label: str, max_lines: int = 4) -> list:
    """'(54) Bezeichnung:' 처럼 값이 다음 줄로 이어지는 항목을 줄 단위로 읽는다.

    라벨 뒤부터 다음 INID 코드가 나오기 전까지.
    """
    m = re.search(label, text, re.IGNORECASE)
    if not m:
        return []
    out = []
    for i, line in enumerate(text[m.end():].split("\n")):
        if i and _NEXT_INID.match(line):
            break
        line = line.strip(" :")
        if line:
            out.append(line)
        elif out:
            break
        if len(out) >= max_lines:
            break
    return out


def _block(text: str, label: str, max_lines: int = 4) -> str:
    return " ".join(_block_lines(text, label, max_lines)).strip(" :")


def _clean_num(s: str) -> str:
    """'16 / 789,102' → '16/789,102'"""
    return re.sub(r"\s+", "", s or "")


# 유니코드 범위는 반드시 \uXXXX 이스케이프로 적을 것.
# 리터럴 글자로 쓰면 '豈'가 U+8C48이라 범위가 한글(U+AC00~)까지 삼킨다.
_HANJA = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"      # 한자
_KANA = "\u3041-\u309f\u30a0-\u30ff"                      # 히라가나/가타카나
_HANGUL = "\uac00-\ud7a3"  # 한글 음절

# 문자 종류 판별용 (한글 포함)
_CJK = _HANJA + _KANA + _HANGUL
# 글자별 공백을 되돌릴 대상 — 한글은 제외한다. 한국어는 원래 단어 사이를
# 띄어 쓰므로 넣으면 '사출 성형의 냉각 시스템'이 붙어버린다.
_HAN = _HANJA + _KANA

_CJK_SPACE = re.compile(rf"(?<=[{_HAN}])[ \t]+(?=[{_HAN}])")
_NUM_DOT_SPACE = re.compile(r"(?<=\d)\.[ \t]+(?=\d)")


def despace_cjk(text: str) -> str:
    """OCR 결과의 글자별 공백을 되돌린다.

    '申 请 号' → '申请号', '2015. 06. 24' → '2015.06.24'
    """
    if not text:
        return text
    prev = None
    while prev != text:            # '一 种 多' 처럼 연속된 경우 반복 적용
        prev = text
        text = _CJK_SPACE.sub("", text)
    return _NUM_DOT_SPACE.sub(".", text)


def _tidy(s: str) -> str:
    """PDF 추출 특유의 벌어진 문장부호를 정리."""
    s = (s or "").strip()
    # OCR이 CJK 열거쉼표(、)를 '\'로 잘못 읽는 경우가 잦다
    s = re.sub(rf"(?<=[{_CJK}])\s*\\\s*(?=[{_CJK}])", "、", s)
    s = s.replace("\\", " ")
    s = re.sub(r"\s{2,}", " ", s.strip())
    s = re.sub(r"\s+([,.;:])", r"\1", s)      # "Co. , LTD ." → "Co., LTD."
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    return s.strip(" ,;:")


# 법인 접미사 — 출원인 이름이 주소로 이어지기 전에 끊는 기준
_ORG_TAIL = re.compile(
    r"^(.*?(?:CORPORATION|CORP|COMPANY|CO\s*\.?\s*,?\s*LTD|LTD|INC|LLC|"
    r"L\.L\.C|GMBH|B\.V|N\.V|S\.A|A\.?G|K\.?K|PLC|주식회사|유한회사|\(주\)|"
    r"有限公司|股份公司|公司|株式会社)"
    r"\.?)(?:\s|,|$)",
    re.IGNORECASE)

# 한국 주소 시작 (출원인 이름 뒤에 붙어 나오는 경우)
_KR_ADDR = re.compile(
    r"\s+(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|"
    r"전북|전남|경북|경남|제주)\S*\s")


def _org_name(raw: str) -> str:
    """'UNIVERSAL DISPLAY CORPORATION , Ewing , NJ ( US )' → 법인명까지만."""
    raw = _tidy(raw)
    m = _KR_ADDR.search(raw)
    if m:
        raw = raw[:m.start()].strip()
    m = _ORG_TAIL.match(raw)
    if m:
        return _tidy(m.group(1))
    # 접미사가 없으면 주소(도시, 국가코드) 앞에서 자른다
    return _tidy(re.split(r",\s*[A-Z][a-z]+\s*-?\s*(?:si|gu|shi)?\s*\(", raw)[0])


def _org_names(raw: str, extra_split: str = "") -> str:
    """공동 권리자를 모두 뽑아 ' / '로 잇는다.

    DE  'Shanghai AVIC …Co., Ltd., Shanghai, CN; Tianma …Co., Ltd., Shenzhen, CN'
    CN  '上海天马微电子有限公司 … 申请人 天马微电子股份有限公司'
    """
    if not raw:
        return ""
    parts = re.split(extra_split, raw) if extra_split else [raw]
    names, seen = [], set()
    for part in parts:
        for chunk in re.split(r"[;；]", part):
            name = _org_name(chunk)
            # 주소만 남은 조각(도시명 등)은 버린다
            if not name or not _ORG_TAIL.match(_tidy(name)):
                continue
            if name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)
    if not names:                       # 법인 접미사가 없는 개인/기관명
        first = _org_name(re.split(r"[;；]", parts[0])[0])
        return first
    return " / ".join(names)


# ------------------------------------------------------------ US 등록특허

def _parse_us(text: str) -> dict:
    out = {}

    # (10) 등록번호 — "US 11,367,770 B2"
    reg = _field(text, r"Patent\s*No\s*\.?\s*:?\s*(US\s*[\d,\s]{7,15}[AB]\d?)")
    if not reg:
        reg = _field(text, r"\bUS\s*0?(\d{7,8})\s*([AB]\d)", 0)
    if reg:
        reg = re.sub(r"\s+", " ", reg).strip()
        # "US 11,367,770 B2" 형태로 정규화
        m = re.search(r"(\d[\d,]{5,12})\s*([AB]\d?)?", reg)
        if m:
            num = m.group(1).replace(",", "")
            if len(num) >= 7:
                num = f"{int(num):,}"
            kind = f" {m.group(2)}" if m.group(2) else ""
            reg = f"US {num}{kind}"
    out["registration_number"] = reg

    # (21) 출원번호
    out["application_number"] = _clean_num(_field(
        text, r"Appl\s*\.?\s*No\s*\.?\s*:?\s*(\d{2}\s*/\s*[\d,]{3,10})"))

    # (22) 출원일
    filed = _field(text, r"Filed\s*:?\s*([A-Z][a-z]{2,4}\s*\.?\s*\d{1,2}\s*,"
                         r"\s*\d{4})")
    out["application_date"] = parse_date(filed)

    # (45) 등록일
    out["registration_date"] = parse_date(_field(
        text, r"Date\s*of\s*Patent\s*:?\s*([A-Z][a-z]{2,4}\s*\.?\s*\d{1,2}"
              r"\s*,\s*\d{4})"))

    # (54) 발명의 명칭 — 대문자 제목 줄
    title = _field(text, r"\(\s*54\s*\)\s*([^\n]+)")
    if not title:
        # 컬럼 재구성 순서에 따라 (12) 다음 줄에 오기도 한다
        title = _field(text, r"United\s+States\s+Patent[^\n]*\n[^\n]*\n"
                             r"\(\s*54\s*\)\s*([^\n]+)")
    out["title"] = _tidy(title)

    # (71)/(73) 출원인 — 법인명이 다음 줄로 이어지므로 2줄까지 붙여 읽는다
    applicant = _field(
        text, r"Applicant\s*:?\s*([^\n]+(?:\n(?!\s*\(\s*\d)[^\n]+)?)")
    if not applicant:
        applicant = _field(
            text, r"Assignee\s*:?\s*([^\n]+(?:\n(?!\s*\(\s*\d)[^\n]+)?)")
    out["applicant"] = _org_name(applicant.replace("\n", " "))

    # (30) 외국 우선권 + (60)/(63) 미국 관련출원
    priorities, dates = [], []
    m = re.search(r"Foreign\s+Application\s+Priority\s+Data(.{0,400})",
                  text, re.IGNORECASE | re.DOTALL)
    if m:
        for line in m.group(1).split("\n")[:6]:
            d = parse_date(line)
            num = _field(line, r"([\dA-Z]{2}[\d\-]{6,20})")
            cc = _field(line, r"\(\s*([A-Z]{2})\s*\)")
            if d:
                dates.append(d)
                if num:
                    priorities.append(f"{num} ({cc})" if cc else num)

    m = re.search(r"Provisional\s+application\s+No\s*\.?\s*(.{0,300})",
                  text, re.IGNORECASE | re.DOTALL)
    if m:
        # 다음 INID 항목 전까지만 본다 (CPC 분류코드 'HO1L 51/504' 오인 방지)
        chunk = re.split(r"\n\s*\(\s*\d{2}\s*\)", m.group(1))[0]
        # 가출원 번호는 60/61/62/63 시리즈 + 6자리 (분류코드와 자릿수가 다름)
        for pm in re.finditer(r"\b(6[0-3]\s*/\s*\d{3},\d{3})\b", chunk):
            priorities.append(f"US {_clean_num(pm.group(1))} (가출원)")
        for dm in _DATE_EN.finditer(chunk):
            d = parse_date(dm.group(0))
            if d:
                dates.append(d)

    out["family_patents"] = priorities
    # 우선일 = 가장 이른 우선권 주장일 (없으면 출원일)
    out["priority_date"] = min(dates) if dates else out["application_date"]
    return out


# ------------------------------------------------------------ KR 공보

_KR_LABELS = {
    "registration_number": r"등\s*록\s*번\s*호",
    "application_number": r"출\s*원\s*번\s*호",
    "application_date": r"출\s*원\s*(?:일자|일)",
    "registration_date": r"등\s*록\s*(?:일자|일)",
    "title": r"발명의\s*명칭",
    "applicant": r"출\s*원\s*인",
}


def _parse_kr(text: str) -> dict:
    out = {}
    for key, label in _KR_LABELS.items():
        val = _field(text, r"【?\s*" + label + r"\s*】?\s*:?\s*([^\n]+)")
        val = _tidy(val)
        if key.endswith("_date"):
            val = parse_date(val)
        elif key.endswith("_number"):
            val = _clean_num(val)
        out[key] = val

    # (73) 특허권자 / 출원인 — 이름이 라벨 다음 줄, 그 다음 줄은 주소
    if not out.get("applicant"):
        lines = _block_lines(text, r"\(\s*73\s*\)\s*(?:특허권자|출원인)",
                             max_lines=2)
        out["applicant"] = _org_name(lines[0]) if lines else ""

    # (30) 우선권 주장 (국내 출원은 없음 → 출원일이 우선일)
    pri = _block(text, r"\(\s*30\s*\)\s*우선권\s*주장", max_lines=3)
    out["priority_date"] = parse_date(pri) or out.get("application_date", "")
    out["family_patents"] = re.findall(r"\b(\d{2}-\d{4}-\d{7})\b", pri or "")
    return out


# ------------------------------------------------------------ DE 공보

def _parse_de(text: str) -> dict:
    out = {}

    # (10) "DE 10 2014 203 555 B4 2023.11.02"
    out["registration_number"] = _tidy(_field(
        text, r"\(\s*10\s*\)\s*(DE\s*[\d\s]{10,20}[AB]\d?)"))

    # (21) Aktenzeichen
    out["application_number"] = _tidy(_field(
        text, r"Aktenzeichen\s*:?\s*([\d\s]{10,20}(?:\.\d)?)"))

    # (22) Anmeldetag
    out["application_date"] = parse_date(_field(
        text, r"Anmeldetag\s*:?\s*([\d.\s]{8,12})"))

    # (45) Veröffentlichungstag der Patenterteilung (라벨이 줄바꿈된다)
    out["registration_date"] = parse_date(_block(
        text, r"Patenterteilung\s*:", max_lines=1))
    if not out["registration_date"]:
        out["registration_date"] = parse_date(_field(
            text, r"\(\s*45\s*\)[^\n]*\n?[^\n]*?([\d]{2}\.[\d]{2}\.[\d]{4})"))

    # (54) Bezeichnung — 제목이 여러 줄로 이어진다
    title = _block(text, r"Bezeichnung\s*:", max_lines=3)
    out["title"] = _tidy(re.sub(r"\xad", "", title))

    # (73) Patentinhaber — 공동권리자는 ';'로 구분되고 여러 줄에 걸친다
    out["applicant"] = _org_names(
        _block(text, r"Patentinhaber\s*:", max_lines=4))

    # (30) Unionspriorität: "201310375928.3 / 26.08.2013 / CN"
    pri = _block(text, r"Unionspriorit[äa]t\s*:", max_lines=4)
    out["priority_date"] = parse_date(pri) or out["application_date"]
    fam = []
    if pri:
        num = _field(pri, r"([\d]{6,15}(?:\.\d)?)")
        cc = _field(pri, r"\b([A-Z]{2})\b\s*$") or _field(pri, r"\b([A-Z]{2})\b")
        if num:
            fam.append(f"{num} ({cc})" if cc else num)
    out["family_patents"] = fam
    return out


# ------------------------------------------------------------ CN 공보

_CN_LABELS = {
    "application_number": r"\(\s*21\s*\)\s*申请号",
    "application_date": r"\(\s*22\s*\)\s*申请日",
    "title": r"\(\s*54\s*\)\s*发明名称",
    "applicant": r"\(\s*7[13]\s*\)\s*(?:专利权人|申请人)",
}


def _parse_cn(text: str) -> dict:
    out = {}
    for key, label in _CN_LABELS.items():
        lines = _block_lines(text, label, max_lines=6)
        if key == "applicant":
            # '地址 …'는 주소, 그 뒤 '申请人 …'은 공동 출원인
            joined = " ".join(lines)
            names = [re.split(r"地\s*址", seg)[0]
                     for seg in re.split(r"申\s*请\s*人|专\s*利\s*权\s*人",
                                         joined)]
            val = _org_names(" ; ".join(n for n in names if n.strip()))
        else:
            val = _tidy(" ".join(lines))
            if key.endswith("_date"):
                val = parse_date(val)
            elif key.endswith("_number"):
                val = _clean_num(val)
        out[key] = val

    # (11) 授权公告号 / (10) 申请公布号 — "CN 104732907 A"
    out["registration_number"] = _tidy(_field(
        text, r"(?:授权公告号|申请公布号)\s*[:：]?\s*(CN\s*[\d]{6,12}\s*[A-Z]\d?)"))
    out["registration_date"] = parse_date(_block(
        text, r"(?:授权公告日|申请公布日)", max_lines=1))

    pri = _block(text, r"\(\s*30\s*\)\s*优先权数据", max_lines=3)
    out["priority_date"] = parse_date(pri) or out.get("application_date", "")
    out["family_patents"] = ([_tidy(pri)] if pri and out["priority_date"]
                             else [])
    return out


# ------------------------------------------------------------ 진입점

def ocr_front_page(pdf_path: str, page_index: int = 0) -> str:
    """스캔본 서지 페이지를 OCR로 읽는다 (문자 종류를 먼저 판별).

    크래시 위험이 있는 경로이므로 GUI에서는 별도 프로세스로 호출할 것.
    """
    try:
        import pytesseract
        from core.ocr_engine import (_render_page_pixmap, _pixmap_to_pil,
                                     _resolve_lang)
    except Exception:
        return ""

    try:
        doc = fitz.open(pdf_path)
        if page_index >= doc.page_count:
            doc.close()
            return ""
        pix = _render_page_pixmap(doc[page_index], dpi=300)
        img = _pixmap_to_pil(pix)
        doc.close()
    except Exception:
        return ""

    # osd로 문자 종류를 먼저 보고 언어팩을 고른다 (다국어 동시 OCR은 느리고
    # 정확도도 떨어진다)
    lang = "eng"
    try:
        osd = pytesseract.image_to_osd(img)
        script = re.search(r"Script:\s*(\w+)", osd)
        script = script.group(1).lower() if script else ""
        lang = {"han": "chi_sim+eng", "hangul": "kor+eng",
                "korean": "kor+eng", "japanese": "jpn+eng",
                "hiragana": "jpn+eng", "katakana": "jpn+eng"}.get(script,
                                                                  "eng")
    except Exception:
        pass

    try:
        return pytesseract.image_to_string(img, lang=_resolve_lang(lang))
    except Exception:
        return ""


def extract_biblio(pdf_path: str, max_pages: int = 2,
                   use_ocr: bool = False) -> dict:
    """PDF 앞쪽 페이지에서 서지사항을 뽑는다.

    반환: {title, applicant, application_number, registration_number,
           application_date, registration_date, priority_date,
           family_patents, _source} — 못 찾은 항목은 빈 문자열.
    """
    empty = {
        "title": "", "applicant": "", "application_number": "",
        "registration_number": "", "application_date": "",
        "registration_date": "", "priority_date": "",
        "family_patents": [], "_source": "",
    }
    if not FITZ_AVAILABLE or not pdf_path:
        return empty

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return empty

    try:
        results = []
        scanned = True
        for pno in range(min(max_pages, doc.page_count)):
            page = doc[pno]
            # 원문 그대로 + 2단 재구성본 둘 다 시도한다.
            # KR/DE/CN 공보는 원문이 이미 읽기 좋고, US는 2단 재구성이
            # 있어야 라벨과 값이 같은 줄에 온다.
            for text in _page_texts(page):
                if not text.strip():
                    continue
                scanned = False
                got = _parse_by_kind(text)
                if _filled(got) > 1:
                    results.append(got)
        best = _merge(results, empty)

        # 텍스트 레이어가 없는 스캔본 → OCR (호출자가 허용한 경우에만)
        if use_ocr and scanned and _filled(best) == 0:
            text = despace_cjk(ocr_front_page(pdf_path, 0))
            if text.strip():
                got = _parse_by_kind(text)
                got["_ocr"] = True
                if _filled(got) > 0:
                    best = {**empty, **got}
        return best
    finally:
        doc.close()


def is_scanned(pdf_path: str, max_pages: int = 2) -> bool:
    """앞쪽 페이지에 텍스트 레이어가 없으면 True (OCR이 필요한 문서)."""
    if not FITZ_AVAILABLE or not pdf_path:
        return False
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return False
    try:
        for pno in range(min(max_pages, doc.page_count)):
            if len(doc[pno].get_text().strip()) > 50:
                return False
        return True
    finally:
        doc.close()


def _page_texts(page) -> list:
    raw = despace_cjk(page.get_text())
    col = despace_cjk(_front_page_text(page))
    return [raw, col] if col.strip() and col != raw else [raw]


def detect_kind(text: str) -> str:
    """공보 종류 판별."""
    if re.search(r"대한민국특허청|등록특허공보|공개특허공보|발명의\s*명칭", text):
        return "KR"
    if re.search(r"Patentschrift|Offenlegungsschrift|Aktenzeichen|"
                 r"Anmeldetag|Patentinhaber", text):
        return "DE"
    if re.search(r"发明专利|申请公布|授权公告|发明名称|申请人", text):
        return "CN"
    return "US"


_PARSERS = {"KR": _parse_kr, "DE": _parse_de, "CN": _parse_cn, "US": _parse_us}


def _parse_by_kind(text: str) -> dict:
    kind = detect_kind(text)
    got = _PARSERS[kind](text)
    got["_source"] = kind
    return got


def _merge(results: list, empty: dict) -> dict:
    """여러 파싱 결과를 합친다 — 가장 많이 채운 것을 기준으로 빈칸만 보충."""
    if not results:
        return dict(empty)
    results.sort(key=_filled, reverse=True)
    best = {**empty, **results[0]}
    for other in results[1:]:
        if other.get("_source") != best.get("_source"):
            continue
        for key, val in other.items():
            if key == "_source" or not val:
                continue
            cur = best.get(key)
            if not cur:
                best[key] = val
            elif (key == "title" and isinstance(val, str)
                    and isinstance(cur, str) and len(val) > len(cur)
                    and cur.rstrip(". ") in val):
                # 2단 재구성에서 잘린 제목을 원문 쪽 전체 제목으로 교체
                best[key] = val
    return best


def _filled(d: dict) -> int:
    """채워진 항목 수 (_source는 세지 않는다)."""
    count = 0
    for key, val in d.items():
        if key == "_source":
            continue
        if isinstance(val, str):
            val = val.strip()
        if val:
            count += 1
    return count


FIELD_LABELS = [
    ("title", "제목"),
    ("applicant", "출원인"),
    ("application_number", "출원번호"),
    ("registration_number", "등록번호"),
    ("priority_date", "우선일"),
    ("application_date", "출원일"),
    ("registration_date", "등록일"),
    ("family_patents", "패밀리 특허"),
]
