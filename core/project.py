"""프로젝트 저장/불러오기 (.pcc 파일, JSON 기반)"""
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


AUTOSAVE_INTERVAL_MS = 5 * 60 * 1000  # 5분


@dataclass
class CaseInfo:
    application_number: str = ""
    registration_number: str = ""
    priority_date: str = ""
    application_date: str = ""
    registration_date: str = ""
    family_patents: list[str] = field(default_factory=list)
    title: str = ""
    applicant: str = ""
    notes: str = ""


@dataclass
class ClaimElement:
    """청구항 구성요소 (1A, 1B, ...)"""
    element_id: str = ""       # "1A", "1B", ...
    text: str = ""
    color_rgb: tuple = (128, 128, 128)


@dataclass
class Claim:
    claim_number: int = 1
    is_independent: bool = True
    parent_claim: Optional[int] = None
    full_text: str = ""
    elements: list[ClaimElement] = field(default_factory=list)


@dataclass
class ClaimTerm:
    """청구항-선행문헌 간 매칭 용어 (단어/구문 단위, 프로젝트 전역).

    청구항 텍스트와 선행문헌에서 같은 용어는 같은 색으로 표시된다.
    """
    term_id: str = ""          # "T1", "T2", ...
    text: str = ""             # 용어 (예: "power line")
    color_rgb: tuple = (200, 100, 100)
    note: str = ""


@dataclass
class MappingEntry:
    """하나의 구성요소 <-> 선행문헌 텍스트/도면 매핑"""
    mapping_id: str = ""
    element_id: str = ""          # 청구항 구성요소 ID
    claim_number: int = 1
    doc_path: str = ""            # 선행문헌 파일 경로
    page: int = 0
    rect: list = field(default_factory=lambda: [0, 0, 0, 0])  # PDF 좌표계 [x0,y0,x1,y1]
    extracted_text: str = ""
    judgment: str = "미판단"      # 일치 / 불일치 / 부분일치 / 미판단
    interpretation: str = "문언침해"  # 문언침해 / 균등론 / 넓게해석 / 좁게해석
    note: str = ""
    # extracted_text 안에서 요소 색을 입힐 단어 범위: [[start, end, term_id], ...]
    term_spans: list = field(default_factory=list)
    term_id: str = ""             # 매칭 용어 ID (설정 시 용어 색으로 표시)


@dataclass
class ProjectData:
    version: str = "1.0"
    case_info: CaseInfo = field(default_factory=CaseInfo)
    claims: list[Claim] = field(default_factory=list)
    terms: list[ClaimTerm] = field(default_factory=list)
    mappings: list[MappingEntry] = field(default_factory=list)
    doc_paths: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    modified_at: float = field(default_factory=time.time)


class ProjectManager:
    def __init__(self):
        self.current_path: Optional[str] = None
        self.data = ProjectData()
        self._dirty = False
        self._crash_recovery_path = os.path.join(
            tempfile.gettempdir(), "pcc_autosave.pcc"
        )
        self._recent_files_path = os.path.join(
            os.path.expanduser("~"), ".pcc_recent.json"
        )

    def new_project(self):
        self.data = ProjectData()
        self.current_path = None
        self._dirty = False

    def save(self, path: Optional[str] = None) -> bool:
        target = path or self.current_path
        if not target:
            return False
        try:
            self.data.modified_at = time.time()
            raw = self._serialize()
            tmp = target + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
            shutil.move(tmp, target)
            self.current_path = target
            self._dirty = False
            self._update_recent(target)
            # 크래시 복구용 파일도 같이 업데이트
            shutil.copy2(target, self._crash_recovery_path)
            return True
        except Exception as e:
            print(f"[ProjectManager] save error: {e}")
            return False

    def autosave(self):
        """5분 자동저장 - 크래시 복구 파일에만 저장"""
        try:
            self.data.modified_at = time.time()
            raw = self._serialize()
            with open(self._crash_recovery_path, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ProjectManager] autosave error: {e}")

    def load(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.data = self._deserialize(raw)
            self.current_path = path
            self._dirty = False
            self._update_recent(path)
            return True
        except Exception as e:
            print(f"[ProjectManager] load error: {e}")
            return False

    def has_crash_recovery(self) -> bool:
        return os.path.exists(self._crash_recovery_path)

    def load_crash_recovery(self) -> bool:
        return self.load(self._crash_recovery_path)

    def clear_crash_recovery(self):
        if os.path.exists(self._crash_recovery_path):
            os.remove(self._crash_recovery_path)

    def get_recent_files(self) -> list[str]:
        try:
            if os.path.exists(self._recent_files_path):
                with open(self._recent_files_path, "r", encoding="utf-8") as f:
                    files = json.load(f)
                return [f for f in files if os.path.exists(f)]
        except Exception:
            pass
        return []

    def mark_dirty(self):
        self._dirty = True

    def is_dirty(self) -> bool:
        return self._dirty

    # --- serialization helpers ---

    def _serialize(self) -> dict:
        d = asdict(self.data)
        # tuple -> list 변환은 asdict가 자동 처리
        return d

    def _deserialize(self, raw: dict) -> ProjectData:
        ci_raw = raw.get("case_info", {})
        ci = CaseInfo(**{k: v for k, v in ci_raw.items() if k in CaseInfo.__dataclass_fields__})

        claims = []
        for c in raw.get("claims", []):
            elements = [
                ClaimElement(
                    element_id=e.get("element_id", ""),
                    text=e.get("text", ""),
                    color_rgb=tuple(e.get("color_rgb", [128, 128, 128]))
                )
                for e in c.get("elements", [])
            ]
            claims.append(Claim(
                claim_number=c.get("claim_number", 1),
                is_independent=c.get("is_independent", True),
                parent_claim=c.get("parent_claim"),
                full_text=c.get("full_text", ""),
                elements=elements,
            ))

        terms = []
        for t in raw.get("terms", []):
            terms.append(ClaimTerm(
                term_id=t.get("term_id", ""),
                text=t.get("text", ""),
                color_rgb=tuple(t.get("color_rgb", [200, 100, 100])),
                note=t.get("note", ""),
            ))

        mappings = []
        for m in raw.get("mappings", []):
            mappings.append(MappingEntry(**{
                k: v for k, v in m.items()
                if k in MappingEntry.__dataclass_fields__
            }))

        return ProjectData(
            version=raw.get("version", "1.0"),
            case_info=ci,
            claims=claims,
            terms=terms,
            mappings=mappings,
            doc_paths=raw.get("doc_paths", []),
            created_at=raw.get("created_at", time.time()),
            modified_at=raw.get("modified_at", time.time()),
        )

    def _update_recent(self, path: str):
        try:
            files = self.get_recent_files()
            if path in files:
                files.remove(path)
            files.insert(0, path)
            files = files[:10]
            with open(self._recent_files_path, "w", encoding="utf-8") as f:
                json.dump(files, f, ensure_ascii=False)
        except Exception:
            pass
