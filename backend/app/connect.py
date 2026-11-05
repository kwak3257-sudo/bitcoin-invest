"""빗썸 API 키와 텔레그램을 한 번에 연결하는 도우미. connect.bat이 실행한다.

- 빗썸: 이 PC의 공인 IP를 보여 주고(키 발급 때 허용 IP로 넣음), 키를 받아 잔고 조회로 확인한다.
- 텔레그램: 봇 토큰을 확인하고, 사용자가 봇에게 보낸 메시지로 채팅 ID를 찾는다.
키와 토큰은 복사만 하고 Enter를 누르면 클립보드에서 읽는다(붙여 넣어도 된다). 이 PC의 .env에만 저장하고, s를 넣으면 그 단계는 건너뛴다.

    python -m app.connect
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time

import httpx

from .config import ROOT
from .exchanges.base import ExchangeError
from .exchanges.bithumb import BithumbExchange

ENV = ROOT / ".env"
WAIT_SECONDS = 180
RECENT_SECONDS = 600  # 프로그램이 기다리기 전에 보낸 메시지도 10분 안이면 받아 준다


def clipboard() -> str:
    if sys.platform != "win32":
        return ""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


def read_secret(label: str, pattern: re.Pattern | None = None) -> str | None:
    """복사해 둔 값을 읽는다. pattern이 있으면 긴 메시지를 통째로 복사해도 그 부분만 찾는다. 건너뛰면 None."""
    while True:
        typed = input(f"{label}을(를) 복사한 뒤 Enter (붙여 넣어도 됨, 건너뛰려면 s 입력 후 Enter): ").strip()
        if typed.lower() == "s":
            return None
        value = typed or clipboard()
        if pattern is not None:
            found = pattern.findall(value)
            value = found[-1] if found else ""
        if value and " " not in value and len(value) >= 20:
            print(f"   읽었어요: {value[:4]}…{value[-4:]}")
            return value
        print("   복사된 값을 찾지 못했어요. 다시 복사한 뒤 Enter를 눌러 주세요.")


def save_env(values: dict[str, str]) -> None:
    lines = ENV.read_text(encoding="utf-8-sig").splitlines() if ENV.exists() else []
    left = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in left:
            out.append(f"{key}={left.pop(key)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in left.items()]
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")


def public_ip() -> str | None:
    try:
        return httpx.get("https://api.ipify.org", timeout=10).text.strip()
    except httpx.HTTPError:
        return None


async def check_bithumb(access: str, secret: str) -> str:
    ex = BithumbExchange(access, secret)
    try:
        krw = next((b.balance for b in await ex.balances() if b.currency == "KRW"), 0)
        return f"{krw:,.0f}"
    finally:
        await ex.close()


def connect_bithumb() -> bool:
    print("\n=== 1. 빗썸 API 키 ===")
    ip = public_ip()
    print("빗썸 웹사이트에 로그인해 API 관리 메뉴에서 새 키를 발급하세요.")
    print("  - 권한: 자산 조회, 주문 조회, 주문하기만 체크. ★출금은 절대 체크하지 마세요★")
    print(f"  - 허용 IP: {ip or '(IP를 찾지 못했습니다. 네이버에서 내 IP 주소를 검색해 넣으세요)'}")
    access = read_secret("Access Key")
    if not access:
        print("빗썸 연결을 건너뜁니다. 모의투자는 키 없이도 됩니다.")
        return True
    secret = read_secret("Secret Key")
    if not secret:
        print("빗썸 연결을 건너뜁니다.")
        return True
    try:
        krw = asyncio.run(check_bithumb(access, secret))
    except ExchangeError as exc:
        print(f"키 확인 실패: {exc}")
        print("키를 다시 복사했는지, 허용 IP가 위 주소와 같은지 확인한 뒤 connect.bat을 다시 실행하세요.")
        return False
    save_env({"BITHUMB_ACCESS_KEY": access, "BITHUMB_SECRET_KEY": secret})
    print(f"빗썸 연결 완료! 원화 잔고 {krw}원을 확인했습니다.")
    return True


def connect_telegram() -> bool:
    print("\n=== 2. 텔레그램 (알림과 인증번호) ===")
    print("텔레그램에서 @BotFather 에게 /token 을 보내고 내 봇을 고르면 토큰을 줍니다. 봇이 없으면 /newbot 으로 만드세요.")
    print("토큰이 든 메시지를 통째로 복사해도 됩니다.")
    token = read_secret("토큰", TOKEN_RE)
    if not token:
        print("텔레그램 연결을 건너뜁니다. 실거래는 텔레그램을 연결해야 켤 수 있어요.")
        return True
    api = f"https://api.telegram.org/bot{token}"
    with httpx.Client(timeout=15) as client:
        r = client.get(f"{api}/getMe")
        if r.status_code != 200 or not r.json().get("ok"):
            print("토큰이 맞지 않습니다. 예전 토큰일 수 있어요.")
            print("BotFather에게 /token 을 보내고 봇을 고르면 지금 쓸 수 있는 토큰을 보여 줍니다. 그 메시지를 복사한 뒤 connect.bat을 다시 실행하세요.")
            return False
        name = r.json()["result"]["username"]
        since = time.time() - RECENT_SECONDS
        offset = None

        print(f"휴대폰 텔레그램에서 @{name} 을 검색해 열고, 시작(Start)을 누르거나 아무 글자나 보내세요. 이미 보냈다면 잠시 기다리세요.")
        print(f"   {WAIT_SECONDS // 60}분 동안 기다립니다...")
        chat_id = None
        deadline = time.time() + WAIT_SECONDS
        while time.time() < deadline and chat_id is None:
            params = {"timeout": 20, **({"offset": offset} if offset else {})}
            for u in client.get(f"{api}/getUpdates", params=params, timeout=30).json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if msg.get("chat", {}).get("type") == "private" and msg.get("date", 0) >= since:
                    chat_id = msg["chat"]["id"]
        if chat_id is None:
            print("메시지를 받지 못했습니다. 봇에게 메시지를 보낸 뒤 connect.bat을 다시 실행하세요.")
            return False

        save_env({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": str(chat_id)})
        client.post(f"{api}/sendMessage", json={
            "chat_id": chat_id,
            "text": "✅ 코인 투자 도우미와 연결됐어요. 앞으로 거래 알림과 인증번호가 여기로 옵니다.",
        })
    print("텔레그램 연결 완료! 휴대폰에 시험 메시지가 갔는지 확인하세요.")
    return True


def main() -> int:
    ok = connect_bithumb() and connect_telegram()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
