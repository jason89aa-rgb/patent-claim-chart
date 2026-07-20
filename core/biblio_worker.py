"""스캔본 서지사항 OCR을 별도 프로세스로 실행한다.

청구항 추출과 같은 이유 — PDF 렌더링/OCR이 네이티브 크래시해도
GUI 프로세스는 살아남아야 한다. 한 페이지짜리 단발 작업이라
비동기 상태머신 대신 블로킹 호출을 쓴다 (중첩 이벤트루프 금지).
"""
import json
import os
import subprocess
import sys
import tempfile


def _worker_command(pdf_path: str, out_path: str) -> tuple:
    """(program, args, env) — 프리즈/개발 환경 모두 지원."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        # onefile 자기실행: 자식을 독립 인스턴스로 (부모 _MEI 보호)
        for key in list(env):
            if key.startswith("_PYI") or key.startswith("_MEIPASS"):
                env.pop(key, None)
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        # 부모가 잡아둔 언어팩 경로는 부모의 임시폴더를 가리킨다.
        # 자식이 자기 번들에서 다시 찾도록 지운다.
        env.pop("TESSDATA_PREFIX", None)
        return sys.executable, ["--extract-biblio", pdf_path, out_path], env

    main_py = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return (sys.executable,
            ["-X", "utf8", main_py, "--extract-biblio", pdf_path, out_path],
            env)


def extract_biblio_ocr(pdf_path: str, timeout: int = 300) -> tuple:
    """스캔본에서 서지사항을 OCR로 읽는다.

    반환: (biblio dict 또는 None, 오류 메시지)
    """
    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="pcc_biblio_")
    os.close(fd)
    program, args, env = _worker_command(pdf_path, out_path)

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.run(
            [program] + args, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=creationflags)
    except subprocess.TimeoutExpired:
        _cleanup(out_path)
        return None, f"OCR이 {timeout}초 안에 끝나지 않았습니다."
    except Exception as e:
        _cleanup(out_path)
        return None, f"OCR 프로세스를 시작하지 못했습니다: {e}"

    if proc.returncode != 0:
        out = (proc.stdout or b"").decode("utf-8", "replace").strip()
        msg = out.splitlines()[-1] if out else f"코드 {proc.returncode}"
        _cleanup(out_path)
        return None, f"OCR 처리에 실패했습니다 ({msg})."

    try:
        with open(out_path, "r", encoding="utf-8") as f:
            return json.load(f), ""
    except Exception as e:
        return None, f"OCR 결과를 읽지 못했습니다: {e}"
    finally:
        _cleanup(out_path)


def _cleanup(path: str):
    try:
        os.remove(path)
    except OSError:
        pass
