"""
특허 Claim Chart 생성기 - 메인 진입점
오프라인 환경 전용, 외부 API 호출 없음
"""
import sys
import os
import datetime
import traceback
import multiprocessing

# OCR/PDF 처리를 별도 프로세스로 격리하기 위한 자식 프로세스 여부 판정
_IS_MP_CHILD = any(a.startswith("--multiprocessing")
                   or a.startswith("parent_pid=")
                   or "from multiprocessing" in a
                   for a in sys.argv[1:])


# ---------------------------------------------------------------- 크래시 로그
# --noconsole 빌드에서는 네이티브 크래시(세그폴트)가 화면 없이 창을 닫는다.
# faulthandler + excepthook으로 로그 파일에 원인을 남긴다.
def _setup_crash_logging():
    try:
        log_dir = os.path.join(os.path.expanduser("~"), "PatentClaimChart_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "crash.log")
        f = open(log_path, "a", encoding="utf-8", buffering=1)
        f.write(f"\n===== 실행 시작 {datetime.datetime.now()} =====\n")

        import faulthandler
        faulthandler.enable(file=f)

        def excepthook(exc_type, exc, tb):
            f.write(f"\n--- 예외 {datetime.datetime.now()} ---\n")
            traceback.print_exception(exc_type, exc, tb, file=f)
            f.flush()
            sys.__excepthook__(exc_type, exc, tb)

        sys.excepthook = excepthook

        import threading
        if hasattr(threading, "excepthook"):
            def thread_hook(args):
                f.write(f"\n--- 스레드 예외 {datetime.datetime.now()} ---\n")
                traceback.print_exception(
                    args.exc_type, args.exc_value, args.exc_traceback, file=f)
                f.flush()
            threading.excepthook = thread_hook

        return log_path
    except Exception:
        return None


CRASH_LOG_PATH = None if _IS_MP_CHILD else _setup_crash_logging()


# PyInstaller 번들 환경에서 리소스 경로 처리
def resource_path(relative: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.abspath("."), relative)


def _run_claims_worker() -> int:
    """--extract-claims 워커 모드: GUI 없이 청구항 추출만 수행.

    부모 GUI가 자기 자신(exe)을 이 플래그로 실행한다. PDF 렌더링/OCR이
    네이티브 크래시해도 이 프로세스만 죽고 GUI는 살아남는다.
    (PyInstaller onefile에서 multiprocessing은 부모까지 무너뜨리는
    문제가 있어 단순 CLI 자식 프로세스 방식을 사용)

    프로토콜(stdout, 한 줄씩): PROGRESS <cur> <total> / DONE / ERROR <msg>
    결과: out_json 경로에 청구항 리스트 JSON 저장.
    """
    import json
    from dataclasses import asdict

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                               line_buffering=True)
    except Exception:
        pass

    pdf_path = sys.argv[2]
    out_path = sys.argv[3]

    if os.environ.get("PCC_TEST_CRASH"):     # 크래시 격리 테스트용
        print("PROGRESS 1 10", flush=True)
        os.abort()

    def cb(cur: int, total: int) -> bool:
        print(f"PROGRESS {cur} {total}", flush=True)
        return True

    try:
        from core.claims_extractor import extract_claims_from_pdf
        claims = extract_claims_from_pdf(pdf_path, use_ocr=True,
                                         progress_cb=cb)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in claims], f, ensure_ascii=False)
        print("DONE", flush=True)
        return 0
    except Exception as e:
        print(f"ERROR {type(e).__name__}: {e}", flush=True)
        return 1


