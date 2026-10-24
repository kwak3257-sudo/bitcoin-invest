"""환경 변수 설정. API 키는 .env 파일이나 서버 환경 변수로만 넣고 코드에 적지 않는다."""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
BITHUMB_ACCESS_KEY = os.getenv("BITHUMB_ACCESS_KEY") or None
BITHUMB_SECRET_KEY = os.getenv("BITHUMB_SECRET_KEY") or None
# 엔진이 예정 시각을 확인하는 주기(초)
ENGINE_TICK_SECONDS = int(os.getenv("ENGINE_TICK_SECONDS", "30"))
