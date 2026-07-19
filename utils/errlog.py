"""내보내기 등에서 발생한 예외를 크래시 로그에 남긴다 (--noconsole 대응)."""
import os
import datetime
import traceback


def _log_path() -> str:
    log_dir = os.path.join(os.path.expanduser("~"), "PatentClaimChart_logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "crash.log")


def log_exception(context: str):
    """현재 예외의 전체 트레이스백을 로그 파일에 기록."""
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(f"\n--- {context} 오류 {datetime.datetime.now()} ---\n")
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        pass
