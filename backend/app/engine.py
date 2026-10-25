"""매매 엔진. 화면(API 서버)과 별도 프로세스로 실행한다.

    python -m app.engine
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from . import bot, config, notify
from .exchanges.bithumb import BithumbExchange
from .store import DcaStore, TraderStore
from .strategies import trader
from .strategies.dca import KST, run_if_due, take_profit_if_reached

log = logging.getLogger("engine")


async def tick(store: DcaStore, exchange) -> None:
    if not store.load().config.enabled:
        return
    with store.edit() as state:
        now = datetime.now(KST)
        runs = [await run_if_due(state, exchange, now), await take_profit_if_reached(state, exchange, now)]
    for run in runs:
        if run is not None:
            log.info("%s: %s", "매수" if run.side == "buy" else "매도", run.message)


async def trader_tick(store: TraderStore, exchange) -> None:
    before = store.load()
    if not (before.config.enabled or before.stop_requested):
        return
    with store.edit() as state:
        was_halted = state.halted_until is not None
        trades = await trader.step(state, exchange, datetime.now(KST))
        halt = state.halt_reason if state.halted_until is not None and not was_halted else None
        stopped = before.config.enabled and not state.config.enabled
    tag = "[모의]" if state.config.mode == "paper" else "[실거래]"
    for t in trades:
        text = f"{tag} {state.config.market} {t.message}" if t.ok else f"{tag} {t.side} 실패: {t.message}"
        (log.info if t.ok else log.warning)(text)
        await notify.send(text)
    if halt:
        log.warning(halt)
        await notify.send(f"{tag} {halt}")
    if stopped:
        log.warning("단기 매매를 긴급 정지했습니다.")
        await notify.send(f"{tag} 단기 매매를 긴급 정지했습니다.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청 주소에 텔레그램 토큰이 들어 있어 찍지 않는다
    store = DcaStore(config.DATA_DIR / "dca.json")
    trader_store = TraderStore(config.DATA_DIR / "trader.json")
    exchange = BithumbExchange(config.BITHUMB_ACCESS_KEY, config.BITHUMB_SECRET_KEY)
    log.info("매매 엔진 시작 (확인 주기 %s초, 텔레그램 알림 %s)", config.ENGINE_TICK_SECONDS,
             "켜짐" if notify.enabled() else "꺼짐")
    last_error = None
    commands = asyncio.create_task(bot.poll(trader_store, exchange))  # 휴대폰에서 /상태, /정지
    try:
        while True:
            for job in (tick(store, exchange), trader_tick(trader_store, exchange)):
                try:
                    await job
                except Exception as exc:  # 한 번의 오류로 엔진이 멈추지 않게 한다
                    log.exception("엔진 처리 중 오류")
                    if str(exc) != last_error:  # 같은 오류는 한 번만 알린다
                        await notify.send(f"엔진 처리 중 오류: {exc}")
                    last_error = str(exc)
            await asyncio.sleep(config.ENGINE_TICK_SECONDS)
    finally:
        commands.cancel()
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
