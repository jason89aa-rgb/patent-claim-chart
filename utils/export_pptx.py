"""PPTX Claim Chart Export — 배심원 친화적 모던 디자인 (Type A/B/C).

디자인 원칙:
- 흰 배경 + 명확한 잉크색 텍스트, 민트 포인트
- 구성요소는 둥근 색상 칩, 판단은 색상 필(pill) 배지로 한눈에
- 청구항 요소와 선행문헌 대응 단어는 같은 색으로 매칭
"""
import os

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

from core.project import ProjectData, CaseInfo, Claim, MappingEntry
from core.region_capture import (capture_for_mappings,
                                 group_mappings_by_region,
                                 build_region_index)
from utils.color_utils import get_text_color
from utils.term_format import split_by_terms, evidence_chunks
from utils.errlog import log_exception

SLIDE_W = Inches(13.33)
SLIDE_H = Inches(7.5)
FONT = "맑은 고딕"

# ------------------------------------------------------------ 디자인 토큰
INK    = RGBColor(0x1F, 0x24, 0x30)   # 본문
SUB    = RGBColor(0x6B, 0x76, 0x84)   # 보조
ACCENT = RGBColor(0x2A, 0xC1, 0xBC)   # 민트 포인트
LIGHT  = RGBColor(0xF2, 0xF5, 0xF7)   # 옅은 카드 배경
BORDER = RGBColor(0xE1, 0xE6, 0xEA)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)

# 판단: (글자색, 배경색) — 배심원이 즉시 인지할 수 있는 신호등 팔레트
JUDGMENT_STYLE = {
    "일치":    (RGBColor(0x02, 0x7A, 0x48), RGBColor(0xD1, 0xFA, 0xDF)),
    "부분일치": (RGBColor(0xB5, 0x47, 0x08), RGBColor(0xFE, 0xF0, 0xC7)),
    "불일치":  (RGBColor(0xB4, 0x23, 0x18), RGBColor(0xFE, 0xE4, 0xE2)),
    "미판단":  (RGBColor(0x47, 0x54, 0x67), RGBColor(0xEA, 0xEC, 0xF0)),
}

INTERPRETATION_LABELS = {
    "문언침해": "Lit.",
    "균등론":   "DOE",
    "넓게해석": "Broad",
    "좁게해석": "Narrow",
}


# ------------------------------------------------------------ 기본 도형
def _no_shadow(shape):
    try:
        shape.shadow.inherit = False
    except Exception:
        pass


def _hex_to_rgbcolor(hex_str: str) -> RGBColor:
    h = hex_str.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _round_rect(slide, left, top, width, height,
                fill=None, line=None, radius=0.14):
    sp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    try:
        sp.adjustments[0] = radius
    except Exception:
        pass
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(1)
    _no_shadow(sp)
    return sp


def _rect(slide, left, top, width, height, fill):
    sp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    sp.line.fill.background()
    _no_shadow(sp)
    return sp


def _shape_text(sp, text, size=10, bold=False, color=INK,
                align=PP_ALIGN.CENTER):
    tf = sp.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Pt(4)
    tf.margin_top = tf.margin_bottom = Pt(1)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return sp


def _chip(slide, left, top, width, height, text, rgb, font_size=10):
    """구성요소 라벨용 둥근 색상 칩."""
    sp = _round_rect(slide, left, top, width, height,
                     fill=RGBColor(*rgb), radius=0.32)
    _shape_text(sp, text, size=font_size, bold=True,
                color=_hex_to_rgbcolor(get_text_color(tuple(rgb))))
    return sp


def _pill(slide, left, top, width, height, text, fg, bg, size=9):
    sp = _round_rect(slide, left, top, width, height, fill=bg, radius=0.5)
    _shape_text(sp, text, size=size, bold=True, color=fg)
    return sp


def _judgment_pill(slide, left, top, width, judgment, interp=""):
    fg, bg = JUDGMENT_STYLE.get(judgment, JUDGMENT_STYLE["미판단"])
    label = judgment
    interp_label = INTERPRETATION_LABELS.get(interp, "")
    if interp_label:
        label += f" · {interp_label}"
    return _pill(slide, left, top, width, Inches(0.3), label, fg, bg)


