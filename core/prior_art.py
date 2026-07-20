"""선행문헌 관리 — 라벨(D1, D2 …)과 적격성 판단.

적격성: 선행문헌은 대상 특허의 기준일(우선일, 없으면 출원일)보다
**앞서 공개**된 것이어야 한다. 기준일 이후에 공개된 문헌을 인용하면
그 무효 논리 전체가 무너지므로, 문헌을 열 때 자동으로 검사한다.

공개일과 등록일 중 빠른 날짜를 그 문헌의 공지일로 본다
(등록공고도 공개의 일종이다).
"""
import os

STATUS_OK = "적격"
STATUS_BAD = "부적격"
STATUS_UNKNOWN = "확인 필요"

# 상태별 (글자색, 배경색) — UI 공용
STATUS_STYLE = {
    STATUS_OK: ("#1B683E", "#D7F4E0"),
    STATUS_BAD: ("#9D3533", "#F8E3E1"),
    STATUS_UNKNOWN: ("#8A6000", "#FBEEC9"),
}


def norm_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(path)) if path else ""


def subject_base_date(case_info) -> tuple:
    """대상 특허의 기준일. 반환: (YYYY-MM-DD, '우선일'|'출원일'|'')."""
    pri = (getattr(case_info, "priority_date", "") or "").strip()
    if pri:
        return pri, "우선일"
    app = (getattr(case_info, "application_date", "") or "").strip()
    if app:
        return app, "출원일"
    return "", ""


def public_date(doc) -> str:
    """문헌이 공중에 공개된 가장 이른 날짜 (공개일/등록일 중 빠른 것)."""
    dates = [d.strip() for d in (doc.pub_date, doc.reg_date)
             if (d or "").strip()]
    return min(dates) if dates else ""


def eligibility(doc, base_date: str) -> tuple:
    """선행문헌 적격성. 반환: (상태, 설명 한 줄).

    같은 날 공개는 시각을 다퉈야 하므로 안전하게 부적격으로 분류한다.
    """
    pub = public_date(doc)
    if not base_date:
        return (STATUS_UNKNOWN,
                "대상 특허의 우선일(기준일)이 입력되지 않았습니다")
    if not pub:
        return (STATUS_UNKNOWN,
                "이 문헌의 공개일을 확인할 수 없습니다 — 직접 입력해 주세요")
    if pub < base_date:
        return STATUS_OK, f"공개 {pub} · 기준일 {base_date}보다 앞섬"
    return (STATUS_BAD,
            f"공개 {pub} · 기준일 {base_date} 이후(또는 당일) — "
            "선행문헌 자격이 없습니다")


def find_prior_art(data, path: str):
    target = norm_path(path)
    for doc in getattr(data, "prior_arts", None) or []:
        if norm_path(doc.path) == target:
            return doc
    return None


def next_label(data) -> str:
    used = {d.label for d in getattr(data, "prior_arts", None) or []}
    n = 1
    while f"D{n}" in used:
        n += 1
    return f"D{n}"


def ensure_prior_art(data, path: str) -> tuple:
    """문헌을 등록부에 올린다. 반환: (PriorArtDoc, 새로 등록됐는지)."""
    doc = find_prior_art(data, path)
    if doc is not None:
        return doc, False
    from core.project import PriorArtDoc
    doc = PriorArtDoc(path=norm_path(path), label=next_label(data))
    data.prior_arts.append(doc)
    return doc, True


def label_for(data, path: str) -> str:
    """경로에 붙은 라벨 (D1 …). 등록 전이면 빈 문자열."""
    doc = find_prior_art(data, path)
    return (doc.label or "").strip() if doc else ""


def labels_map(data) -> dict:
    """{정규화 경로: 라벨} — 표 열머리·내보내기 공용."""
    return {norm_path(d.path): (d.label or "").strip()
            for d in getattr(data, "prior_arts", None) or []
            if (d.label or "").strip()}
