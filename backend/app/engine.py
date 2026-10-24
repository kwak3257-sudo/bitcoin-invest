"""매매 엔진. 화면(API 서버)과 별도 프로세스로 실행한다.

    python -m app.engine
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from . import config
from .exchanges.bithumb import BithumbExchange
from .store import DcaStore
from .strategies.dca import KST, run_if_due

log = logging.getLogger("engine")


async def tick(store: DcaStore, exchange) -> None:
    if not store.load().config.enabled:
        return
    with store.edit() as state:
        run = await run_if_due(state, exchange, datetime.now(KST))
    if run is not None:
        log.info("정기 매수 실행: %s", run.message)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = DcaStore(config.DATA_DIR / "dca.json")
    exchange = BithumbExchange(config.BITHUMB_ACCESS_KEY, config.BITHUMB_SECRET_KEY)
    log.info("매매 엔진 시작 (확인 주기 %s초)", config.ENGINE_TICK_SECONDS)
    try:
        while True:
            try:
                await tick(store, exchange)
            except Exception:  # 한 번의 오류로 엔진이 멈추지 않게 한다
                log.exception("엔진 처리 중 오류")
            await asyncio.sleep(config.ENGINE_TICK_SECONDS)
    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
