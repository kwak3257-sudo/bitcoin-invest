import { useEffect, useRef, useState } from 'react'
import { createChart, type UTCTimestamp } from 'lightweight-charts'
import { api } from '../api'

const INTERVALS = [
  { value: '1m', label: '1분' },
  { value: '15m', label: '15분' },
  { value: '1h', label: '1시간' },
  { value: '4h', label: '4시간' },
  { value: '1d', label: '일' },
  { value: '1w', label: '주' },
]

// 100원 이상은 원 단위, 그 미만 코인은 소수점 둘째 자리까지
const formatPrice = (p: number) =>
  p >= 100 ? Math.round(p).toLocaleString('ko-KR') : p.toLocaleString('ko-KR', { maximumFractionDigits: 2 })

// 캔들 시각은 KST 문자열로 온다. UTC로 읽혀야 차트 눈금이 KST 그대로 보인다.
const toChartTime = (kst: string) => (Date.parse(`${kst}Z`) / 1000) as UTCTimestamp

export function PriceChart({ market, title }: { market: string; title: string }) {
  const el = useRef<HTMLDivElement>(null)
  const [interval, setInterval] = useState('1d')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!el.current) return
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      localization: { locale: 'ko-KR', priceFormatter: formatPrice },
      timeScale: { timeVisible: interval !== '1d' && interval !== '1w' },
    })
    const series = chart.addCandlestickSeries({
      upColor: '#ef4444',
      borderUpColor: '#ef4444',
      wickUpColor: '#ef4444',
      downColor: '#3b82f6',
      borderDownColor: '#3b82f6',
      wickDownColor: '#3b82f6',
    })
    let cancelled = false
    api
      .candles(market, interval)
      .then((rows) => {
        if (cancelled) return
        series.setData(
          rows.map((c) => ({
            time: toChartTime(c.time_kst),
            open: Number(c.open),
            high: Number(c.high),
            low: Number(c.low),
            close: Number(c.close),
          })),
        )
        chart.timeScale().fitContent()
        setError(null)
      })
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
      chart.remove()
    }
  }, [market, interval])

  return (
    <section className="card">
      <div className="card-head">
        <h2>{title} 차트</h2>
        <div className="segmented">
          {INTERVALS.map((i) => (
            <button
              key={i.value}
              className={i.value === interval ? 'active' : undefined}
              onClick={() => setInterval(i.value)}
            >
              {i.label}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      <div ref={el} className="chart" />
    </section>
  )
}
