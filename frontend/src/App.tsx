import { useEffect, useMemo, useState } from 'react'
import { api, type Market, type Ticker } from './api'
import { Analysis } from './components/Analysis'
import { Backtest } from './components/Backtest'
import { DcaSettings } from './components/DcaSettings'
import { PriceChart } from './components/PriceChart'
import { TickerTable } from './components/TickerTable'
import { Trader } from './components/Trader'
import { formatKrw, formatRate, trendClass } from './format'

const WATCHLIST = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-DOGE']
const REFRESH_MS = 3000

type Page = 'dashboard' | 'trader' | 'analysis' | 'backtest' | 'auto'

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [markets, setMarkets] = useState<Market[]>([])
  const [tickers, setTickers] = useState<Ticker[]>([])
  const [selected, setSelected] = useState('KRW-BTC')
  const [error, setError] = useState<string | null>(null)

  const marketMap = useMemo(() => new Map(markets.map((m) => [m.code, m])), [markets])

  useEffect(() => {
    api.markets().then(setMarkets).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .tickers(WATCHLIST)
        .then((t) => {
          if (!alive) return
          setTickers(t)
          setError(null)
        })
        .catch((e: Error) => alive && setError(e.message))
    load()
    const id = window.setInterval(load, REFRESH_MS)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [])

  const btc = tickers.find((t) => t.market === 'KRW-BTC')
  const selectedName = marketMap.get(selected)?.korean_name ?? selected

  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand">코인 투자 도우미</div>
        <button className={page === 'dashboard' ? 'active' : undefined} onClick={() => setPage('dashboard')}>
          대시보드
        </button>
        <button className={page === 'trader' ? 'active' : undefined} onClick={() => setPage('trader')}>
          단기 매매
        </button>
        <button className={page === 'analysis' ? 'active' : undefined} onClick={() => setPage('analysis')}>
          정기 매수 수익
        </button>
        <button className={page === 'backtest' ? 'active' : undefined} onClick={() => setPage('backtest')}>
          백테스트
        </button>
        <button className={page === 'auto' ? 'active' : undefined} onClick={() => setPage('auto')}>
          정기 매수 설정
        </button>
        <div className="exchange-tag">연결 거래소: 빗썸</div>
      </nav>

      <main>
        {error && <div className="banner error">{error}</div>}

        {page === 'dashboard' && (
          <>
            <header className="hero">
              <div>
                <div className="label">비트코인 현재가</div>
                <div className={`price ${btc ? trendClass(btc.change_rate) : ''}`}>
                  {btc ? formatKrw(btc.price) : '—'}
                </div>
              </div>
              {btc && (
                <div className={`change ${trendClass(btc.change_rate)}`}>
                  {formatRate(btc.change_rate)} ({Number(btc.change_price) > 0 ? '+' : ''}
                  {formatKrw(btc.change_price)})
                </div>
              )}
            </header>
            <div className="grid">
              <section className="card">
                <div className="card-head">
                  <h2>관심 코인</h2>
                  <span className="muted">{REFRESH_MS / 1000}초마다 갱신</span>
                </div>
                <TickerTable tickers={tickers} markets={marketMap} selected={selected} onSelect={setSelected} />
              </section>
              <PriceChart market={selected} title={selectedName} />
            </div>
          </>
        )}

        {page === 'trader' && <Trader markets={markets} />}
        {page === 'analysis' && <Analysis />}
        {page === 'backtest' && <Backtest markets={markets} />}
        {page === 'auto' && <DcaSettings markets={markets} />}
      </main>
    </div>
  )
}
