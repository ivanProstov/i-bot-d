import { useEffect, useState } from 'react';
import { api } from '../api';
import { int, minutesText, num } from '../format';
import { loadWorkspace, saveWorkspace } from '../workspace';

type Run = {
  id: string;
  symbol: string;
  interval: string;
  from: string;
  to: string;
  status: string;
  hypothesisId: string | null;
  parentRunId: string | null;
  total: number;
  processed: number;
  finished: number;
  stopped: number;
  remaining: number;
  perMinute: number | null;
  error: string | null;
};

export function RunScreen() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [titles, setTitles] = useState<Map<string, string>>(new Map());
  const [current, setCurrent] = useState(loadWorkspace().runId);
  const [error, setError] = useState('');

  async function reload() {
    const body = await api<{ runs: Run[] }>('/api/runs');
    setRuns(body.runs);
  }

  useEffect(() => {
    void api<{ hypotheses: Array<{ id: string; title: string }> }>('/api/hypotheses')
      .then((body) => setTitles(new Map(body.hypotheses.map((item) => [item.id, item.title]))))
      .catch(() => undefined);
    void reload().catch((reason: Error) => setError(reason.message));
    const timer = setInterval(() => {
      void reload().catch(() => undefined);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const run = runs.find((item) => item.id === current) || runs[0];

  async function cancel(id: string) {
    await api(`/api/runs/${id}/cancel`, { method: 'POST' });
    await reload();
  }

  return (
    <section>
      <h1>Прогон</h1>
      <p className="lead">Сколько комбинаций досчитано до конца истории, сколько оборвано по просадке и сколько ещё не посчитано.</p>
      {error ? <p className="error">{error}</p> : null}
      {run ? (
        <div className="card">
          <p>{run.symbol} {run.interval}, {run.from} — {run.to}</p>
          <p>Статус: {statusText(run.status)}. {run.hypothesisId ? titles.get(run.hypothesisId) || run.hypothesisId : 'без гипотезы'}</p>
          {run.parentRunId ? <p>Это уточнение прогона {run.parentRunId}.</p> : null}
          <p>Досчитано: {int(run.finished)}. Оборвано по просадке: {int(run.stopped)}. Ещё не посчитано: {int(run.remaining)}.</p>
          <p>
            Скорость: {run.perMinute ? `${num(run.perMinute, 1)} комбинаций в минуту` : 'ещё нет'}.
            Остаток примерно {run.perMinute ? minutesText(run.remaining / run.perMinute) : '—'}.
          </p>
          <p>Всего в сетке: {int(run.total)}. Пройдено: {int(run.processed)}.</p>
          <RunProgress
            processed={run.processed}
            total={run.total}
            active={run.status === 'queued' || run.status === 'running'}
          />
          {run.error ? <p className="error">{run.error}</p> : null}
          {(run.status === 'queued' || run.status === 'running') && (
            <button className="secondary" onClick={() => void cancel(run.id)}>Остановить очередь</button>
          )}
        </div>
      ) : (
        <p className="note">Прогонов ещё нет. Запуск со экрана «Сетка».</p>
      )}
      <h2>Все прогоны</h2>
      {runs.map((item) => (
        <button
          key={item.id}
          className={`card secondary${item.id === run?.id ? ' current' : ''}`}
          onClick={() => {
            setCurrent(item.id);
            saveWorkspace({ runId: item.id, selectedRowIds: [] });
          }}
        >
          {item.symbol} {item.interval} · {statusText(item.status)} · {int(item.processed)}/{int(item.total)}
          {item.id === run?.id ? ' · открыт' : ''}
        </button>
      ))}
    </section>
  );
}

function RunProgress({ processed, total, active }: { processed: number; total: number; active: boolean }) {
  const pct = total > 0 ? Math.min(100, (processed / total) * 100) : 0;
  const [width, setWidth] = useState(() => (prefersReducedMotion() ? pct : 0));

  useEffect(() => {
    if (prefersReducedMotion()) {
      setWidth(pct);
      return;
    }
    const frame = requestAnimationFrame(() => setWidth(pct));
    return () => cancelAnimationFrame(frame);
  }, [pct]);

  return (
    <div
      className={active ? 'progress busy' : 'progress'}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={processed}
      aria-label="Пройдено"
    >
      <span style={{ width: `${width}%` }} />
    </div>
  );
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function statusText(status: string): string {
  if (status === 'queued') return 'в очереди';
  if (status === 'running') return 'идёт';
  if (status === 'done') return 'досчитан';
  if (status === 'cancelled') return 'остановлен';
  if (status === 'error') return 'ошибка';
  return status;
}