def _add_text_box(slide, left, top, width, height, text,
                  font_size=12, bold=False, color=None,
                  align=PP_ALIGN.LEFT, wrap=True):
    tx = slide.shapes.add_textbox(left, top, width, height)
    tf = tx.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color or INK
    return tx


def _add_term_text_box(slide, left, top, width, height, text,
                       terms, font_size=9, base_color=None, chunks=None):
    """매칭 요소를 색상으로 강조한 텍스트 박스."""
    tx = slide.shapes.add_textbox(left, top, width, height)
    tf = tx.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    base = base_color or INK
    for chunk, color in (chunks if chunks is not None
                         else split_by_terms(text, terms)):
        if not chunk:
            continue
        run = p.add_run()
        run.text = chunk
        run.font.name = FONT
        run.font.size = Pt(font_size)
        if color:
            run.font.bold = True
            run.font.color.rgb = RGBColor(*color)
        else:
            run.font.color.rgb = base
    return tx


def _add_region_image(slide, mappings, colors, left, top,
                      max_w, max_h, terms=None) -> bool:
    """매핑된 PDF 영역을 카드 프레임 안에 캡처 삽입."""
    img_path = capture_for_mappings(mappings, colors, terms=terms)
    if not img_path or not os.path.exists(img_path):
        return False
    try:
        from PIL import Image
        with Image.open(img_path) as im:
            iw, ih = im.size
        inset = Inches(0.06)
        avail_w = max_w - 2 * inset
        avail_h = max_h - 2 * inset
        scale = min(avail_w / iw, avail_h / ih)
        w = int(iw * scale)
        h = int(ih * scale)
        # 카드 프레임
        _round_rect(slide, left, top, max_w, max_h,
                    fill=WHITE, line=BORDER, radius=0.06)
        slide.shapes.add_picture(
            img_path,
            left + (max_w - w) // 2,
            top + (max_h - h) // 2,
            width=w, height=h)
        return True
    except Exception as e:
        print(f"[export_pptx] image insert error: {e}")
        return False


def _color_maps(data: ProjectData) -> dict:
    colors = {}
    for claim in data.claims:
        for elem in claim.elements:
            colors[elem.element_id] = tuple(elem.color_rgb)
    for t in data.terms:
        colors[t.term_id] = tuple(t.color_rgb)
    return colors


def _slide_header(slide, title, sub=""):
    """모든 본문 슬라이드 공통 헤더: 제목 + 민트 포인트 바 + 보조 텍스트."""
    _add_text_box(slide, Inches(0.3), Inches(0.22), Inches(9.0), Inches(0.5),
                  title, font_size=18, bold=True, color=INK)
    _rect(slide, Inches(0.32), Inches(0.78), Inches(0.9), Inches(0.06),
          ACCENT)
    if sub:
        _add_text_box(slide, Inches(9.0), Inches(0.3), Inches(4.0),
                      Inches(0.4), sub, font_size=11, color=SUB,
                      align=PP_ALIGN.RIGHT)


