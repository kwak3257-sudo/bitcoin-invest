import { useEffect, useRef, useState } from 'react'
import { createChart, type UTCTimestamp } from 'lightweight-charts'
import {
  api,
  type BacktestParams,
  type BacktestRequest,
  type BacktestResult,
  type Market,
  type OptimizeResult,
} from '../api'
import { formatKrw, formatKst, trendClass } from '../format'

const INTERVALS = [
  { value: '15m', label: '15분봉' },
  { value: '30m', label: '30분봉' },
  { value: '1h', label: '1시간봉' },
  { value: '4h', label: '4시간봉' },
  { value: '1d', label: '일봉' },
]

const DEFAULT: BacktestRequest = {
  market: 'KRW-BTC',
  interval: '1h',
  candles: 1000,
  params: {
    fast: 9,
    slow: 26,
    rsi_period: 14,
    rsi_max: 70,
    stop_loss_pct: 2,
    take_profit_pct: 4,
    trend_period: null,
    strategy: 'ma_cross',
    k: 0.5,
  },
  costs: { fee_rate: 0.0025, slippage_pct: 0.05, initial_krw: 100000 },
}

function describe(p: BacktestParams) {
  const trend = p.trend_period ? ` · 추세 ${p.trend_period}` : ''
  const stop = Number(p.stop_loss_pct) >= 50 ? '손절 없음' : `손절 ${Number(p.stop_loss_pct)}%`
  if (p.strategy === 'breakout') return `돌파 k ${Number(p.k)}${trend} · ${stop}`
  return `${p.fast}/${p.slow}봉${trend} · ${stop} · 익절 ${Number(p.take_profit_pct)}%`
}

const pct = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
// 백엔드 시각은 KST 문자열(시간대 없음)이라 UTC로 읽혀야 차트에 KST 그대로 보인다
const toChartTime = (kst: string) => (Date.parse(`${kst}Z`) / 1000) as UTCTimestamp

function EquityChart({ equity }: { equity: BacktestResult['equity'] }) {
  const el = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!el.current) return
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      localization: { locale: 'ko-KR', priceFormatter: (p: number) => `${Math.round(p).toLocaleString('ko-KR')}원` },
      timeScale: { timeVisible: true },
    })
    const strategy = chart.addLineSeries({ color: '#f59e0b', lineWidth: 2, title: '전략' })
    const hold = chart.addLineSeries({ color: '#64748b', lineWidth: 1, title: '그냥 보유' })
    strategy.setData(equity.map((e) => ({ time: toChartTime(e.time), value: e.equity })))
    hold.setData(equity.map((e) => ({ time: toChartTime(e.time), value: e.buy_hold })))
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [equity])
  return <div ref={el} className="chart" />
}