def _run_biblio_worker() -> int:
    """--extract-biblio 워커 모드: 스캔본 서지사항을 OCR로 읽는다.

    청구항 추출과 같은 이유로 별도 프로세스에서 돈다 — PDF 렌더링/OCR이
    네이티브 크래시해도 GUI는 살아남는다.
    결과: out_json 경로에 서지사항 dict 저장.
    """
    import json

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                               line_buffering=True)
    except Exception:
        pass

    pdf_path = sys.argv[2]
    out_path = sys.argv[3]

    try:
        from core.biblio_extractor import extract_biblio
        biblio = extract_biblio(pdf_path, use_ocr=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(biblio, f, ensure_ascii=False)
        print("DONE", flush=True)
        return 0
    except Exception as e:
        print(f"ERROR {type(e).__name__}: {e}", flush=True)
        return 1


def _run_selftest_ocr() -> int:
    """--selftest-ocr <pdf>: 번들된 Tesseract만으로 OCR이 되는지 확인.

    다른 PC(= Tesseract 미설치)에서도 동작하는지 배포 전에 검증하는 용도.
    tesseract 경로와 언어팩 경로가 번들 안(_MEIPASS)을 가리켜야 한다.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                               line_buffering=True)
    except Exception:
        pass

    # 시스템에 설치된 Tesseract를 무시하고 번들본만 쓰게 한다
    os.environ["PCC_BUNDLED_TESSERACT_ONLY"] = "1"

    import pytesseract
    from core import ocr_engine

    meipass = getattr(sys, "_MEIPASS", "")
    cmd = pytesseract.pytesseract.tesseract_cmd
    prefix = os.environ.get("TESSDATA_PREFIX", "")
    print(f"MEIPASS   {meipass}", flush=True)
    print(f"TESSERACT {cmd}", flush=True)
    print(f"TESSDATA  {prefix}", flush=True)
    print(f"BUNDLED   {bool(meipass) and str(cmd).startswith(meipass)}",
          flush=True)
    try:
        print(f"VERSION   {pytesseract.get_tesseract_version()}", flush=True)
        print(f"LANGS     {sorted(pytesseract.get_languages(config=''))}",
              flush=True)
    except Exception as e:
        print(f"ERROR {type(e).__name__}: {e}", flush=True)
        return 1

    if len(sys.argv) >= 3:
        from core.biblio_extractor import extract_biblio
        biblio = extract_biblio(sys.argv[2], use_ocr=True)
        got = {k: v for k, v in biblio.items() if v and k != "_source"}
        print(f"OCR-FIELDS {len(got)}", flush=True)
        for key in ("title", "applicant", "application_number",
                    "application_date"):
            if biblio.get(key):
                print(f"  {key} = {biblio[key]}", flush=True)
    print("OCR-SELFTEST-OK", flush=True)
    return 0


def _run_selftest_extract() -> int:
    """--selftest-extract 모드: '프리즈 부모가 프리즈 자식을 낳는' 조합 검증.

    자식 종료 후 부모가 계속 살아서 새 DLL을 로드할 수 있어야 통과.
    (onefile _MEI 공유폴더 파괴 버그를 잡아내기 위한 테스트)
    """
    import time
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                               line_buffering=True)
    except Exception:
        pass
    pdf_path = sys.argv[2]

    from core.claims_extractor import extract_claims_in_subprocess

    def cb(cur, total):
        print(f"P {cur}/{total}", flush=True)
        return True

    claims, err = extract_claims_in_subprocess(pdf_path, progress_cb=cb)
    print(f"RESULT claims={len(claims)} err={err}", flush=True)

    # 자식 정리 후 부모 생존 검증: 아직 안 올라온 모듈/DLL 강제 로드
    time.sleep(1.5)
    import pptx        # noqa: F401
    import docx        # noqa: F401
    import openpyxl    # noqa: F401
    import fitz
    d = fitz.open(pdf_path)
    d[0].get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
    d.close()
    from PyQt6.QtCore import QCoreApplication   # noqa: F401
    print("PARENT-ALIVE", flush=True)
    return 0 if (claims and not err) else 1


def main():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont

    # HiDPI 지원
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("특허 Claim Chart 생성기")
    app.setOrganizationName("PatentTools")
    app.setFont(QFont("맑은 고딕", 10))

    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    # 워커 모드: GUI를 띄우지 않고 청구항 추출만 수행 후 종료
    if len(sys.argv) >= 4 and sys.argv[1] == "--extract-claims":
        sys.exit(_run_claims_worker())
    # 워커 모드: 스캔본 서지사항 OCR
    if len(sys.argv) >= 4 and sys.argv[1] == "--extract-biblio":
        sys.exit(_run_biblio_worker())
    # 프리즈 자기실행 검증 모드 (배포 전 테스트용)
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest-extract":
        sys.exit(_run_selftest_extract())
    # 번들 Tesseract만으로 OCR이 되는지 검증 (다른 PC 배포 전)
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest-ocr":
        sys.exit(_run_selftest_ocr())
    main()
