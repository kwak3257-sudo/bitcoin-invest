import type { Market, Ticker } from '../api'
import { formatKrw, formatRate, formatValueKrw, trendClass } from '../format'

interface Props {
  tickers: Ticker[]
  markets: Map<string, Market>
  selected: string
  onSelect: (market: string) => void
}

export function TickerTable({ tickers, markets, selected, onSelect }: Props) {
  return (
    <table className="ticker-table">
      <thead>
        <tr>
          <th>코인</th>
          <th className="num">현재가</th>
          <th className="num">전일 대비</th>
          <th className="num hide-sm" title="최근 24시간 거래대금">거래대금</th>
        </tr>
      </thead>
      <tbody>
        {tickers.map((t) => {
          const m = markets.get(t.market)
          return (
            <tr
              key={t.market}
              className={t.market === selected ? 'selected' : undefined}
              onClick={() => onSelect(t.market)}
            >
              <td>
                <div className="coin-name">{m?.korean_name ?? t.market}</div>
                <div className="coin-code">{t.market.replace('KRW-', '')}/KRW</div>
              </td>
              <td className={`num ${trendClass(t.change_rate)}`}>{formatKrw(t.price)}</td>
              <td className={`num ${trendClass(t.change_rate)}`}>{formatRate(t.change_rate)}</td>
              <td className="num hide-sm">{formatValueKrw(t.value_24h)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
