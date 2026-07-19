"""매핑 엔진: Undo/Redo 스택, 매핑 CRUD."""
import uuid
from copy import deepcopy
from typing import Optional, Callable

from core.project import MappingEntry, ProjectData


class Command:
    def execute(self): pass
    def undo(self): pass


class AddMappingCommand(Command):
    def __init__(self, data: ProjectData, entry: MappingEntry, on_change: Callable):
        self._data = data
        self._entry = entry
        self._on_change = on_change

    def execute(self):
        self._data.mappings.append(deepcopy(self._entry))
        self._on_change()

    def undo(self):
        self._data.mappings = [m for m in self._data.mappings
                               if m.mapping_id != self._entry.mapping_id]
        self._on_change()


class DeleteMappingCommand(Command):
    def __init__(self, data: ProjectData, mapping_id: str, on_change: Callable):
        self._data = data
        self._mapping_id = mapping_id
        self._on_change = on_change
        self._deleted: Optional[MappingEntry] = None
        self._index: int = -1

    def execute(self):
        for i, m in enumerate(self._data.mappings):
            if m.mapping_id == self._mapping_id:
                self._deleted = deepcopy(m)
                self._index = i
                break
        if self._deleted:
            self._data.mappings.pop(self._index)
        self._on_change()

    def undo(self):
        if self._deleted is not None:
            self._data.mappings.insert(self._index, deepcopy(self._deleted))
        self._on_change()


class UpdateMappingCommand(Command):
    def __init__(self, data: ProjectData, mapping_id: str,
                 new_values: dict, on_change: Callable):
        self._data = data
        self._mapping_id = mapping_id
        self._new_values = new_values
        self._on_change = on_change
        self._old_values: dict = {}

    def execute(self):
        for m in self._data.mappings:
            if m.mapping_id == self._mapping_id:
                for k, v in self._new_values.items():
                    self._old_values[k] = getattr(m, k)
                    setattr(m, k, v)
                break
        self._on_change()

    def undo(self):
        for m in self._data.mappings:
            if m.mapping_id == self._mapping_id:
                for k, v in self._old_values.items():
                    setattr(m, k, v)
                break
        self._on_change()


class MappingEngine:
    def __init__(self, data: ProjectData, on_change: Optional[Callable] = None):
        self.data = data
        self._on_change = on_change or (lambda: None)
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []

    def set_data(self, data: ProjectData):
        self.data = data
        self._undo_stack.clear()
        self._redo_stack.clear()

    def _execute(self, cmd: Command):
        cmd.execute()
        self._undo_stack.append(cmd)
        self._redo_stack.clear()

    def add_mapping(self, element_id: str, claim_number: int,
                    doc_path: str, page: int, rect: list,
                    extracted_text: str = "",
                    judgment: str = "미판단",
                    interpretation: str = "문언침해",
                    note: str = "",
                    term_id: str = "",
                    term_spans: list = None) -> MappingEntry:
        entry = MappingEntry(
            mapping_id=str(uuid.uuid4()),
            element_id=element_id,
            claim_number=claim_number,
            doc_path=doc_path,
            page=page,
            rect=rect,
            extracted_text=extracted_text,
            judgment=judgment,
            interpretation=interpretation,
            note=note,
            term_id=term_id,
            term_spans=list(term_spans or []),
        )
        cmd = AddMappingCommand(self.data, entry, self._on_change)
        self._execute(cmd)
        return entry

    def delete_mapping(self, mapping_id: str):
        cmd = DeleteMappingCommand(self.data, mapping_id, self._on_change)
        self._execute(cmd)

    def update_mapping(self, mapping_id: str, **kwargs):
        cmd = UpdateMappingCommand(self.data, mapping_id, kwargs, self._on_change)
        self._execute(cmd)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        cmd = self._undo_stack.pop()
        cmd.undo()
        self._redo_stack.append(cmd)
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        cmd = self._redo_stack.pop()
        cmd.execute()
        self._undo_stack.append(cmd)
        return True

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def get_mappings_for_element(self, element_id: str,
                                  claim_number: int) -> list[MappingEntry]:
        return [m for m in self.data.mappings
                if m.element_id == element_id and m.claim_number == claim_number]

    def get_mappings_for_doc(self, doc_path: str,
                              page: int) -> list[MappingEntry]:
        return [m for m in self.data.mappings
                if m.doc_path == doc_path and m.page == page]

    def completion_ratio(self, claim_number: int) -> float:
        """해당 청구항의 전체 구성요소 중 최소 1개 이상 매핑된 비율."""
        claim = next((c for c in self.data.claims
                      if c.claim_number == claim_number), None)
        if not claim or not claim.elements:
            return 0.0
        mapped_ids = {m.element_id for m in self.data.mappings
                      if m.claim_number == claim_number}
        elem_ids = {e.element_id for e in claim.elements}
        if not elem_ids:
            return 0.0
        return len(mapped_ids & elem_ids) / len(elem_ids)