# ------------------------------------------------------------ 표지
def _cover_slide(prs: Presentation, case_info: CaseInfo, title: str):
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    # 상단 민트 스트립
    _rect(slide, 0, 0, SLIDE_W, Inches(0.16), ACCENT)

    _add_text_box(slide, Inches(0.95), Inches(1.0), Inches(11.4),
                  Inches(0.45), "CLAIM CHART", font_size=14, bold=True,
                  color=ACCENT)
    _add_text_box(slide, Inches(0.93), Inches(1.45), Inches(11.5),
                  Inches(1.0), title or "특허 Claim Chart",
                  font_size=30, bold=True, color=INK)

    # 사건 정보 카드
    card = _round_rect(slide, Inches(0.9), Inches(2.85), Inches(7.7),
                       Inches(3.7), fill=LIGHT, radius=0.06)
    rows = [
        ("출원번호", case_info.application_number),
        ("등록번호", case_info.registration_number),
        ("우선일", case_info.priority_date),
        ("출원일", case_info.application_date),
        ("등록일", case_info.registration_date),
        ("출원인", case_info.applicant),
        ("패밀리", ", ".join(case_info.family_patents)),
    ]
    y = Inches(3.1)
    for label, value in rows:
        _add_text_box(slide, Inches(1.2), y, Inches(1.5), Inches(0.35),
                      label, font_size=10, bold=True, color=SUB)
        _add_text_box(slide, Inches(2.8), y, Inches(5.5), Inches(0.35),
                      value or "-", font_size=11, color=INK)
        y += Inches(0.44)

    # 판단 범례 카드
    _round_rect(slide, Inches(8.95), Inches(2.85), Inches(3.5),
                Inches(3.7), fill=LIGHT, radius=0.06)
    _add_text_box(slide, Inches(9.25), Inches(3.05), Inches(2.9),
                  Inches(0.35), "판단 범례", font_size=11, bold=True,
                  color=SUB)
    y = Inches(3.5)
    for judgment in ("일치", "부분일치", "불일치", "미판단"):
        fg, bg = JUDGMENT_STYLE[judgment]
        _pill(slide, Inches(9.25), y, Inches(1.45), Inches(0.32),
              judgment, fg, bg)
        y += Inches(0.44)
    _add_text_box(slide, Inches(9.25), y + Inches(0.05), Inches(3.0),
                  Inches(1.0),
                  "Lit.=문언침해  DOE=균등론\nBroad=넓게해석  Narrow=좁게해석",
                  font_size=8.5, color=SUB)


# ------------------------------------------------------------ 요소 범례
def _term_legend_slide(prs: Presentation, terms: list):
    if not terms:
        return
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(slide, "매칭 요소 색상 안내")
    _add_text_box(slide, Inches(0.32), Inches(1.0), Inches(12.5),
                  Inches(0.4),
                  "같은 색 = 청구항의 요소와 선행문헌의 대응부분이 서로 대응함을 의미합니다.",
                  font_size=11, color=SUB)

    col_w = Inches(6.2)
    x0, y0 = Inches(0.4), Inches(1.7)
    per_col = 11
    for i, t in enumerate(terms):
        col = i // per_col
        row = i % per_col
        x = x0 + col * (col_w + Inches(0.3))
        y = y0 + row * Inches(0.48)
        if x + col_w > SLIDE_W:
            break
        rgb = tuple(t.color_rgb)
        _chip(slide, x, y, Inches(0.75), Inches(0.32), t.term_id, rgb,
              font_size=10)
        _add_text_box(slide, x + Inches(0.9), y - Inches(0.01),
                      col_w - Inches(1.0), Inches(0.38),
                      t.text, font_size=12, color=INK)


# ------------------------------------------------------------ Type A
_A_X = [Inches(0.3), Inches(1.37), Inches(5.49), Inches(8.81),
        Inches(11.88)]
_A_W = [Inches(0.95), Inches(4.00), Inches(3.20), Inches(2.95),
        Inches(1.25)]
_A_HEADERS = ["구성요소", "청구항 기재", "선행문헌 대응부분", "도면 · 근거", "판단"]
_A_TOP = Inches(0.98)
_A_HEADER_H = Inches(0.36)
_A_MAX_Y = Inches(7.1)


def _type_a_header(prs: Presentation, claim: Claim, doc_label: str,
                   page_no: int):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    suffix = f"  ({page_no})" if page_no > 1 else ""
    _slide_header(slide, f"청구항 {claim.claim_number} Claim Chart{suffix}",
                  doc_label)
    # 헤더 밴드
    band_w = _A_X[4] + _A_W[4] - _A_X[0]
    _round_rect(slide, _A_X[0], _A_TOP, band_w, _A_HEADER_H,
                fill=LIGHT, radius=0.3)
    for i, h in enumerate(_A_HEADERS):
        tx = _add_text_box(slide, _A_X[i], _A_TOP + Inches(0.045),
                           _A_W[i], Inches(0.3), h,
                           font_size=10, bold=True, color=SUB,
                           align=PP_ALIGN.CENTER)
    return slide