function NumberField({
  label,
  value,
  onChange,
  step = 1,
  min,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  step?: number
  min?: number
}) {
  return (
    <label>
      {label}
      <input type="number" value={value} step={step} min={min} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}

export function Backtest({ markets }: { markets: Market[] }) {
  const [req, setReq] = useState<BacktestRequest>(DEFAULT)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [opt, setOpt] = useState<OptimizeResult | null>(null)
  const [optimizing, setOptimizing] = useState(false)

  const setParam = (k: keyof BacktestRequest['params'], v: number) =>
    setReq({ ...req, params: { ...req.params, [k]: v } })
  const setCost = (k: keyof BacktestRequest['costs'], v: number) => setReq({ ...req, costs: { ...req.costs, [k]: v } })

  async function run(next: BacktestRequest = req) {
    setRunning(true)
    setError(null)
    try {
      setResult(await api.backtest(next))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  async function runOptimize() {
    setOptimizing(true)
    setError(null)
    try {
      setOpt(
        await api.optimize({
          market: req.market,
          interval: req.interval,
          candles: req.candles,
          costs: req.costs,
          strategy: req.params.strategy,
        }),
      )
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setOptimizing(false)
    }
  }

  function apply(params: BacktestParams) {
    // 서버는 소수 값을 문자열로 보내므로 숫자로 바꿔 폼에 넣는다
    const next = {
      ...req,
      params: {
        ...req.params,
        fast: Number(params.fast),
        slow: Number(params.slow),
        stop_loss_pct: Number(params.stop_loss_pct),
        take_profit_pct: Number(params.take_profit_pct),
        trend_period: params.trend_period,
        strategy: params.strategy,
        k: Number(params.k),
      },
    }
    setReq(next)
    run(next)
  }

  const isBreakout = req.params.strategy === 'breakout'
  const beatsHold = result && result.return_pct > result.buy_hold_pct

  return (
    <>
      <section className="card">
        <div className="card-head">
          <h2>단기 매매 백테스트</h2>
          <span className="muted">이동평균 교차 + RSI, 손절·익절 · 수수료와 슬리피지 반영</span>
        </div>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault()
            run()
          }}
        >
          <label>
            코인
            <select value={req.market} onChange={(e) => setReq({ ...req, market: e.target.value })}>
              {(markets.length ? markets : [{ code: 'KRW-BTC', korean_name: '비트코인', english_name: '' }]).map(
                (m) => (
                  <option key={m.code} value={m.code}>
                    {m.korean_name} ({m.code.replace('KRW-', '')})
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            봉 간격
            <select value={req.interval} onChange={(e) => setReq({ ...req, interval: e.target.value })}>
              {INTERVALS.map((i) => (
                <option key={i.value} value={i.value}>
                  {i.label}
                </option>
              ))}
            </select>
          </label>
          <NumberField
            label="기간 (봉 개수, 최대 3000)"
            value={req.candles}
            step={50}
            min={50}
            onChange={(v) => setReq({ ...req, candles: v })}
          />
          <NumberField
            label="시작 금액 (원)"
            value={req.costs.initial_krw}
            step={10000}
            min={10000}
            onChange={(v) => setCost('initial_krw', v)}
          />
          <label>
            전략
            <select
              value={req.params.strategy}
              onChange={(e) =>
                setReq({
                  ...req,
                  params: { ...req.params, strategy: e.target.value as BacktestParams['strategy'], trend_period: null },
                })
              }
            >
              <option value="ma_cross">이동평균 교차</option>
              <option value="breakout">변동성 돌파</option>
            </select>
          </label>
          {isBreakout ? (
            <NumberField
              label="돌파 계수 k (직전 봉 변동폭의 몇 배)"
              value={req.params.k}
              step={0.05}
              min={0.05}
              onChange={(v) => setParam('k', v)}
            />
          ) : (
            <>
              <NumberField
                label="짧은 이동평균 (봉)"
                value={req.params.fast}
                min={2}
                onChange={(v) => setParam('fast', v)}
              />
              <NumberField
                label="긴 이동평균 (봉)"
                value={req.params.slow}
                min={3}
                onChange={(v) => setParam('slow', v)}
              />
              <NumberField
                label="RSI 상한 (이보다 높으면 진입 안 함)"
                value={req.params.rsi_max}
                min={1}
                onChange={(v) => setParam('rsi_max', v)}
              />
            </>
          )}
          <NumberField
            label="손절 (%)"
            value={req.params.stop_loss_pct}
            step={0.1}
            min={0.1}
            onChange={(v) => setParam('stop_loss_pct', v)}
          />
          {!isBreakout && (
            <NumberField
              label="익절 (%)"
              value={req.params.take_profit_pct}
              step={0.1}
              min={0.1}
              onChange={(v) => setParam('take_profit_pct', v)}
            />
          )}
          <label>
            추세 필터 (큰 흐름이 오를 때만 매수)
            <select
              value={req.params.trend_period ?? ''}
              onChange={(e) =>
                setReq({
                  ...req,
                  params: { ...req.params, trend_period: e.target.value ? Number(e.target.value) : null },
                })
              }
            >
              <option value="">끔</option>
              {(isBreakout ? [3, 5, 10, 20] : [50, 100, 200]).map((n) => (
                <option key={n} value={n}>
                  {n}봉 이동평균 위에서만
                </option>
              ))}
            </select>
          </label>
          <NumberField
            label="수수료율 (%)"
            value={Number((req.costs.fee_rate * 100).toFixed(4))}
            step={0.01}
            min={0}
            onChange={(v) => setCost('fee_rate', v / 100)}
          />
          <NumberField
            label="슬리피지 (%)"
            value={req.costs.slippage_pct}
            step={0.01}
            min={0}
            onChange={(v) => setCost('slippage_pct', v)}
          />
          <div className="form-actions">
            <button type="submit" disabled={running || optimizing}>
              {running ? '계산 중…' : '백테스트 실행'}
            </button>
            <button type="button" className="secondary" onClick={runOptimize} disabled={running || optimizing}>
              {optimizing ? '수백 가지 설정 계산 중…' : '자동 최적화'}
            </button>
            {error && <span className="error">{error}</span>}
          </div>
        </form>
      </section>

      {opt && (
        <section className="card" style={{ marginTop: 16 }}>
          <div className="card-head">
            <h2>자동 최적화 결과</h2>
            <span className="muted">
              {opt.tested}가지 설정 비교 · 고른 기간 {formatKst(opt.train_from)}~ · 검증 기간 {formatKst(opt.test_from)}
              ~
            </span>
          </div>
          <p className="summary">
            앞 70% 기간에서 수익이 가장 좋았던 설정을, 고를 때 쓰지 않은 뒤 30% 기간에 다시 돌린 결과예요. 검증
            기간에서도 수익이 나고 "그냥 보유"보다 나아야 믿을 만해요.
          </p>
          <table className="ticker-table">
            <thead>
              <tr>
                <th>설정</th>
                <th className="num">고른 기간</th>
                <th className="num">검증 기간</th>
                <th className="num hide-sm">검증 · 보유</th>
                <th className="num hide-sm">검증 거래</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {opt.picks.map((pk, i) => (
                <tr key={i}>
                  <td>{describe(pk.params)}</td>
                  <td className={`num ${trendClass(pk.train.return_pct)}`}>{pct(pk.train.return_pct)}</td>
                  <td className={`num ${trendClass(pk.test.return_pct)}`}>{pct(pk.test.return_pct)}</td>
                  <td className="num hide-sm">{pct(pk.test.buy_hold_pct)}</td>
                  <td className="num hide-sm">
                    {pk.test.trade_count}회 · {pk.test.win_rate_pct.toFixed(0)}%
                  </td>
                  <td className="num">
                    <button className="link" onClick={() => apply(pk.params)} disabled={running}>
                      적용
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {result && (
        <>
          <header className="hero" style={{ marginTop: 20 }}>
            <div>
              <div className="label">
                {formatKst(result.from)} ~ {formatKst(result.to)} · 캔들 {result.candle_count}개
              </div>
              <div className={`price ${trendClass(result.return_pct)}`}>{pct(result.return_pct)}</div>
            </div>
            <div className={`change ${beatsHold ? 'up' : 'down'}`}>
              그냥 보유 {pct(result.buy_hold_pct)} 대비 {beatsHold ? '우세' : '열세'}
            </div>
          </header>
          <div className="stats">
            <div className="stat">
              <div className="stat-label">최종 금액</div>
              <div className="stat-value">{formatKrw(result.final_krw)}</div>
              <div className="stat-sub">시작 {formatKrw(result.initial_krw)}</div>
            </div>
            <div className="stat">
              <div className="stat-label">거래 횟수 · 승률</div>
              <div className="stat-value">
                {result.trade_count}회 · {result.win_rate_pct.toFixed(0)}%
              </div>
              <div className="stat-sub">보유 시간 비율 {result.exposure_pct.toFixed(0)}%</div>
            </div>
            <div className="stat">
              <div className="stat-label">최대 낙폭</div>
              <div className="stat-value down">-{result.max_drawdown_pct.toFixed(2)}%</div>
              <div className="stat-sub">고점 대비 가장 크게 떨어진 정도</div>
            </div>
            <div className="stat">
              <div className="stat-label">낸 수수료</div>
              <div className="stat-value">{formatKrw(result.fees_krw)}</div>
              <div className="stat-sub">시작 금액의 {((result.fees_krw / result.initial_krw) * 100).toFixed(2)}%</div>
            </div>
          </div>
          <section className="card">
            <div className="card-head">
              <h2>자산 흐름</h2>
              <span className="muted">주황: 전략 · 회색: 처음에 사서 그냥 보유</span>
            </div>
            <EquityChart equity={result.equity} />
          </section>
          <section className="card">
            <div className="card-head">
              <h2>거래 내역</h2>
            </div>
            {result.trades.length === 0 ? (
              <p className="muted">이 기간에는 진입 신호가 없었어요.</p>
            ) : (
              <table className="ticker-table">
                <thead>
                  <tr>
                    <th>진입</th>
                    <th className="hide-sm">청산</th>
                    <th>이유</th>
                    <th className="num">손익</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.slice(0, 100).map((t) => (
                    <tr key={t.entry_time}>
                      <td>{formatKst(t.entry_time)}</td>
                      <td className="hide-sm">{t.exit_time ? formatKst(t.exit_time) : '—'}</td>
                      <td>{t.reason}</td>
                      <td className={`num ${trendClass(t.pnl_krw)}`}>
                        {pct(t.pnl_pct)} ({t.pnl_krw > 0 ? '+' : ''}
                        {formatKrw(t.pnl_krw)})
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </>
  )
}
