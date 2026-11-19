import { useEffect, useState } from 'react';
import { api } from '../api';
import { loadCatalog } from '../catalog';
import { int } from '../format';
import { loadWorkspace, saveWorkspace } from '../workspace';

type Series = {
  id: string;
  symbol: string;
  interval: string;
  start: string | null;
  end: string | null;
  bars: number;
  gapCount: number;
  gaps: Array<{ after: string; before: string; missingBars: number }>;
  minQty: number | null;
  lotStep: number | null;
  tickSize: number | null;
  minNotional: number | null;
  status: string;
  progressBars: number;
  error: string | null;
  sliceBars?: number | null;
};

export function DataScreen() {
  const workspace = loadWorkspace();
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [timeframe, setTimeframe] = useState('5m');
  const [start, setStart] = useState(workspace.from);
  const [end, setEnd] = useState(workspace.to);
  const [intervals, setIntervals] = useState<string[]>([]);
  const [series, setSeries] = useState<Series | null>(null);
  const [error, setError] = useState('');

  async function refresh(id: string, from = start, to = end) {
    const query = from && to ? `?from=${from}&to=${to}` : '';
    const body = await api<Series>(`/api/series/${id}${query}`);
    setSeries(body);
    return body;
  }

  useEffect(() => {
    void loadCatalog().then((body) => setIntervals(body.intervals)).catch((reason: Error) => setError(reason.message));
    if (!workspace.seriesId) return;
    void refresh(workspace.seriesId).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!series || series.status !== 'downloading') return;
    const timer = setInterval(() => {
      void refresh(series.id).catch((reason: Error) => setError(reason.message));
    }, 1000);
    return () => clearInterval(timer);
  }, [series?.id, series?.status]);

  async function download() {
    setError('');
    try {
      const body = await api<Series>('/api/series/download', {
        method: 'POST',
        body: JSON.stringify({ symbol, interval: timeframe, start, end }),
      });
      saveWorkspace({ seriesId: body.id, from: start, to: end });
      setSeries(body);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  return (
    <section>
      <h1>Данные</h1>
      <p className="lead">
        Публичные свечи Binance USD-M. Ключ API не нужен. Уже скачанный кусок того же символа и таймфрейма заново не качается: добирается только недостающий край.
      </p>
      <div className="row">
        <label>
          Символ
          <input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} />
        </label>
        <label>
          Таймфрейм
          <select value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
            {intervals.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Начало
          <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
        </label>
        <label>
          Конец
          <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
        </label>
        <button onClick={() => void download()} disabled={!start || !end || series?.status === 'downloading'}>
          Загрузить
        </button>
      </div>
      <p className="note">Даты в UTC. BTCUSDT и 5m стоят в полях как пример из спеки, их можно сменить. Другую биржу этот экран не вызывает.</p>
      {error ? <p className="error">{error}</p> : null}
      {series ? (
        <div className="card">
          <p>
            {series.symbol} {series.interval} · {series.status === 'downloading' ? 'качается' : series.status === 'ready' ? 'скачан' : 'ошибка'}
          </p>
          <p>Баров в файле: {int(series.bars)}. Сейчас докачано в этой попытке: {int(series.progressBars)}.</p>
          {series.start ? <p>В файле: {series.start} — {series.end}.</p> : null}
          {series.sliceBars !== null && series.sliceBars !== undefined ? <p>В выбранных датах: {int(series.sliceBars)} баров.</p> : null}
          <p>Дыр: {int(series.gapCount)}.</p>
          {series.gaps.slice(0, 8).map((gap) => (
            <p key={`${gap.after}-${gap.before}`} className="note">
              {gap.after} → {gap.before}, пропущено баров: {gap.missingBars}
            </p>
          ))}
          {series.gapCount > series.gaps.length ? <p className="note">Показаны первые {series.gaps.length} дыр.</p> : null}
          <p>
            Минимальный лот: {series.minQty ?? '—'}. Шаг лота: {series.lotStep ?? '—'}. Шаг цены: {series.tickSize ?? '—'}.
          </p>
          <p className="note">Шаг цены в тесте не округляется. Объём режется вниз по шагу лота. Если шаг лота неизвестен, объём остаётся notional / цена.</p>
          {series.error ? <p className="error">{series.error}</p> : null}
        </div>
      ) : (
        <p className="note">Ряд ещё не выбран.</p>
      )}
    </section>
  );
}
