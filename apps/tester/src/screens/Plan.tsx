import { useEffect, useState } from 'react';
import { api } from '../api';
import { loadCatalog, maPlugin } from '../catalog';
import { axesFromDraft } from './Grid';
import { loadGrid, loadWorkspace, saveWorkspace } from '../workspace';

type Cell = { cell: number; column: string; direction: string; variant: number | null; status: string; note: string };
type Series = { id: string; symbol: string; status: string };
type Column = { index: number; title: string; cellFrom: number; cellTo: number; runnable: boolean };
type Hypothesis = { id: string; title: string; detail: string; rejectBtc: boolean };

const statuses = [
  ['not_started', 'не запускалась'],
  ['queued', 'в очереди'],
  ['running', 'идёт'],
  ['has_candidates', 'есть кандидаты'],
  ['discarded', 'отброшена'],
];

export function PlanScreen() {
  const [interval, setInterval] = useState('5m');
  const [cells, setCells] = useState<Cell[]>([]);
  const [columns, setColumns] = useState<Column[]>([]);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');

  async function reload(next = interval) {
    const body = await api<{ cells: Cell[] }>(`/api/plan?interval=${next}`);
    setCells(body.cells);
  }

  useEffect(() => {
    void Promise.all([
      api<{ columns: Column[] }>('/api/plan-columns'),
      api<{ hypotheses: Hypothesis[] }>('/api/hypotheses'),
    ]).then(([board, list]) => {
      setColumns(board.columns);
      setHypotheses(list.hypotheses);
    }).catch((reason: Error) => setError(reason.message));
    void reload().catch((reason: Error) => setError(reason.message));
  }, [interval]);

  async function setStatus(cell: Cell, status: string) {
    await api('/api/plan', { method: 'PUT', body: JSON.stringify({ interval, cell: cell.cell, status, note: cell.note }) });
    await reload();
  }

  async function enqueue(hypothesisId: string) {
    setError('');
    setInfo('');
    const workspace = loadWorkspace();
    const draft = loadGrid();
    if (!workspace.seriesId || !workspace.from || !workspace.to) {
      setError('Сначала выберите ряд и даты на экране «Данные».');
      return;
    }
    if (!draft) {
      setError('Сначала заполните сетку.');
      return;
    }
    try {
      const catalog = await loadCatalog();
      const series = await api<Series>(`/api/series/${workspace.seriesId}`);
      const hypothesis = hypotheses.find((item) => item.id === hypothesisId);
      if (hypothesis?.rejectBtc && series.symbol.toUpperCase().startsWith('BTC')) {
        setError('Эта гипотеза не ставится на символ, который начинается с BTC. Смените монету на экране «Данные».');
        return;
      }
      const axes = axesFromDraft(draft, maPlugin(catalog).params);
      const run = await api<{ id: string }>('/api/hypotheses/queue', {
        method: 'POST',
        body: JSON.stringify({
          hypothesisId,
          ideaId: workspace.ideaId,
          seriesId: workspace.seriesId,
          from: workspace.from,
          to: workspace.to,
          strategyId: 'ma-cross',
          axes,
          deposit: Number(draft.deposit),
          earlyStopPct: Number(draft.earlyStopPct),
          orderNotional: Number(draft.orderNotional),
          leverage: Number(draft.leverage),
          constraintEnabled: draft.constraintEnabled,
        }),
      });
      saveWorkspace({ runId: run.id });
      setInfo('Гипотеза поставлена в очередь прогонов.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  return (
    <section>
      <h1>План гипотез</h1>
      <p className="lead">
        Доска 7×9 хранит статус ячейки. «Вар 1 / вар 2 / вар 3» на схеме не расшифрованы, поэтому ячейка не запускает правило. Колонки RSI, MACD, дельты и Боллинджера не запускаются: этих плагинов в первой поставке нет.
      </p>
      <label>
        Таймфрейм доски
        <select value={interval} onChange={(event) => setInterval(event.target.value)}>
          {['1m', '5m', '15m', '1h', '4h', '1d'].map((item) => <option key={item}>{item}</option>)}
        </select>
      </label>
      <div className="board">
        {columns.map((column) => (
          <div key={column.index}>
            <h2>{column.title}</h2>
            {!column.runnable ? <p className="note">Плагина нет.</p> : null}
            {cells.filter((cell) => cell.cell >= column.cellFrom && cell.cell <= column.cellTo).map((cell) => (
              <div key={cell.cell} className="card cell">
                <p>{cell.cell}. {cell.direction}, вар {cell.variant}</p>
                <select value={cell.status} onChange={(event) => void setStatus(cell, event.target.value)}>
                  {statuses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </div>
            ))}
          </div>
        ))}
      </div>
      <h2>Очередь для скользящих</h2>
      <p className="note">Гипотеза берёт текущую сетку и подставляет только те оси, которые названы в спеке. Остальные диапазоны не переписываются.</p>
      {hypotheses.map((item) => (
        <div key={item.id} className="card">
          <strong>{item.title}</strong>
          <p className="note">{item.detail}</p>
          <button onClick={() => void enqueue(item.id)}>В очередь</button>
        </div>
      ))}
      {error ? <p className="error">{error}</p> : null}
      {info ? <p className="ok">{info}</p> : null}
    </section>
  );
}