def _type_a_slide(prs: Presentation, claim: Claim,
                  mappings: list, doc_label: str,
                  terms: list, colors: dict):
    page_no = 1
    slide = _type_a_header(prs, claim, doc_label, page_no)

    by_elem: dict = {}
    for m in mappings:
        by_elem.setdefault(m.element_id, []).append(m)

    # 같은 도면(그룹)이 여러 구성요소에 걸치면 이미지는 첫 행에만
    region_index = build_region_index(mappings)
    rendered_groups: set = set()

    y = _A_TOP + _A_HEADER_H + Inches(0.1)

    for elem in claim.elements:
        elem_maps = by_elem.get(elem.element_id, [])
        region_index = build_region_index(mappings)
        regions = list(group_mappings_by_region(elem_maps).values()) or [[]]

        for idx, region_maps in enumerate(regions):
            # 전체 그룹(다른 구성요소 포함) 확인
            if region_maps:
                gkey, gmembers = region_index.get(
                    region_maps[0].mapping_id, (None, region_maps))
                first_show = gkey not in rendered_groups
                if gkey is not None:
                    rendered_groups.add(gkey)
            else:
                gkey, gmembers, first_show = None, [], False

            has_image = bool(region_maps) and first_show
            row_h = Inches(1.6) if has_image else Inches(0.52)

            if y + row_h > _A_MAX_Y:
                page_no += 1
                slide = _type_a_header(prs, claim, doc_label, page_no)
                y = _A_TOP + _A_HEADER_H + Inches(0.1)

            # 구성요소 칩
            _chip(slide, _A_X[0], y + Inches(0.02), _A_W[0], Inches(0.32),
                  elem.element_id if idx == 0 else "〃",
                  tuple(elem.color_rgb) if elem.color_rgb else (150, 150, 150))

            # 청구항 기재 (요소 색상)
            if idx == 0:
                _add_term_text_box(slide, _A_X[1], y, _A_W[1],
                                   max(row_h, Inches(1.0)),
                                   elem.text, terms, font_size=9)

            # 선행문헌 대응부분
            if region_maps:
                m0 = region_maps[0]
                judgment = m0.judgment
                interp = m0.interpretation
                ev_chunks = evidence_chunks(m0, terms)
                if not (m0.extracted_text or "").strip():
                    ev_chunks = [("(도면 표시 참조)", None)]
                others = sorted({m.element_id for m in gmembers
                                 if m.element_id != elem.element_id})
                if others:
                    ev_chunks = ev_chunks + [
                        (f"\n[공통 대응: {', '.join(others)}]", None)]
            else:
                ev_chunks = [("(대응 없음)", None)]
                judgment = "미판단"
                interp = ""

            _add_term_text_box(slide, _A_X[2], y, _A_W[2], row_h,
                               "", terms, font_size=9, chunks=ev_chunks)

            # 도면/근거 이미지: 같은 도면 그룹은 첫 행에만 (모든 요소 색 포함)
            if region_maps:
                if first_show:
                    _add_region_image(slide, gmembers, colors,
                                      _A_X[3], y, int(_A_W[3]),
                                      int(row_h) - int(Inches(0.06)),
                                      terms=terms)
                else:
                    _add_text_box(slide, _A_X[3], y + Inches(0.06),
                                  _A_W[3], Inches(0.4),
                                  "▲ 위 도면과 동일 (함께 표시됨)",
                                  font_size=9, color=SUB,
                                  align=PP_ALIGN.CENTER)

            # 판단 필
            _judgment_pill(slide, _A_X[4], y + Inches(0.02), _A_W[4],
                           judgment, interp)

            y += row_h + Inches(0.08)
            # 행 구분선
            _rect(slide, _A_X[0], y - Inches(0.05),
                  _A_X[4] + _A_W[4] - _A_X[0], Inches(0.012), BORDER)


