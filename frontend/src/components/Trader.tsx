import { useEffect, useState } from 'react'
import { api, withTelegramCode, type Market, type RecommendRow, type TraderConfig, type TraderView } from '../api'
import { describeParams, formatKrw, formatKst, trendClass } from '../format'

const REFRESH_MS = 5000
const INTERVALS = [
  { value: '15m', label: '15분봉' },
  { value: '30m', label: '30분봉' },
  { value: '1h', label: '1시간봉' },
  { value: '4h', label: '4시간봉' },
  { value: '1d', label: '일봉' },
] as const

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

export function Trader({ markets }: { markets: Market[] }) {
  const [view, setView] = useState<TraderView | null>(null)
  const [draft, setDraft] = useState<TraderConfig | null>(null)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [rows, setRows] = useState<RecommendRow[] | null>(null)
  const [finding, setFinding] = useState(false)

  useEffect(() => {
    let alive = true
    let first = true
    const load = () =>
      api
        .getTrader()
        .then((v) => {
          if (!alive) return
          setView(v)
          // 설정 폼은 처음 한 번만 채운다. 그 뒤로는 입력 중인 값을 덮지 않는다
          if (first) setDraft(v.config)
          first = false
        })
        .catch((e: Error) => alive && setMessage({ ok: false, text: e.message }))
    load()
    const id = window.setInterval(load, REFRESH_MS)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [])

  if (!view || !draft) return <section className="card">{message?.text ?? '불러오는 중…'}</section>

  const set = <K extends keyof TraderConfig>(key: K, value: TraderConfig[K]) => setDraft({ ...draft, [key]: value })
  const setParam = (key: keyof TraderConfig['params'], value: string) =>
    setDraft({ ...draft, params: { ...draft.params, [key]: value } })

  async function save(next: TraderConfig) {
    if (next.mode === 'live' && next.enabled && !confirm('실제 돈으로 사고팝니다. 계속할까요?')) return
    setBusy(true)
    try {
      const v = await withTelegramCode((code) => api.putTrader(next, code))
      setView(v)
      setDraft(v.config)
      setMessage({ ok: true, text: '저장했습니다.' })
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function findBest(applyTop = false) {
    if (!draft) return
    setFinding(true)
    setMessage(null)
    try {
      const found = (await api.recommend(draft.market, draft.fee_rate)).rows
      setRows(found)
      if (applyTop) {
        // 검증 기간에 실제로 거래해서 수익을 낸 설정만 넣는다
        const best = found.find((r) => r.test.trade_count > 0 && r.test.return_pct > 0)
        if (best) applyPaper(best)
        else setMessage({ ok: false, text: '검증 기간에 수익을 낸 설정이 없어 바꾸지 않았어요.' })
      }
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    } finally {
      setFinding(false)
    }
  }

  function applyPaper(row: RecommendRow) {
    if (!draft) return
    // 추천 설정은 언제나 모의투자로 먼저 넣는다. 실거래는 사용자가 직접 바꾼다
    save({
      ...draft,
      mode: 'paper',
      enabled: true,
      interval: row.interval,
      params: { ...draft.params, ...(row.params as unknown as TraderConfig['params']) },
    })
  }

  async function emergencyStop() {
    if (!confirm('보유 중인 코인을 시장가로 모두 팔고 단기 매매를 끕니다. 계속할까요?')) return
    setBusy(true)
    try {
      const v = await api.stopTrader()
      setView(v)
      setDraft((d) => d && { ...d, enabled: v.config.enabled })
      setMessage({
        ok: true,
        text: v.stop_requested ? '정지 요청을 보냈어요. 엔진이 곧 팔고 멈춥니다.' : '멈췄습니다.',
      })
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const cfg = view.config
  const breakout = draft.params.strategy === 'breakout'
  const coin = cfg.market.replace('KRW-', '')
  const pos = view.position
  const status = view.stop_requested
    ? '정지 중…'
    : view.halted_until
      ? `쉬는 중 (${formatKst(view.halted_until)}까지)`
      : cfg.enabled
        ? '운영 중'
        : '꺼짐'

  return (
    <>
      {view.halt_reason && <div className="banner">{view.halt_reason}</div>}
      <header className="hero">
        <div>
          <div className="label">
            단기 매매 · {cfg.mode === 'live' ? '실거래' : '모의투자'} · {status}
          </div>
          <div className={`price ${trendClass(view.total_pnl_krw)}`}>{signedKrw(view.total_pnl_krw)}</div>
        </div>
        <div className={`change ${trendClass(view.return_pct)}`}>
          {Number(view.return_pct) > 0 ? '+' : ''}
          {Number(view.return_pct).toFixed(2)}%
        </div>
        <button className="danger" onClick={emergencyStop} disabled={busy || (!cfg.enabled && !pos)}>
          긴급 정지
        </button>
      </header>

      <div className="stats">
        <Stat label="운용 자산" value={formatKrw(view.equity_krw)} sub={`운용 금액 ${formatKrw(cfg.budget_krw)}`} />
        <Stat
          label="오늘 손익"
          value={signedKrw(view.today_pnl_krw)}
          tone={trendClass(view.today_pnl_krw)}
          sub={`하루 손실 한도 -${formatKrw(view.daily_loss_limit_krw)}`}
        />
        <Stat
          label="보유"
          value={pos ? formatKrw(view.position_value_krw ?? 0) : '없음'}
          sub={
            pos
              ? `${Number(pos.volume).toLocaleString('ko-KR', { maximumFractionDigits: 8 })} ${coin} · 매수가 ${formatKrw(pos.entry_price)}`
              : `현금 ${formatKrw(view.cash_krw)}`
          }
        />
        <Stat
          label="거래 · 승률"
          value={`${view.trade_count}회 · ${view.win_rate_pct.toFixed(0)}%`}
          sub={`실현 손익 ${signedKrw(view.realized_pnl_krw)}`}
        />
        <Stat label="낸 수수료" value={formatKrw(view.fees_krw)} sub="매수·매도 합계" />
      </div>

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h2>전략 자동 찾기</h2>
          <button className="link" onClick={() => findBest()} disabled={finding || busy}>
            {rows ? '다시 찾기' : '목록만 보기'}
          </button>
        </div>
        <div className="form-actions" style={{ marginBottom: 12 }}>
          <button onClick={() => findBest(true)} disabled={finding || busy}>
            {finding ? '두 전략 × 4시간봉·일봉 계산 중… (1분 정도)' : '가장 좋은 설정 찾아서 모의투자에 넣기'}
          </button>
          {message && <span className={message.ok ? 'ok' : 'error'}>{message.text}</span>}
        </div>
        <p className="summary">
          이동평균 교차와 변동성 돌파를 4시간봉·일봉 과거 3000개 봉으로 수백 가지씩 돌려, 앞 70% 기간에서 고른 설정을 뒤
          30% 기간에서 검증한 순서로 보여 줘요. 현재 수수료율 {(Number(draft.fee_rate) * 100).toFixed(2)}%로 계산해요.
        </p>
        {rows && (
          <table className="ticker-table">
            <thead>
              <tr>
                <th>봉</th>
                <th>설정</th>
                <th className="num">검증 기간</th>
                <th className="num hide-sm">그냥 보유</th>
                <th className="num hide-sm">거래</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 8).map((r, i) => (
                <tr key={i}>
                  <td>{r.interval === '1d' ? '일봉' : '4시간봉'}</td>
                  <td>{describeParams(r.params)}</td>
                  <td className={`num ${trendClass(r.test.return_pct)}`}>
                    {r.test.return_pct > 0 ? '+' : ''}
                    {r.test.return_pct.toFixed(2)}%
                  </td>
                  <td className="num hide-sm">
                    {r.test.buy_hold_pct > 0 ? '+' : ''}
                    {r.test.buy_hold_pct.toFixed(2)}%
                  </td>
                  <td className="num hide-sm">{r.test.trade_count}회</td>
                  <td className="num">
                    <button className="link" onClick={() => applyPaper(r)} disabled={busy}>
                      모의투자에 적용
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>단기 매매 설정</h2>
          <label className="switch">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => save({ ...draft, enabled: e.target.checked })}
              disabled={busy}
            />
            <span>{draft.enabled ? '켜짐' : '꺼짐'}</span>
          </label>
        </div>
        <p className="summary">
          {breakout
            ? '봉이 시작될 때 목표가(시가 + k × 직전 봉 변동폭)를 정하고, 가격이 넘으면 운용 금액 전부로 삽니다. 다음 봉이 시작되면 팝니다.'
            : '짧은 이동평균이 긴 이동평균을 위로 뚫고 RSI가 과열이 아니면 운용 금액 전부로 삽니다. 반대로 꺾이거나 손절·익절가에 닿으면 팝니다.'}{' '}
          백테스트에서 검증한 값을 넣으세요.
          <br />
          {view.keys_ready ? '빗썸 API 키 등록됨' : '빗썸 API 키 없음 (모의투자만 가능)'} · 텔레그램 알림{' '}
          {view.telegram_ready ? '켜짐' : '꺼짐'}
        </p>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault()
            save(draft)
          }}
        >
          <label>
            코인
            <select value={draft.market} onChange={(e) => set('market', e.target.value)}>
              {(markets.length
                ? markets
                : [
                    {
                      code: draft.market,
                      korean_name: draft.market,
                      english_name: '',
                    },
                  ]
              ).map((m) => (
                <option key={m.code} value={m.code}>
                  {m.korean_name} ({m.code.replace('KRW-', '')})
                </option>
              ))}
            </select>
          </label>
          <label>
            봉 간격
            <select
              value={draft.interval}
              onChange={(e) => set('interval', e.target.value as TraderConfig['interval'])}
            >
              {INTERVALS.map((i) => (
                <option key={i.value} value={i.value}>
                  {i.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            실행 방식
            <select value={draft.mode} onChange={(e) => set('mode', e.target.value as TraderConfig['mode'])}>
              <option value="paper">모의투자 (실제 주문 없음)</option>
              <option value="live">실거래</option>
            </select>
          </label>
          <label>
            운용 금액 (원)
            <input
              type="number"
              min={10000}
              step={10000}
              value={Number(draft.budget_krw)}
              onChange={(e) => set('budget_krw', e.target.value)}
            />
          </label>
          <label>
            하루 손실 한도 (운용 금액의 %)
            <input
              type="number"
              min={0.5}
              step={0.5}
              value={Number(draft.daily_loss_limit_pct)}
              onChange={(e) => set('daily_loss_limit_pct', e.target.value)}
            />
          </label>
          <label>
            수수료율 (%)
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={Number((Number(draft.fee_rate) * 100).toFixed(4))}
              onChange={(e) => set('fee_rate', String(Number(e.target.value) / 100))}
            />
          </label>
          <label>
            전략
            <select
              value={draft.params.strategy}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  params: {
                    ...draft.params,
                    strategy: e.target.value as TraderConfig['params']['strategy'],
                    trend_period: null,
                  },
                })
              }
            >
              <option value="ma_cross">이동평균 교차</option>
              <option value="breakout">변동성 돌파</option>
            </select>
          </label>
          {breakout ? (
            <label>
              돌파 계수 k
              <input
                type="number"
                min={0.05}
                step={0.05}
                value={Number(draft.params.k)}
                onChange={(e) => setParam('k', e.target.value)}
              />
            </label>
          ) : (
            <>
              <label>
                짧은 이동평균 (봉)
                <input
                  type="number"
                  min={2}
                  value={draft.params.fast}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      params: { ...draft.params, fast: Number(e.target.value) },
                    })
                  }
                />
              </label>
              <label>
                긴 이동평균 (봉)
                <input
                  type="number"
                  min={3}
                  value={draft.params.slow}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      params: { ...draft.params, slow: Number(e.target.value) },
                    })
                  }
                />
              </label>
              <label>
                RSI 상한
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={Number(draft.params.rsi_max)}
                  onChange={(e) => setParam('rsi_max', e.target.value)}
                />
              </label>
            </>
          )}
          <label>
            손절 (%)
            <input
              type="number"
              min={0.1}
              step={0.1}
              value={Number(draft.params.stop_loss_pct)}
              onChange={(e) => setParam('stop_loss_pct', e.target.value)}
            />
          </label>
          {!breakout && (
            <label>
              익절 (%)
              <input
                type="number"
                min={0.1}
                step={0.1}
                value={Number(draft.params.take_profit_pct)}
                onChange={(e) => setParam('take_profit_pct', e.target.value)}
              />
            </label>
          )}
          <label>
            추세 필터
            <select
              value={draft.params.trend_period ?? ''}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  params: { ...draft.params, trend_period: e.target.value ? Number(e.target.value) : null },
                })
              }
            >
              <option value="">끔</option>
              {(breakout ? [3, 5, 10, 20] : [50, 100, 200]).map((n) => (
                <option key={n} value={n}>
                  {n}봉 이동평균 위에서만
                </option>
              ))}
            </select>
          </label>
          <div className="form-actions">
            <button type="submit" disabled={busy}>
              {busy ? '저장 중…' : '설정 저장'}
            </button>
            {message && <span className={message.ok ? 'ok' : 'error'}>{message.text}</span>}
          </div>
        </form>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-head">
          <h2>거래 기록</h2>
          <span className="muted">{REFRESH_MS / 1000}초마다 갱신</span>
        </div>
        {view.trades.length === 0 ? (
          <p className="muted">아직 거래가 없어요. 켜 두면 신호가 나올 때 여기에 기록돼요.</p>
        ) : (
          <table className="ticker-table">
            <thead>
              <tr>
                <th>시각</th>
                <th>구분</th>
                <th className="hide-sm">이유</th>
                <th className="num">가격</th>
                <th className="num">손익</th>
              </tr>
            </thead>
            <tbody>
              {view.trades.map((t) => (
                <tr key={`${t.at}-${t.side}`} className={t.ok ? undefined : 'error'}>
                  <td>{formatKst(t.at)}</td>
                  <td className={t.ok ? (t.side === 'buy' ? 'up' : 'down') : 'error'}>
                    {t.side === 'buy' ? '매수' : '매도'}
                    {!t.ok && ' 실패'}
                    {t.mode === 'paper' && <span className="muted"> (모의)</span>}
                  </td>
                  <td className="hide-sm">{t.ok ? t.reason : t.message}</td>
                  <td className="num">{t.price ? formatKrw(t.price) : '—'}</td>
                  <td className={`num ${t.pnl_krw ? trendClass(t.pnl_krw) : ''}`}>
                    {t.pnl_krw ? signedKrw(t.pnl_krw) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
