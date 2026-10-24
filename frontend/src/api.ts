// 백엔드 API 호출. 금액은 서버에서 문자열(Decimal)로 오므로 화면에서 숫자로 바꾼다.

export interface Ticker {
  market: string
  price: string
  change_rate: string
  change_price: string
  high: string
  low: string
  volume_24h: string
  value_24h: string
  timestamp: string
}

export interface Candle {
  market: string
  time_kst: string
  open: string
  high: string
  low: string
  close: string
  volume: string
}

export interface Market {
  code: string
  korean_name: string
  english_name: string
}

export interface DcaConfig {
  enabled: boolean
  mode: 'paper' | 'live'
  exchange: 'bithumb' | 'upbit'
  market: string
  weekday: number
  run_time: string
  krw_amount: string
  max_total_krw: string | null
  fee_rate: string
  take_profit_pct: string | null
  take_profit_sell_ratio: string
  take_profit_cooldown_hours: number
}

export interface DcaRun {
  at: string
  market: string
  side: 'buy' | 'sell'
  krw_amount: string
  volume: string
  fee_krw: string
  mode: 'paper' | 'live'
  order_id: string | null
  price: string | null
  ok: boolean
  message: string
}

export interface DcaView {
  config: DcaConfig
  summary: string
  next_run: string | null
  take_profit_price: string | null
  total_spent: string
  runs: DcaRun[]
}

export interface Analysis {
  market: string
  mode: 'paper' | 'live'
  fee_rate: string
  price: string | null
  volume: string
  avg_cost: string | null
  invested_krw: string
  cost_krw: string
  value_krw: string
  realized_pnl_krw: string
  unrealized_pnl_krw: string
  total_pnl_krw: string
  return_pct: string
  fees_krw: string
  buy_count: number
  sell_count: number
  curve: { at: string; invested: string; pnl: string }[]
  trades: DcaRun[]
}

export interface BacktestParams {
  fast: number
  slow: number
  rsi_period: number
  rsi_max: number
  stop_loss_pct: number
  take_profit_pct: number
  trend_period: number | null
}

export interface BacktestRequest {
  market: string
  interval: string
  candles: number
  params: BacktestParams
  costs: { fee_rate: number; slippage_pct: number; initial_krw: number }
}

export interface BacktestTrade {
  entry_time: string
  entry_price: number
  exit_time: string | null
  exit_price: number | null
  reason: string
  pnl_krw: number
  pnl_pct: number
  fees_krw: number
}

export interface BacktestResult {
  market: string
  interval: string
  from: string
  to: string
  candle_count: number
  initial_krw: number
  final_krw: number
  return_pct: number
  buy_hold_pct: number
  max_drawdown_pct: number
  trade_count: number
  win_rate_pct: number
  fees_krw: number
  exposure_pct: number
  trades: BacktestTrade[]
  equity: { time: string; equity: number; buy_hold: number }[]
}

export interface TraderConfig {
  enabled: boolean
  mode: 'paper' | 'live'
  market: string
  interval: '15m' | '30m' | '1h' | '4h'
  params: {
    fast: number
    slow: number
    rsi_period: number
    rsi_max: string
    stop_loss_pct: string
    take_profit_pct: string
    trend_period: number | null
  }
  budget_krw: string
  daily_loss_limit_pct: string
  fee_rate: string
}

export interface TraderTrade {
  at: string
  market: string
  side: 'buy' | 'sell'
  mode: 'paper' | 'live'
  reason: string
  price: string | null
  volume: string
  krw_amount: string
  fee_krw: string
  pnl_krw: string | null
  ok: boolean
  message: string
}

export interface TraderView {
  config: TraderConfig
  keys_ready: boolean
  telegram_ready: boolean
  price: string | null
  position: { entry_at: string; entry_price: string; volume: string; cost_krw: string } | null
  position_value_krw: string | null
  cash_krw: string
  equity_krw: string
  realized_pnl_krw: string
  total_pnl_krw: string
  return_pct: string
  today_pnl_krw: string
  daily_loss_limit_krw: string
  fees_krw: string
  trade_count: number
  win_rate_pct: number
  halted_until: string | null
  halt_reason: string | null
  stop_requested: boolean
  curve: { at: string; pnl: string }[]
  trades: TraderTrade[]
}

export interface OptimizeSummary {
  return_pct: number
  buy_hold_pct: number
  max_drawdown_pct: number
  trade_count: number
  win_rate_pct: number
  fees_krw: number
}

export interface OptimizeResult {
  tested: number
  train_from: string
  test_from: string
  to: string
  picks: { params: BacktestParams; train: OptimizeSummary; test: OptimizeSummary }[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    const message = Array.isArray(detail)
      ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join(' ')
      : detail ?? `요청 실패 (${res.status})`
    throw new Error(message)
  }
  return res.json()
}

export const api = {
  markets: () => request<Market[]>('/api/markets'),
  tickers: (markets: string[]) =>
    request<Ticker[]>(`/api/tickers?markets=${encodeURIComponent(markets.join(','))}`),
  candles: (market: string, interval: string) =>
    request<Candle[]>(`/api/candles?market=${market}&interval=${interval}&count=200`),
  backtest: (req: BacktestRequest) =>
    request<BacktestResult>('/api/backtest', { method: 'POST', body: JSON.stringify(req) }),
  optimize: (req: Omit<BacktestRequest, 'params'>) =>
    request<OptimizeResult>('/api/backtest/optimize', { method: 'POST', body: JSON.stringify(req) }),
  analysis: () => request<Analysis>('/api/analysis'),
  getTrader: () => request<TraderView>('/api/strategies/trader'),
  putTrader: (cfg: TraderConfig) =>
    request<TraderView>('/api/strategies/trader', { method: 'PUT', body: JSON.stringify(cfg) }),
  stopTrader: () => request<TraderView>('/api/strategies/trader/stop', { method: 'POST' }),
  getDca: () => request<DcaView>('/api/strategies/dca'),
  putDca: (cfg: DcaConfig) =>
    request<DcaView>('/api/strategies/dca', { method: 'PUT', body: JSON.stringify(cfg) }),
}