# ------------------------------------------------------------ Type B
def _type_b_slide(prs: Presentation, claim: Claim,
                  mappings: list, doc_label: str,
                  terms: list, colors: dict):
    """구성요소 1개당 슬라이드 1장 — 좌측 청구항 카드, 우측 도면 크게."""
    by_elem: dict = {}
    for m in mappings:
        by_elem.setdefault(m.element_id, []).append(m)

    for elem in claim.elements:
        elem_maps = by_elem.get(elem.element_id, [])
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        elem_rgb = tuple(elem.color_rgb) if elem.color_rgb else (150, 150, 150)

        # 상단 밴드
        _round_rect(slide, Inches(0.25), Inches(0.22), Inches(12.83),
                    Inches(0.62), fill=LIGHT, radius=0.22)
        _chip(slide, Inches(0.45), Inches(0.36), Inches(0.95), Inches(0.36),
              elem.element_id, elem_rgb, font_size=12)
        _add_text_box(slide, Inches(1.6), Inches(0.33), Inches(7.0),
                      Inches(0.42),
                      f"청구항 {claim.claim_number} — 구성요소 {elem.element_id}",
                      font_size=15, bold=True, color=INK)
        _add_text_box(slide, Inches(8.8), Inches(0.38), Inches(4.1),
                      Inches(0.36), doc_label, font_size=10, color=SUB,
                      align=PP_ALIGN.RIGHT)

        # ── 좌측: 청구항 카드
        _round_rect(slide, Inches(0.3), Inches(1.05), Inches(6.15),
                    Inches(6.1), fill=WHITE, line=BORDER, radius=0.05)
        _add_text_box(slide, Inches(0.55), Inches(1.22), Inches(3.0),
                      Inches(0.3), "청구항 기재", font_size=10, bold=True,
                      color=SUB)
        _add_term_text_box(slide, Inches(0.55), Inches(1.6), Inches(5.65),
                           Inches(3.9), elem.text, terms, font_size=12.5)

        if elem_maps:
            judgment = elem_maps[0].judgment
            interp = elem_maps[0].interpretation
        else:
            judgment, interp = "미판단", ""
        _judgment_pill(slide, Inches(0.55), Inches(5.7), Inches(1.9),
                       judgment, interp)

        notes = "\n".join(m.note for m in elem_maps if m.note)
        if notes:
            _add_text_box(slide, Inches(0.55), Inches(6.15), Inches(5.6),
                          Inches(0.85), f"비고: {notes}", font_size=9,
                          color=SUB)

        # ── 우측: 도면/근거
        region_index = build_region_index(mappings)
        regions = list(group_mappings_by_region(elem_maps).values())
        if not regions:
            _add_text_box(slide, Inches(6.75), Inches(3.6), Inches(6.2),
                          Inches(0.5), "(매핑된 선행문헌 없음)",
                          font_size=12, color=SUB, align=PP_ALIGN.CENTER)
            continue

        n_show = min(len(regions), 2)
        block_h = Inches(6.1 / n_show)
        y = Inches(1.05)
        for region_maps in regions[:2]:
            m0 = region_maps[0]
            _gk, gmembers = region_index.get(m0.mapping_id,
                                             (None, region_maps))
            caption = f"{os.path.basename(m0.doc_path)}  ·  p.{m0.page + 1}"
            others = sorted({m.element_id for m in gmembers
                             if m.element_id != elem.element_id})
            if others:
                caption += f"   [공통 대응: {', '.join(others)}]"
            _add_text_box(slide, Inches(6.75), y, Inches(6.25),
                          Inches(0.28), caption, font_size=9, bold=True,
                          color=SUB)

            img_top = y + Inches(0.32)
            img_h = block_h - Inches(1.0)
            ok = _add_region_image(slide, gmembers, colors,
                                   Inches(6.75), img_top,
                                   int(Inches(6.25)), int(img_h),
                                   terms=terms)
            if not ok:
                _add_text_box(slide, Inches(6.75), img_top, Inches(6.25),
                              Inches(0.4), "(도면 캡처 실패)", font_size=10,
                              color=JUDGMENT_STYLE["불일치"][0])

            if m0.extracted_text:
                _add_term_text_box(slide, Inches(6.75),
                                   img_top + img_h + Inches(0.05),
                                   Inches(6.25), Inches(0.55), "",
                                   terms, font_size=9,
                                   chunks=evidence_chunks(m0, terms))
            y += block_h


