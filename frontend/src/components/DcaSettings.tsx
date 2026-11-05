import { useEffect, useState } from 'react'
import { api, withTelegramCode, type DcaConfig, type DcaView, type Market } from '../api'
import { formatKrw, formatKst } from '../format'

const WEEKDAYS = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']

export function DcaSettings({ markets }: { markets: Market[] }) {
  const [view, setView] = useState<DcaView | null>(null)
  const [draft, setDraft] = useState<DcaConfig | null>(null)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .getDca()
      .then((v) => {
        setView(v)
        setDraft(v.config)
      })
      .catch((e: Error) => setMessage({ ok: false, text: e.message }))
  }, [])

  if (!draft) return <section className="card">{message?.text ?? '불러오는 중…'}</section>

  const set = <K extends keyof DcaConfig>(key: K, value: DcaConfig[K]) =>
    setDraft({ ...draft, [key]: value })

  async function save(next: DcaConfig) {
    if (next.mode === 'live' && next.enabled && !confirm('실제 돈으로 매수합니다. 계속할까요?')) return
    setSaving(true)
    try {
      const v = await withTelegramCode((code) => api.putDca(next, code))
      setView(v)
      setDraft(v.config)
      setMessage({ ok: true, text: '저장했습니다.' })
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>주간 정기 매수 + 목표 수익 매도</h2>
        <label className="switch">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(e) => save({ ...draft, enabled: e.target.checked })}
            disabled={saving}
          />
          <span>{draft.enabled ? '켜짐' : '꺼짐'}</span>
        </label>
      </div>

      {view && (
        <p className="summary">
          {view.summary}
          {view.next_run && <> · 다음 실행 {formatKst(view.next_run)}</>}
          <br />
          누적 매수 {formatKrw(view.total_spent)}
          {view.take_profit_price && <> · 목표 매도가 {formatKrw(view.take_profit_price)} 이상</>}
        </p>
      )}

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
            {(markets.length ? markets : [{ code: draft.market, korean_name: draft.market, english_name: '' }]).map(
              (m) => (
                <option key={m.code} value={m.code}>
                  {m.korean_name} ({m.code.replace('KRW-', '')})
                </option>
              ),
            )}
          </select>
        </label>
        <label>
          요일
          <select value={draft.weekday} onChange={(e) => set('weekday', Number(e.target.value))}>
            {WEEKDAYS.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <label>
          시각 (한국 시간)
          <input type="time" value={draft.run_time.slice(0, 5)} onChange={(e) => set('run_time', e.target.value)} />
        </label>
        <label>
          1회 매수 금액 (원)
          <input
            type="number"
            min={5000}
            step={1000}
            value={Number(draft.krw_amount)}
            onChange={(e) => set('krw_amount', e.target.value)}
          />
        </label>
        <label>
          누적 매수 한도 (원, 비우면 없음)
          <input
            type="number"
            min={0}
            step={10000}
            value={draft.max_total_krw === null ? '' : Number(draft.max_total_krw)}
            onChange={(e) => set('max_total_krw', e.target.value === '' ? null : e.target.value)}
          />
        </label>
        <label>
          실행 방식
          <select value={draft.mode} onChange={(e) => set('mode', e.target.value as DcaConfig['mode'])}>
            <option value="paper">모의투자 (실제 주문 없음)</option>
            <option value="live">실거래</option>
          </select>
        </label>
        <label>
          수수료율 (%)
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={Number(draft.fee_rate) * 100}
            onChange={(e) => set('fee_rate', String(Number(e.target.value) / 100))}
          />
        </label>
        <label>
          목표 수익률 (%, 수수료 제외 · 비우면 매도 안 함)
          <input
            type="number"
            min={0.1}
            step={0.1}
            value={draft.take_profit_pct === null ? '' : Number(draft.take_profit_pct)}
            onChange={(e) => set('take_profit_pct', e.target.value === '' ? null : e.target.value)}
          />
        </label>
        <label>
          목표 도달 시 매도 비율
          <select
            value={Number(draft.take_profit_sell_ratio)}
            onChange={(e) => set('take_profit_sell_ratio', e.target.value)}
          >
            {[0.25, 0.5, 0.75, 1].map((r) => (
              <option key={r} value={r}>
                보유량의 {r * 100}%
              </option>
            ))}
          </select>
        </label>
        <div className="form-actions">
          <button type="submit" disabled={saving}>
            {saving ? '저장 중…' : '설정 저장'}
          </button>
          {message && <span className={message.ok ? 'ok' : 'error'}>{message.text}</span>}
        </div>
      </form>

      {view && view.runs.length > 0 && (
        <>
          <h3>최근 실행 기록</h3>
          <ul className="runs">
            {view.runs.map((r) => (
              <li key={r.at} className={r.ok ? undefined : 'error'}>
                {formatKst(r.at)} · {r.side === 'sell' ? '매도' : '매수'} · {r.mode === 'live' ? '실거래' : '모의'} ·{' '}
                {formatKrw(r.krw_amount)} · {r.message}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
