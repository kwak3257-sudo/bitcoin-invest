"""환경 변수 설정. API 키는 .env 파일이나 서버 환경 변수로만 넣고 코드에 적지 않는다.

저장소 맨 위의 .env 파일이 있으면 먼저 읽는다. 이미 설정된 환경 변수가 우선이다.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT / "backend" / "data")
if not DATA_DIR.is_absolute():
    DATA_DIR = ROOT / DATA_DIR
BITHUMB_ACCESS_KEY = os.getenv("BITHUMB_ACCESS_KEY") or None
BITHUMB_SECRET_KEY = os.getenv("BITHUMB_SECRET_KEY") or None
# 엔진이 예정 시각을 확인하는 주기(초)
ENGINE_TICK_SECONDS = int(os.getenv("ENGINE_TICK_SECONDS", "30"))
