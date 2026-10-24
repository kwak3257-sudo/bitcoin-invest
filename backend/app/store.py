"""전략 설정과 실행 기록을 JSON 파일에 저장한다. (초기 개인용, 이후 DB로 교체)

API 서버와 매매 엔진이 같은 파일을 쓰므로, 읽고 고쳐 쓰는 동안 파일 잠금을 잡는다.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .strategies.dca import DcaState

if sys.platform == "win32":
    import msvcrt

    def _lock(f) -> None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)  # 잡힐 때까지 기다린다(약 10초마다 재시도)

else:
    import fcntl

    def _lock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_EX)


class DcaStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> DcaState:
        if not self.path.exists():
            return DcaState()
        return DcaState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def _save(self, state: DcaState) -> None:
        data = state.model_dump_json(indent=2)
        # 쓰는 도중 꺼져도 파일이 깨지지 않게 임시 파일에 쓴 뒤 교체
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, self.path)

    @contextmanager
    def edit(self) -> Iterator[DcaState]:
        """잠금을 잡고 상태를 읽어 넘겨준 뒤, 블록이 끝나면 저장한다."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lock:
            _lock(lock)
            state = self.load()
            yield state
            self._save(state)
