import { useEffect, useState } from 'react';
import { api } from '../api';
import { num } from '../format';
import { loadWorkspace, saveWorkspace } from '../workspace';

type Month = { month: string; profit: number | null };
type ResultRow = {
  id: string;
  status: string;
  reason: string | null;
  params: Record<string, string | number | boolean>;
  Profit: number | null;
  ProfitFact: number | null;
  Winrate: number | null;
  Trades: number | null;
  MaxDraw: number | null;
  MaxDrawPct: number | null;
  MaxDrawAt: string | null;
  WorstTrade: number | null;
  WorstTradeAt: string | null;
  WorstOpen: number | null;
  WorstOpenAt: string | null;
  positiveMonthShare: number | null;
  bestMonthShare: number | null;
  months: Month[];
};
type RunInfo = {
  id: string;
  colors: { profit33: number | null; profit66: number | null; pf33: number | null; pf66: number | null };
};

const sorts = ['Profit', 'ProfitFact', 'Winrate', 'Trades', 'MaxDraw', 'MaxDrawPct', 'positiveMonthShare', 'bestMonthShare'] as const;

export function TableScreen() {
  const workspace = loadWorkspace();
  const [status, setStatus] = useState('done');
  const [sort, setSort] = useState<(typeof sorts)[number]>('Profit');
  const [dir, setDir] = useState<'desc' | 'asc'>('desc');
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [rows, setRows] = useState<ResultRow[]>([]);
  const [run, setRun] = useState<RunInfo | null>(null);
  const [picked, setPicked] = useState(workspace.selectedRowIds[0] || '');
  const [selected, setSelected] = useState<string[]>(workspace.selectedRowIds);
  const [filters, setFilters] = useState({ minProfitFact: '', maxDrawPct: '', minTrades: '', minPositiveMonthShare: '' });
  const [showMonths, setShowMonths] = useState(false);
  const [cutoff, setCutoff] = useState({ metric: 'ProfitFact', op: '>=', value: '' });
  const [book, setBook] = useState({ name: '', kind: 'research', band: 'short' });
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const limit = 30;

  async function reload(nextPage = page) {
    if (!workspace.runId) return;
    const query = new URLSearchParams({
      status,
      sort,
      dir,
      limit: String(limit),
      offset: String(nextPage * limit),
    });
    for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);
    const body = await api<{ total: number; rows: ResultRow[]; run: RunInfo }>(`/api/runs/${workspace.runId}/rows?${query}`);
    setTotal(body.total);
    setRows(body.rows);
    setRun(body.run);
  }

  useEffect(() => {
    void reload(0).catch((reason: Error) => setError(reason.message));
    setPage(0);
  }, [status, sort, dir, workspace.runId]);

  function toggle(id: string) {
    const next = selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id];
    setSelected(next);
    saveWorkspace({ selectedRowIds: next });
  }

  async function applyCutoff() {
    if (!workspace.runId) return;
    setError('');
    try {
      const body = await api<{ moved: number }>(`/api/runs/${workspace.runId}/cutoff`, {
        method: 'POST',
        body: JSON.stringify({ ...cutoff, value: Number(cutoff.value) }),
      });
      setInfo(`В «отброшено» переложено строк: ${body.moved}.`);
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function restore() {
    if (!workspace.runId) return;
    const body = await api<{ restored: number }>(`/api/runs/${workspace.runId}/restore`, { method: 'POST' });
    setInfo(`Возвращено из порога: ${body.restored}. Оборванные по просадке остаются в «отброшено».`);
    await reload();
  }

  async function toDrafts() {
    if (!workspace.runId) return;
    setError('');
    try {
      await api('/api/drafts', { method: 'POST', body: JSON.stringify({ runId: workspace.runId, rowIds: selected }) });
      setInfo('Строки стали черновиками. Программа торговли их ещё не принимает.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function toBook() {
    if (!workspace.runId) return;
    setError('');
    try {
      await api('/api/books', {
        method: 'POST',
        body: JSON.stringify({ ...book, runId: workspace.runId, rowIds: selected }),
      });
      setInfo('Строки записаны в сводную.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const focus = rows.find((row) => row.id === picked) || rows[0];
  const query = new URLSearchParams({ status, sort, dir });
  for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);

  if (!workspace.runId) return <section><h1>Таблица</h1><p className="note">Сначала откройте прогон на экране «Прогон».</p></section>;

  return (
    <section>
      <h1>Таблица</h1>
      <p className="lead">Досчитанные строки и отдельная пачка «отброшено». Порог не удаляет строку, а перекладывает её с причиной.</p>
      <div className="tabs">
        <button className={status === 'done' ? 'active' : 'secondary'} onClick={() => setStatus('done')}>Досчитанные</button>
        <button className={status === 'rejected' ? 'active' : 'secondary'} onClick={() => setStatus('rejected')}>Отброшено</button>
      </div>
      <div className="row">
        <label>ProfitFact от<input value={filters.minProfitFact} onChange={(event) => setFilters({ ...filters, minProfitFact: event.target.value })} /></label>
        <label>MaxDrawPct до<input value={filters.maxDrawPct} onChange={(event) => setFilters({ ...filters, maxDrawPct: event.target.value })} /></label>
        <label>Сделок от<input value={filters.minTrades} onChange={(event) => setFilters({ ...filters, minTrades: event.target.value })} /></label>
        <label>Плюсовых месяцев, % от<input value={filters.minPositiveMonthShare} onChange={(event) => setFilters({ ...filters, minPositiveMonthShare: event.target.value })} /></label>
        <button className="secondary" onClick={() => void reload(0).then(() => setPage(0))}>Фильтр</button>
        <a className="button secondary" href={`/api/runs/${workspace.runId}/export.xlsx?${query}`}>xlsx</a>
      </div>
      <p className="note">Цвет Profit и ProfitFact — трети внутри досчитанных строк этого прогона, не порог из ролика. Имена правее MaxDraw в спеке не заданы.</p>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th className="left" />
              <th className="left">status</th>
              {['fastType', 'fastPeriod', 'slowType', 'slowPeriod', 'offsetPct', 'orderLife', 'takeProfitPct', 'stopLossPct', 'minSignalGapBars', 'direction', 'crossMode', 'exitMode'].map((name) => (
                <th key={name}>{name}</th>
              ))}
              {sorts.slice(0, 6).map((name) => (
                <th key={name}>
                  <button onClick={() => { setSort(name); setDir(sort === name && dir === 'desc' ? 'asc' : 'desc'); }}>
                    {name}
                  </button>
                </th>
              ))}
              <th>MaxDrawAt</th>
              <th>WorstTrade</th>
              <th>WorstTradeAt</th>
              <th>WorstOpen</th>
              <th>WorstOpenAt</th>
              {sorts.slice(6).map((name) => (
                <th key={name}>
                  <button onClick={() => { setSort(name); setDir(sort === name && dir === 'desc' ? 'asc' : 'desc'); }}>
                    {name}
                  </button>
                </th>
              ))}
              {showMonths && focus?.months.map((month) => <th key={month.month}>{month.month}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} onClick={() => setPicked(row.id)}>
                <td>
                  <input type="checkbox" checked={selected.includes(row.id)} onChange={() => toggle(row.id)} />
                </td>
                <td className="left">{row.status === 'stopped' || row.status === 'discarded' ? row.reason : row.status}</td>
                <td>{text(row.params.fastType)}</td>
                <td>{text(row.params.fastPeriod)}</td>
                <td>{text(row.params.slowType)}</td>
                <td>{text(row.params.slowPeriod)}</td>
                <td>{text(row.params.offsetPct)}</td>
                <td>{text(row.params.lifetimeBars)}</td>
                <td>{text(row.params.takeProfitPct)}</td>
                <td>{text(row.params.stopLossPct)}</td>
                <td>{text(row.params.minSignalGapBars)}</td>
                <td>{text(row.params.direction)}</td>
                <td>{text(row.params.crossMode)}</td>
                <td>{text(row.params.exitMode)}</td>
                <td className={tone(row.Profit, run?.colors.profit33 ?? null, run?.colors.profit66 ?? null)}>{num(row.Profit)}</td>
                <td className={tone(row.ProfitFact, run?.colors.pf33 ?? null, run?.colors.pf66 ?? null)}>{num(row.ProfitFact)}</td>
                <td>{num(row.Winrate)}</td>
                <td>{num(row.Trades, 0)}</td>
                <td>{num(row.MaxDraw)}</td>
                <td>{num(row.MaxDrawPct)}</td>
                <td>{row.MaxDrawAt || '—'}</td>
                <td>{num(row.WorstTrade)}</td>
                <td>{row.WorstTradeAt || '—'}</td>
                <td>{num(row.WorstOpen)}</td>
                <td>{row.WorstOpenAt || '—'}</td>
                <td>{num(row.positiveMonthShare)}</td>
                <td>{num(row.bestMonthShare)}</td>
                {showMonths && row.months.map((month) => <td key={month.month}>{month.profit === null ? '' : num(month.profit)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        <button className="secondary" disabled={page === 0} onClick={() => { const next = page - 1; setPage(next); void reload(next); }}>Назад</button>
        <span>{page * limit + 1}–{Math.min(total, (page + 1) * limit)} из {total}</span>
        <button className="secondary" disabled={(page + 1) * limit >= total} onClick={() => { const next = page + 1; setPage(next); void reload(next); }}>Дальше</button>
        <button className="secondary" onClick={() => setShowMonths((value) => !value)}>{showMonths ? 'Скрыть месяцы' : 'Показать месяцы'}</button>
      </div>
      {focus ? (
        <div className="card">
          <p>Profit {num(focus.Profit)}, ProfitFact {num(focus.ProfitFact)}, сделок {num(focus.Trades, 0)}.</p>
          <p>Просадка {num(focus.MaxDraw)} ({num(focus.MaxDrawPct)}%) на {focus.MaxDrawAt || '—'}.</p>
          <p>Худшая закрытая сделка {num(focus.WorstTrade)} на {focus.WorstTradeAt || '—'}. Худший незакрытый просад {num(focus.WorstOpen)} на {focus.WorstOpenAt || '—'}.</p>
          <p>Плюсовых месяцев {num(focus.positiveMonthShare)}%. Доля лучшего месяца в прибыли {num(focus.bestMonthShare)}%.</p>
          <MonthChart months={focus.months} maxDrawAt={focus.MaxDrawAt} worstAt={focus.WorstTradeAt} />
        </div>
      ) : null}
      <h2>Порог отсечения</h2>
      <div className="row">
        <select value={cutoff.metric} onChange={(event) => setCutoff({ ...cutoff, metric: event.target.value })}>
          {['Profit', 'ProfitFact', 'Winrate', 'Trades', 'MaxDraw', 'MaxDrawPct'].map((item) => <option key={item}>{item}</option>)}
        </select>
        <select value={cutoff.op} onChange={(event) => setCutoff({ ...cutoff, op: event.target.value })}>
          <option value=">=">{'>='}</option>
          <option value="<=">{'<='}</option>
        </select>
        <input value={cutoff.value} onChange={(event) => setCutoff({ ...cutoff, value: event.target.value })} />
        <button onClick={() => void applyCutoff()}>Переложить не прошедшие</button>
        <button className="secondary" onClick={() => void restore()}>Вернуть порог</button>
      </div>
      <h2>Выбранные строки</h2>
      <p className="note">Выбрано: {selected.length}. В черновик и в сводную идут только досчитанные строки.</p>
      <div className="row">
        <button disabled={selected.length === 0} onClick={() => void toDrafts()}>В черновик конфига</button>
        <input placeholder="имя сводной" value={book.name} onChange={(event) => setBook({ ...book, name: event.target.value })} />
        <select value={book.kind} onChange={(event) => setBook({ ...book, kind: event.target.value })}>
          <option value="research">исследовательская</option>
          <option value="working">рабочая</option>
        </select>
        <select value={book.band} onChange={(event) => setBook({ ...book, band: event.target.value })}>
          <option value="short">короткие таймфреймы</option>
          <option value="higher">старшие таймфреймы</option>
        </select>
        <button className="secondary" disabled={selected.length === 0} onClick={() => void toBook()}>В сводную</button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {info ? <p className="ok">{info}</p> : null}
    </section>
  );
}

function MonthChart({ months, maxDrawAt, worstAt }: { months: Month[]; maxDrawAt: string | null; worstAt: string | null }) {
  const peak = Math.max(1, ...months.map((month) => Math.abs(month.profit || 0)));
  return (
    <div className="chart">
      {months.map((month) => {
        const marked = month.month === maxDrawAt?.slice(0, 7) || month.month === worstAt?.slice(0, 7);
        const profit = month.profit;
        return (
          <div
            key={month.month}
            title={`${month.month}: ${profit === null ? 'не считался' : profit}`}
            className={`bar${profit !== null && profit < 0 ? ' down' : ''}${profit === null ? ' empty' : ''}${marked ? ' mark' : ''}`}
            style={{ height: `${profit === null ? 8 : Math.max(2, (Math.abs(profit) / peak) * 110)}px` }}
          />
        );
      })}
    </div>
  );
}

function tone(value: number | null, low: number | null, high: number | null): string {
  if (value === null || low === null || high === null) return '';
  if (value >= high) return 'good';
  if (value <= low) return 'bad';
  return 'mid';
}

function text(value: string | number | boolean | undefined): string {
  if (value === undefined) return '—';
  return String(value);
}
