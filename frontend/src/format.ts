// 원화, 등락률, KST 시간 표기

const krw = new Intl.NumberFormat('ko-KR')

export function formatKrw(value: string | number): string {
  const n = Number(value)
  return `${krw.format(Math.abs(n) >= 100 ? Math.round(n) : n)}원`
}

export function formatRate(rate: string | number): string {
  const pct = Number(rate) * 100
  return `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`
}

/** 국내 거래소 관례: 상승 빨강, 하락 파랑 */
export function trendClass(rate: string | number): string {
  const n = Number(rate)
  return n > 0 ? 'up' : n < 0 ? 'down' : 'flat'
}

/** 24시간 거래대금을 '조/억' 단위로 */
export function formatValueKrw(value: string | number): string {
  const n = Number(value)
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}조원`
  if (n >= 1e8) return `${krw.format(Math.round(n / 1e8))}억원`
  return formatKrw(n)
}

export function formatKst(iso: string): string {
  return new Date(iso).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
