import { useEffect, useRef, useState } from 'react'
import { createChart, type UTCTimestamp } from 'lightweight-charts'
import { api, type Analysis as AnalysisData } from '../api'
import { formatKrw, formatKst, trendClass } from '../format'

const REFRESH_MS = 10000

function signedKrw(v: string | number) {
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${formatKrw(n)}`
}

function Stat({ label, value, tone, sub }: { label: string; value: string; tone?: string; sub?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone ?? ''}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

function PnlChart({ curve }: { curve: AnalysisData['curve'] }) {
  const el = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!el.current || curve.length === 0) return
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      localization: { locale: 'ko-KR', priceFormatter: (p: number) => `${Math.round(p).toLocaleString('ko-KR')}원` },
      timeScale: { timeVisible: true },
    })
    // 국내 관례대로 이익은 빨강, 손실은 파랑
    const series = chart.addBaselineSeries({
      baseValue: { type: 'price', price: 0 },
      topLineColor: '#ef4444',
      topFillColor1: 'rgba(239, 68, 68, 0.28)',
      topFillColor2: 'rgba(239, 68, 68, 0.05)',
      bottomLineColor: '#3b82f6',
      bottomFillColor1: 'rgba(59, 130, 246, 0.05)',
      bottomFillColor2: 'rgba(59, 130, 246, 0.28)',
    })
    // 같은 시각 거래가 겹치면 차트가 거부하므로 1초씩 밀어 준다
    let last = 0
    series.setData(
      curve.map((c) => {
        const t = Math.max(Math.floor(Date.parse(c.at) / 1000) + 9 * 3600, last + 1)
        last = t
        return { time: t as UTCTimestamp, value: Number(c.pnl) }
      }),
    )
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [curve])

  if (curve.length === 0) return <p className="muted">아직 거래 기록이 없어요. 전략을 켜면 여기에 손익 흐름이 그려져요.</p>
  return <div ref={el} className="chart" />
}

export function Analysis() {
  const [data, setData] = useState<AnalysisData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .analysis()
        .then((d) => {
          if (!alive) return
          setData(d)
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

  if (!data) return <section className="card">{error ?? '불러오는 중…'}</section>

  const coin = data.market.replace('KRW-', '')
  const feePct = (Number(data.fee_rate) * 100).toFixed(2)

  return (
    <>
      {error && <div className="banner error">{error}</div>}
      <header className="hero">
        <div>
          <div className="label">
            총 손익 · {data.mode === 'live' ? '실거래' : '모의투자'} · 수수료 {feePct}% 반영
          </div>
          <div className={`price ${trendClass(data.total_pnl_krw)}`}>{signedKrw(data.total_pnl_krw)}</div>
        </div>
        <div className={`change ${trendClass(data.return_pct)}`}>
          {Number(data.return_pct) > 0 ? '+' : ''}
          {Number(data.return_pct).toFixed(2)}%
        </div>
      </header>

      <div className="stats">
        <Stat label="투자 원금" value={formatKrw(data.invested_krw)} sub={`매수 ${data.buy_count}회 · 매도 ${data.sell_count}회`} />
        <Stat
          label="평가 금액"
          value={formatKrw(data.value_krw)}
          sub={`${Number(data.volume).toLocaleString('ko-KR', { maximumFractionDigits: 8 })} ${coin} 보유`}
        />
        <Stat
          label="평가 손익 (미실현)"
          value={signedKrw(data.unrealized_pnl_krw)}
          tone={trendClass(data.unrealized_pnl_krw)}
          sub={data.avg_cost ? `평균 단가 ${formatKrw(data.avg_cost)}` : undefined}
        />
        <Stat label="실현 손익" value={signedKrw(data.realized_pnl_krw)} tone={trendClass(data.realized_pnl_krw)} />
        <Stat label="낸 수수료" value={formatKrw(data.fees_krw)} sub="매수·매도 합계" />
        <Stat label="현재가" value={data.price ? formatKrw(data.price) : '—'} sub={data.market} />
      </div>

      <section className="card">
        <div className="card-head">
          <h2>손익 흐름</h2>
          <span className="muted">거래 시점 가격 기준, 매도 수수료까지 뺀 금액</span>
        </div>
        <PnlChart curve={data.curve} />
      </section>

      <section className="card">
        <div className="card-head">
          <h2>거래 기록</h2>
        </div>
        {data.trades.length === 0 ? (
          <p className="muted">아직 거래 기록이 없어요.</p>
        ) : (
          <table className="ticker-table">
            <thead>
              <tr>
                <th>시각</th>
                <th>구분</th>
                <th className="num">가격</th>
                <th className="num">금액</th>
                <th className="num hide-sm">수수료</th>
              </tr>
            </thead>
            <tbody>
              {data.trades.map((t) => (
                <tr key={`${t.at}-${t.side}`}>
                  <td>{formatKst(t.at)}</td>
                  <td className={t.side === 'buy' ? 'up' : 'down'}>
                    {t.side === 'buy' ? '매수' : '매도'}
                    {t.mode === 'paper' && <span className="muted"> (모의)</span>}
                  </td>
                  <td className="num">{t.price ? formatKrw(t.price) : '—'}</td>
                  <td className="num">{formatKrw(t.krw_amount)}</td>
                  <td className="num hide-sm">{formatKrw(t.fee_krw)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
