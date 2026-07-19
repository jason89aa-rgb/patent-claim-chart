"""HSL 기반 색상 자동 분배 유틸리티"""
import colorsys


def generate_colors(n: int) -> list[tuple[int, int, int]]:
    """n개의 구성요소에 대해 겹치지 않는 HSL 색상을 RGB로 반환."""
    colors = []
    for i in range(n):
        hue = i / n
        # 채도/밝기를 고정해 가독성 확보
        r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.75)
        colors.append((int(r * 255), int(g * 255), int(b * 255)))
    return colors


def term_color(index: int) -> tuple[int, int, int]:
    """
    매칭 용어용 색상. 황금각(golden angle) 순환으로
    용어가 추가되어도 기존 용어의 색이 바뀌지 않는다.
    구성요소 색보다 진하게(밝기↓ 채도↑) 해서 구분.
    """
    hue = (index * 0.381966) % 1.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.42, 0.9)
    return (int(r * 255), int(g * 255), int(b * 255))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def get_text_color(bg_rgb: tuple[int, int, int]) -> str:
    """배경색 밝기에 따라 흰색 또는 검정색 텍스트 반환."""
    r, g, b = bg_rgb
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000000" if luminance > 140 else "#FFFFFF"
