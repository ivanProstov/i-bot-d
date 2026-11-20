import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Axis } from '../catalog';
import { loadWorkspace, saveWorkspace } from '../workspace';

type Row = { id: string; params: Record<string, number | string | boolean> };
type Run = {
  id: string;
  seriesId: string;
  from: string;
  to: string;
  strategyId: string;
  ideaId: string | null;
  axes: Axis[];
  settings: { deposit: number; earlyStopPct: number; orderNotional: number; leverage: number; constraintEnabled: boolean; workers?: number };
};

type Field = { from: string; to: string; step: string; margin: string };

export function RefineScreen() {
  const workspace = loadWorkspace();
  const [run, setRun] = useState<Run | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [fields, setFields] = useState<Record<string, Field>>({});
  const [enums, setEnums] = useState<Record<string, string[]>>({});
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');

  useEffect(() => {
    if (!workspace.runId || workspace.selectedRowIds.length === 0) return;
    const ids = workspace.selectedRowIds.join(',');
    void Promise.all([
      api<Run>(`/api/runs/${workspace.runId}`),
      api<{ rows: Row[] }>(`/api/runs/${workspace.runId}/rows?status=all&ids=${ids}&limit=500`),
    ]).then(([loaded, table]) => {
      setRun(loaded);
      setRows(table.rows);
      const next: Record<string, Field> = {};
      const nextEnums: Record<string, string[]> = {};
      for (const axis of loaded.axes) {
        if (axis.kind === 'enum') {
          const values = new Set<string>();
          for (const row of table.rows) values.add(String(row.params[axis.key]));
          nextEnums[axis.key] = [...values];
        } else {
          const values = table.rows.map((row) => Number(row.params[axis.key])).filter((value) => Number.isFinite(value));
          const low = Math.min(...values);
          const high = Math.max(...values);
          const step = axis.key === 'takeProfitPct' || axis.key === 'stopLossPct' ? '0.3' : String(axis.step);
          next[axis.key] = { from: String(low), to: String(high), step, margin: '0' };
        }
      }
      setFields(next);
      setEnums(nextEnums);
    }).catch((reason: Error) => setError(reason.message));
  }, [workspace.runId]);

  async function start() {
    if (!run) return;
    setError('');
    setInfo('');
    try {
      const axes: Axis[] = run.axes.map((axis) => {
        if (axis.kind === 'enum') return { key: axis.key, kind: 'enum', values: enums[axis.key] || axis.values };
        const field = fields[axis.key];
        const margin = Number(field.margin || 0);
        return {
          key: axis.key,
          kind: 'number',
          from: Number(field.from) - margin,
          to: Number(field.to) + margin,
          step: Number(field.step),
        };
      });
      const created = await api<{ id: string }>('/api/runs', {
        method: 'POST',
        body: JSON.stringify({
          ideaId: run.ideaId,
          seriesId: run.seriesId,
          from: run.from,
          to: run.to,
          strategyId: run.strategyId,
          parentRunId: run.id,
          parentRowIds: rows.map((row) => row.id),
          axes,
          deposit: run.settings.deposit,
          earlyStopPct: run.settings.earlyStopPct,
          orderNotional: run.settings.orderNotional,
          leverage: run.settings.leverage,
          constraintEnabled: run.settings.constraintEnabled,
          ...(typeof run.settings.workers === 'number' ? { workers: run.settings.workers } : {}),
        }),
      });
      saveWorkspace({ runId: created.id, selectedRowIds: [] });
      setInfo('Уточнение поставлено отдельным прогоном со ссылкой на выбранные строки.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  return (
    <section>
      <h1>Уточнение</h1>
      <p className="lead">
        Отдельный прогон вокруг выбранных строк. Для тейка и стопа шаг по умолчанию 0.3 — пример из спеки. Поля можно изменить. Запас вокруг минимума и максимума выбранных значений по умолчанию нулевой.
      </p>
      {workspace.selectedRowIds.length === 0 ? <p className="note">На экране «Таблица» не выбраны строки.</p> : null}
      {rows.length > 0 ? <p>Строк в зоне: {rows.length}.</p> : null}
      {Object.entries(fields).map(([key, field]) => (
        <div key={key} className="row">
          <strong>{key}</strong>
          <label>от<input value={field.from} onChange={(event) => setFields({ ...fields, [key]: { ...field, from: event.target.value } })} /></label>
          <label>до<input value={field.to} onChange={(event) => setFields({ ...fields, [key]: { ...field, to: event.target.value } })} /></label>
          <label>шаг<input value={field.step} onChange={(event) => setFields({ ...fields, [key]: { ...field, step: event.target.value } })} /></label>
          <label>запас<input value={field.margin} onChange={(event) => setFields({ ...fields, [key]: { ...field, margin: event.target.value } })} /></label>
        </div>
      ))}
      {Object.entries(enums).map(([key, values]) => (
        <p key={key}>{key}: {values.join(', ') || '—'}</p>
      ))}
      <button disabled={!run || rows.length === 0} onClick={() => void start()}>Запустить уточнение</button>
      {error ? <p className="error">{error}</p> : null}
      {info ? <p className="ok">{info}</p> : null}
    </section>
  );
}
