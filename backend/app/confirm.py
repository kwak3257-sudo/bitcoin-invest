"""실거래에 영향을 주는 설정 변경은 텔레그램으로 보낸 인증번호를 넣어야 저장된다.

누군가 화면에 들어오더라도 내 텔레그램 없이는 실제 돈이 움직이는 설정을 바꿀 수 없게 한다.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException

from . import notify

CODE_TTL_SECONDS = 300
MAX_TRIES = 5


@dataclass
class _Pending:
    code: str
    payload_hash: str
    expires: float
    tries: int = 0


class ConfirmGate:
    def __init__(self) -> None:
        self._pending: dict[str, _Pending] = {}

    async def require(self, action: str, description: str, payload: str, code: str | None) -> None:
        """코드가 맞으면 그냥 돌아오고, 아니면 새 코드를 보내거나 거절한다(HTTPException)."""
        if not notify.enabled():
            raise HTTPException(
                400, "실거래 설정은 텔레그램 인증을 켠 뒤에 바꿀 수 있습니다. .env에 텔레그램 봇 토큰과 채팅 ID를 넣어 주세요."
            )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        pending = self._pending.get(action)
        valid = pending is not None and pending.payload_hash == digest and time.time() < pending.expires

        if code and valid:
            assert pending is not None
            if secrets.compare_digest(code.strip(), pending.code):
                del self._pending[action]
                return
            pending.tries += 1
            if pending.tries >= MAX_TRIES:
                del self._pending[action]
                await notify.send(f"⚠️ 인증번호가 {MAX_TRIES}번 틀려 요청을 취소했습니다: {description}")
                raise HTTPException(403, "인증번호가 여러 번 틀려 요청을 취소했습니다. 다시 저장해 새 번호를 받으세요.")
            raise HTTPException(403, "인증번호가 맞지 않습니다.")

        new_code = f"{secrets.randbelow(10**6):06d}"
        self._pending[action] = _Pending(new_code, digest, time.time() + CODE_TTL_SECONDS)
        await notify.send(
            f"🔐 인증번호 {new_code}\n요청: {description}\n5분 안에 화면에 입력하세요. "
            "본인이 한 요청이 아니면 입력하지 말고 PC의 프로그램을 끄세요."
        )
        raise HTTPException(428, "텔레그램으로 보낸 인증번호 6자리를 입력하세요.")
