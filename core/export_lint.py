"""내보내기 전 점검 — 산출물에 그대로 실릴 흠을 미리 잡는다.

의뢰인/심판부에 나가는 문서라 빈 근거나 깨진 인용이 섞이면 곤란하다.
전부 읽기 전용 검사이며, 사용자는 경고를 보고도 계속 내보낼 수 있다.
"""
import os
from dataclasses import dataclass, field

from core.claim_scope import effective_elements
from core.text_doc import is_text_doc, load_text_doc

ERROR = "오류"
WARN = "경고"


@dataclass
class LintIssue:
    level: str                  # ERROR | WARN
    title: str
    detail: str = ""
    items: list = field(default_factory=list)   # 해당되는 항목 설명들


def _doc_name(path: str) -> str:
    return os.path.basename(path or "") or "(문서 없음)"


def lint_project(data) -> list:
    """ProjectData를 점검해 발견된 문제 목록을 돌려준다."""
    issues = []
    claims = list(data.claims or [])
    mappings = list(data.mappings or [])

    # --- 기본 구조 -------------------------------------------------
    if not claims:
        issues.append(LintIssue(
            ERROR, "청구항이 없습니다",
            "청구항을 입력하거나 PDF에서 가져온 뒤 내보내세요."))
        return issues

    no_elem = [c for c in claims if not c.elements]
    if no_elem:
        issues.append(LintIssue(
            ERROR, f"구성요소가 분할되지 않은 청구항 {len(no_elem)}개",
            "'자동 분할'로 구성요소를 만들어야 대비표가 생성됩니다.",
            [f"청구항 {c.claim_number}" for c in no_elem]))

    if not mappings:
        issues.append(LintIssue(
            ERROR, "매핑이 하나도 없습니다",
            "선행문헌에서 대응 부분을 드래그해 구성요소와 연결하세요."))
        return issues

    # --- 미대응 구성요소 (All Elements Rule) -----------------------
    mapped_ids = {m.element_id for m in mappings if m.element_id}
    # 상속 때문에 같은 구성요소가 여러 항에 나타나므로 한 번만 센다.
    # 대신 그 구성요소가 걸린 청구항을 함께 적어 파급 범위를 보여준다.
    gap_claims = {}
    for claim in claims:
        for scope in effective_elements(claim, claims):
            if scope.element_id not in mapped_ids:
                gap_claims.setdefault(scope.element_id, []).append(
                    claim.claim_number)
    gaps = [f"{eid}  (청구항 "
            f"{', '.join(str(n) for n in sorted(set(nums)))}항)"
            for eid, nums in gap_claims.items()]
    if gaps:
        issues.append(LintIssue(
            ERROR, f"대응 근거가 없는 구성요소 {len(gaps)}개",
            "모든 구성요소가 대응돼야 무효/침해가 성립합니다 "
            "(All Elements Rule).", gaps))

    # --- 매핑 품질 -------------------------------------------------
    doe_no_note = [m for m in mappings
                   if m.interpretation == "균등론" and not (m.note or "").strip()]
    if doe_no_note:
        issues.append(LintIssue(
            WARN, f"균등론인데 논거가 비어 있는 매핑 {len(doe_no_note)}건",
            "균등 주장은 근거를 적어야 설득력이 있습니다.",
            [f"{m.element_id} · {_doc_name(m.doc_path)} p.{m.page + 1}"
             for m in doe_no_note]))

    undecided = [m for m in mappings if m.judgment == "미판단"]
    if undecided:
        issues.append(LintIssue(
            WARN, f"미판단 상태로 남은 매핑 {len(undecided)}건",
            "일치/부분일치/불일치 중 하나로 판단을 확정하세요.",
            [f"{m.element_id} · {_doc_name(m.doc_path)} p.{m.page + 1}"
             for m in undecided]))

    empty_text = [m for m in mappings
                  if not (m.extracted_text or "").strip()]
    if empty_text:
        issues.append(LintIssue(
            WARN, f"인용 텍스트가 비어 있는 매핑 {len(empty_text)}건",
            "도면만 인용한 경우가 아니라면 근거 문장을 넣어 주세요.",
            [f"{m.element_id} · {_doc_name(m.doc_path)} p.{m.page + 1}"
             for m in empty_text]))

    # --- 선행문헌 적격성 (기준일 이후 공개 문헌 인용 여부) ----------
    from core.prior_art import (STATUS_BAD, STATUS_UNKNOWN, eligibility,
                                find_prior_art, subject_base_date)

    base, base_kind = subject_base_date(data.case_info)
    used_paths = sorted({m.doc_path for m in mappings if m.doc_path})
    if used_paths and not base:
        issues.append(LintIssue(
            WARN, "대상 특허 기준일이 없어 선행문헌 적격성을 확인 못함",
            "서지사항 탭에서 우선일(또는 출원일)을 입력하면 각 문헌의 "
            "공개일과 자동으로 대조합니다."))
    elif base:
        bad, unknown = [], []
        for p in used_paths:
            doc = find_prior_art(data, p)
            if doc is None:
                continue          # 구버전 프로젝트 — 등록 전
            status, detail = eligibility(doc, base)
            tag = f"{doc.label or _doc_name(p)} · {detail}"
            if status == STATUS_BAD:
                bad.append(tag)
            elif status == STATUS_UNKNOWN:
                unknown.append(tag)
        if bad:
            issues.append(LintIssue(
                ERROR, f"기준일 이후에 공개된 선행문헌 인용 {len(bad)}건",
                f"대상 특허 {base_kind} {base}보다 늦게 공개된 문헌은 "
                "선행문헌 자격이 없습니다 — 이 근거로는 무효 주장을 할 수 "
                "없습니다.", bad))
        if unknown:
            issues.append(LintIssue(
                WARN, f"공개일을 확인하지 못한 선행문헌 {len(unknown)}건",
                "'선행문헌 정보' 탭에서 공개일을 입력하거나 서지를 다시 "
                "읽어 주세요.", unknown))

    # --- 근거 문서 상태 --------------------------------------------
    missing = sorted({m.doc_path for m in mappings
                      if m.doc_path and not os.path.exists(m.doc_path)})
    if missing:
        issues.append(LintIssue(
            ERROR, f"파일을 찾을 수 없는 선행문헌 {len(missing)}건",
            "도면 캡처가 빠진 채로 내보내집니다. 붙여넣은 텍스트 문서는 "
            "임시 폴더에 저장되어 PC를 재시작하면 사라질 수 있습니다.",
            [_doc_name(p) for p in missing]))

    # 텍스트 문서는 rect가 문자 오프셋 — 본문이 바뀌면 범위를 벗어난다
    stale = []
    lengths = {}
    for m in mappings:
        if not (m.doc_path and is_text_doc(m.doc_path)
                and os.path.exists(m.doc_path)):
            continue
        if m.doc_path not in lengths:
            lengths[m.doc_path] = len(load_text_doc(m.doc_path))
        end = int(m.rect[1]) if len(m.rect or []) > 1 else 0
        if end > lengths[m.doc_path]:
            stale.append(f"{m.element_id} · {_doc_name(m.doc_path)}")
    if stale:
        issues.append(LintIssue(
            WARN, f"본문 범위를 벗어난 텍스트 인용 {len(stale)}건",
            "문서 내용이 바뀌어 인용 위치가 어긋났을 수 있습니다.",
            stale))

    return issues


def summarize(issues: list) -> tuple:
    """(오류 수, 경고 수)"""
    return (sum(1 for i in issues if i.level == ERROR),
            sum(1 for i in issues if i.level == WARN))