# ------------------------------------------------------------ Type C
def _type_c_slide(prs: Presentation, claim: Claim,
                  all_mappings: list, doc_paths: list):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(slide, f"청구항 {claim.claim_number} 조합 무효 매트릭스")

    doc_labels = [os.path.basename(p) for p in doc_paths] if doc_paths \
        else ["선행문헌"]
    n_docs = len(doc_labels)

    elem_col_w = Inches(2.6)
    doc_col_w = Inches(10.2 / max(n_docs, 1))
    row_h = Inches(0.5)
    top = Inches(1.05)
    x0 = Inches(0.3)

    # 헤더 밴드
    _round_rect(slide, x0, top, elem_col_w + doc_col_w * n_docs,
                Inches(0.36), fill=LIGHT, radius=0.3)
    _add_text_box(slide, x0, top + Inches(0.04), elem_col_w, Inches(0.3),
                  "구성요소", font_size=10, bold=True, color=SUB,
                  align=PP_ALIGN.CENTER)
    for di, dlabel in enumerate(doc_labels):
        _add_text_box(slide, x0 + elem_col_w + doc_col_w * di,
                      top + Inches(0.04), doc_col_w, Inches(0.3),
                      dlabel, font_size=9, bold=True, color=SUB,
                      align=PP_ALIGN.CENTER)

    y = top + Inches(0.46)
    for elem in claim.elements:
        if y + row_h > Inches(7.15):
            break
        rgb = tuple(elem.color_rgb) if elem.color_rgb else (150, 150, 150)
        _chip(slide, x0, y + Inches(0.05), Inches(0.8), Inches(0.32),
              elem.element_id, rgb)
        _add_text_box(slide, x0 + Inches(0.9), y + Inches(0.05),
                      elem_col_w - Inches(0.95), Inches(0.4),
                      f"{elem.text[:32]}...", font_size=8, color=INK)

        for di, dpath in enumerate(doc_paths):
            cell_maps = [m for m in all_mappings
                         if m.element_id == elem.element_id
                         and m.doc_path == dpath]
            cx = x0 + elem_col_w + doc_col_w * di
            if cell_maps:
                j = cell_maps[0].judgment
                interp = INTERPRETATION_LABELS.get(
                    cell_maps[0].interpretation, "")
                fg, bg = JUDGMENT_STYLE.get(j, JUDGMENT_STYLE["미판단"])
                pill_w = min(doc_col_w - Inches(0.2), Inches(1.7))
                _pill(slide, cx + (doc_col_w - pill_w) / 2,
                      y + Inches(0.07), pill_w, Inches(0.3),
                      f"{j} {interp}".strip(), fg, bg, size=8)
            else:
                _add_text_box(slide, cx, y + Inches(0.08), doc_col_w,
                              Inches(0.3), "—", font_size=10, color=SUB,
                              align=PP_ALIGN.CENTER)
        y += row_h
        _rect(slide, x0, y - Inches(0.02),
              elem_col_w + doc_col_w * n_docs, Inches(0.012), BORDER)


# ------------------------------------------------------------ 진입점
def export_pptx(data: ProjectData, output_path: str,
                template_type: str = "A",
                include_cover: bool = True):
    """
    PPTX 내보내기. 성공 시 None, 실패 시 오류 메시지(str) 반환.
    template_type: "A" | "B" | "C"
    """
    try:
        prs = Presentation()
        prs.slide_width = SLIDE_W
        prs.slide_height = SLIDE_H

        if include_cover:
            title = data.case_info.title or "특허 Claim Chart"
            _cover_slide(prs, data.case_info, title)

        terms = data.terms
        colors = _color_maps(data)

        if terms:
            _term_legend_slide(prs, terms)

        for claim in data.claims:
            claim_mappings = [m for m in data.mappings
                              if m.claim_number == claim.claim_number]
            doc_paths = list(dict.fromkeys(
                m.doc_path for m in claim_mappings))

            if template_type == "A":
                for dp in (doc_paths or [""]):
                    doc_label = os.path.basename(dp) if dp else "선행문헌"
                    doc_maps = [m for m in claim_mappings
                                if m.doc_path == dp]
                    _type_a_slide(prs, claim, doc_maps, doc_label,
                                  terms, colors)
            elif template_type == "B":
                for dp in (doc_paths or [""]):
                    doc_label = os.path.basename(dp) if dp else "선행문헌"
                    doc_maps = [m for m in claim_mappings
                                if m.doc_path == dp]
                    _type_b_slide(prs, claim, doc_maps, doc_label,
                                  terms, colors)
            elif template_type == "C":
                _type_c_slide(prs, claim, claim_mappings, doc_paths)

        prs.save(output_path)
        return None
    except Exception as e:
        log_exception("PPTX 내보내기")
        return f"{type(e).__name__}: {e}"
