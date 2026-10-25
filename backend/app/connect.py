"""빗썸 API 키와 텔레그램을 한 번에 연결하는 도우미. connect.bat이 실행한다.

- 빗썸: 이 PC의 공인 IP를 보여 주고(키 발급 때 허용 IP로 넣음), 키를 받아 잔고 조회로 확인한다.
- 텔레그램: 봇 토큰을 확인하고, 사용자가 봇에게 보낸 메시지로 채팅 ID를 찾는다.
키와 토큰은 화면에 보이지 않게 입력받고, 이 PC의 .env에만 저장한다. Enter만 누르면 그 단계는 건너뛴다.

    python -m app.connect
"""

from __future__ import annotations

import asyncio
import getpass
import sys
import time

import httpx

from .config import ROOT
from .exchanges.base import ExchangeError
from .exchanges.bithumb import BithumbExchange

ENV = ROOT / ".env"
WAIT_SECONDS = 180


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
    access = getpass.getpass("Access Key를 붙여넣고 Enter (화면에 안 보임, 건너뛰려면 그냥 Enter): ").strip()
    if not access:
        print("빗썸 연결을 건너뜁니다. 모의투자는 키 없이도 됩니다.")
        return True
    secret = getpass.getpass("Secret Key를 붙여넣고 Enter (화면에 안 보임): ").strip()
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
    print("휴대폰 텔레그램에서 @BotFather 를 검색해 /newbot 을 보내고, 봇 이름을 두 번 정하면 토큰을 줍니다.")
    token = getpass.getpass("토큰을 붙여넣고 Enter (화면에 안 보임, 건너뛰려면 그냥 Enter): ").strip()
    if not token:
        print("텔레그램 연결을 건너뜁니다. 실거래는 텔레그램을 연결해야 켤 수 있어요.")
        return True
    api = f"https://api.telegram.org/bot{token}"
    with httpx.Client(timeout=15) as client:
        r = client.get(f"{api}/getMe")
        if r.status_code != 200 or not r.json().get("ok"):
            print("토큰이 맞지 않습니다. BotFather가 준 토큰 전체를 다시 복사해 주세요.")
            return False
        name = r.json()["result"]["username"]
        # 예전 메시지는 건너뛰고, 지금부터 오는 메시지만 본다
        old = client.get(f"{api}/getUpdates", params={"offset": -1}).json().get("result", [])
        offset = old[-1]["update_id"] + 1 if old else None

        print(f"휴대폰 텔레그램에서 @{name} 을 검색해 열고, 시작(Start)을 누르거나 아무 글자나 보내세요.")
        print(f"   {WAIT_SECONDS // 60}분 동안 기다립니다...")
        chat_id = None
        deadline = time.time() + WAIT_SECONDS
        while time.time() < deadline and chat_id is None:
            params = {"timeout": 20, **({"offset": offset} if offset else {})}
            for u in client.get(f"{api}/getUpdates", params=params, timeout=30).json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if msg.get("chat", {}).get("type") == "private":
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
