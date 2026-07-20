"""종속항의 실제 권리범위 = 인용하는 항의 구성요소 + 자기 추가 한정.

종속항은 인용항의 모든 구성요소를 그대로 포함하므로, 클레임 차트에서도
인용항 구성요소가 함께 대비되어야 한다(All Elements Rule).

매핑을 복제하지 않는다 — 구성요소를 '상속'해서 보여줄 뿐이므로
독립항 매핑을 고치면 종속항 쪽에도 그대로 반영된다.
"""
from dataclasses import dataclass

from core.project import Claim, ClaimElement


@dataclass
class ScopeElement:
    """청구항 한 줄. 상속된 것인지, 어느 항에서 왔는지 함께 들고 다닌다."""
    element: ClaimElement
    source_claim: int          # 이 구성요소가 원래 속한 청구항 번호
    inherited: bool = False    # True면 인용항에서 상속받은 것

    @property
    def element_id(self) -> str:
        return self.element.element_id


def parent_chain(claim: Claim, claims: list) -> list:
    """인용 관계를 거슬러 올라간 상위 청구항 목록 (가장 먼 조상부터).

    잘못된 데이터로 순환 인용이 생겨도 멈춘다.
    """
    by_num = {c.claim_number: c for c in (claims or [])}
    chain, seen = [], {claim.claim_number}
    cur = claim
    while True:
        parent_num = getattr(cur, "parent_claim", None)
        if parent_num is None or parent_num in seen:
            break
        parent = by_num.get(parent_num)
        if parent is None:
            break
        seen.add(parent_num)
        chain.append(parent)
        cur = parent
    chain.reverse()          # 최상위 독립항이 앞으로
    return chain


def effective_elements(claim: Claim, claims: list) -> list:
    """이 청구항을 대비할 때 실제로 필요한 구성요소 전체.

    독립항이면 자기 구성요소만, 종속항이면 [인용항들의 구성요소…] + 자기 것.
    """
    out, seen = [], set()
    for ancestor in parent_chain(claim, claims):
        for elem in ancestor.elements:
            if elem.element_id in seen:
                continue
            seen.add(elem.element_id)
            out.append(ScopeElement(elem, ancestor.claim_number,
                                    inherited=True))
    for elem in claim.elements:
        if elem.element_id in seen:
            continue
        seen.add(elem.element_id)
        out.append(ScopeElement(elem, claim.claim_number, inherited=False))
    return out


def scope_elements(claim: Claim, claims: list, inherit: bool = True) -> list:
    """내보내기·집계에서 쓸 구성요소 목록.

    inherit=False면 예전처럼 자기 구성요소만 돌려준다.
    """
    if inherit:
        return effective_elements(claim, claims)
    return [ScopeElement(e, claim.claim_number) for e in claim.elements]


def scope_mappings(claim: Claim, claims: list, mappings: list,
                   inherit: bool = True) -> list:
    """이 청구항을 대비할 때 실을 매핑.

    상속 구성요소의 매핑은 원래 청구항 번호로 저장돼 있으므로
    항 번호가 아니라 구성요소 ID로 고른다.
    """
    ids = {s.element_id for s in scope_elements(claim, claims, inherit)}
    return [m for m in (mappings or []) if m.element_id in ids]


def effective_completion(claim: Claim, claims: list, mappings: list) -> float:
    """상속 구성요소까지 포함한 대응 완료 비율."""
    scope = effective_elements(claim, claims)
    if not scope:
        return 0.0
    mapped = {m.element_id for m in (mappings or []) if m.element_id}
    done = sum(1 for s in scope if s.element_id in mapped)
    return done / len(scope)
