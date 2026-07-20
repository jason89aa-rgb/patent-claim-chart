"""붙여넣은 선행문헌 명세서 텍스트를 텍스트 문서로 보관한다.

PDF로 변환하지 않는다 — 붙여넣은 텍스트는 텍스트 뷰어 탭에서
그대로 텍스트로 보이고, 선택·검색·매핑이 문자 오프셋 기준으로 동작한다.
"""
import hashlib
import os
import re
import tempfile

_OUT_DIR = os.path.join(tempfile.gettempdir(), "pcc_text_docs")

TEXT_EXTS = (".txt",)

# 파일명 끝의 md5 접미사 (표시용 라벨을 만들 때 떼어낸다)
DIGEST_SUFFIX = re.compile(r"_[0-9a-f]{12}$")


def is_text_doc(path: str) -> bool:
    return (path or "").lower().endswith(TEXT_EXTS)


def _safe_name(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", (title or "").strip())
    return name[:60] or "붙여넣은 문서"


def doc_title(path: str) -> str:
    """텍스트 문서 경로에서 사용자가 붙인 제목을 복원."""
    name = os.path.splitext(os.path.basename(path or ""))[0]
    return DIGEST_SUFFIX.sub("", name) or "붙여넣은 명세서"


def save_text_doc(text: str, title: str = "붙여넣은 명세서") -> str | None:
    """붙여넣은 텍스트를 .txt로 저장하고 경로를 반환.

    같은 내용이면 같은 경로가 나오므로(md5) 탭이 중복 생성되지 않는다.
    """
    if not (text or "").strip():
        return None
    os.makedirs(_OUT_DIR, exist_ok=True)
    digest = hashlib.md5(
        (title + "\x00" + text).encode("utf-8")).hexdigest()[:12]
    out = os.path.join(_OUT_DIR, f"{_safe_name(title)}_{digest}.txt")
    if not os.path.exists(out):
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    return out


def load_text_doc(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def clear_cache():
    if not os.path.isdir(_OUT_DIR):
        return
    for name in os.listdir(_OUT_DIR):
        try:
            os.remove(os.path.join(_OUT_DIR, name))
        except OSError:
            pass
