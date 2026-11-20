import { useEffect, useState } from 'react';
import { api } from '../api';
import { loadCatalog, maPlugin, type Axis, type Plugin, type PluginParam, type Preset } from '../catalog';
import { int, minutesText, num } from '../format';
import { loadGrid, loadWorkspace, saveGrid, saveWorkspace, type GridDraft } from '../workspace';

type Estimate = { total: number; bars: number; elapsedMs: number; workers: number; perMinute: number | null; minutes: number | null };
type WorkerLimits = { workers: number; workersMax: number };
type Summary = { formula: string; raw: number | null; total: number | null; excluded: number | null; overflow: boolean };

function blankDraft(plugin: Plugin): GridDraft {
  const numbers: GridDraft['numbers'] = {};
  const enums: GridDraft['enums'] = {};
  for (const param of plugin.params) {
    if (!param.grid) continue;
    if (param.type === 'enum') enums[param.key] = [String(param.default)];
    else numbers[param.key] = { from: '', to: '', step: '' };
  }
  return {
    numbers,
    enums,
    deposit: '1000',
    earlyStopPct: '25',
    orderNotional: '1000',
    leverage: '1',
    constraintEnabled: true,
  };
}

export function axesFromDraft(draft: GridDraft, params: PluginParam[]): Axis[] {
  const axes: Axis[] = [];
  for (const param of params) {
    if (!param.grid) continue;
    if (param.type === 'enum') {
      const values = draft.enums[param.key] || [];
      if (values.length === 0) throw new Error(`выберите значения: ${param.label}`);
      axes.push({ key: param.key, kind: 'enum', values });
    } else {
      const field = draft.numbers[param.key];
      if (!field || field.from === '' || field.to === '' || field.step === '') {
        throw new Error(`заполните диапазон: ${param.label}`);
      }
      axes.push({
        key: param.key,
        kind: 'number',
        from: Number(field.from),
        to: Number(field.to),
        step: Number(field.step),
      });
    }
  }
  return axes;
}

export function GridScreen() {
  const [plugin, setPlugin] = useState<Plugin | null>(null);
  const [preset, setPreset] = useState<Preset | null>(null);
  const [draft, setDraft] = useState<GridDraft | null>(() => loadGrid());
  const [summary, setSummary] = useState<{ summary: Summary | null; error: string }>({ summary: null, error: '' });
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [busy, setBusy] = useState(false);
  const [limits, setLimits] = useState<WorkerLimits | null>(null);
  const workspace = loadWorkspace();

  useEffect(() => {
    void api<WorkerLimits & { ok: boolean }>('/api/health')
      .then((body) => setLimits({ workers: body.workers, workersMax: body.workersMax }))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!draft || !limits || draft.workers != null) return;
    const next = { ...draft, workers: String(limits.workers) };
    setDraft(next);
    saveGrid(next);
  }, [draft, limits]);

  useEffect(() => {
    void Promise.all([loadCatalog(), api<Preset>('/api/preset/ma-cross')])
      .then(([catalog, loaded]) => {
        const found = maPlugin(catalog);
        setPlugin(found);
        setPreset(loaded);
        setDraft((current) => current || blankDraft(found));
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!draft || !plugin) return;
    let cancelled = false;
    try {
      const axes = axesFromDraft(draft, plugin.params);
      void api<Summary>('/api/grid/summary', {
        method: 'POST',
        body: JSON.stringify({ strategyId: 'ma-cross', axes, constraintEnabled: draft.constraintEnabled }),
      }).then((body) => {
        if (cancelled) return;
        if (body.overflow || body.total === null) setSummary({ summary: null, error: 'комбинаций слишком много, сузьте сетку' });
        else setSummary({ summary: body, error: '' });
      }).catch((reason: Error) => {
        if (!cancelled) setSummary({ summary: null, error: reason.message });
      });
    } catch (reason) {
      setSummary({ summary: null, error: reason instanceof Error ? reason.message : String(reason) });
    }
    return () => {
      cancelled = true;
    };
  }, [draft, plugin]);

  function update(next: GridDraft) {
    setDraft(next);
    saveGrid(next);
    setEstimate(null);
  }

  async function measure() {
    if (!draft) return;
    setError('');
    setBusy(true);
    try {
      const body = await api<Estimate>('/api/estimate', { method: 'POST', body: JSON.stringify(runBody(draft)) });
      setEstimate(body);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    if (!draft) return;
    setError('');
    setInfo('');
    setBusy(true);
    try {
      const run = await api<{ id: string }>('/api/runs', { method: 'POST', body: JSON.stringify(runBody(draft)) });
      saveWorkspace({ runId: run.id });
      setInfo('Прогон поставлен в очередь. Его состояние на экране «Прогон».');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  function runBody(current: GridDraft) {
    if (!plugin) throw new Error('плагин ma-cross не зарегистрирован');
    return {
      ideaId: workspace.ideaId,
      seriesId: workspace.seriesId,
      from: workspace.from,
      to: workspace.to,
      strategyId: 'ma-cross',
      axes: axesFromDraft(current, plugin.params),
      deposit: Number(current.deposit),
      earlyStopPct: Number(current.earlyStopPct),
      orderNotional: Number(current.orderNotional),
      leverage: Number(current.leverage),
      constraintEnabled: current.constraintEnabled,
      ...(current.workers != null && current.workers.trim() !== '' ? { workers: Number(current.workers) } : {}),
    };
  }

  if (!plugin || !preset || !draft) {
    return (
      <section>
        <h1>Сетка</h1>
        <div className="card">
          {error ? <p className="error">{error}</p> : <p className="note">Каталог плагина ещё грузится.</p>}
          <div className="row">
            <button className="secondary" disabled>Оценить скорость</button>
            <button disabled>Запустить прогон</button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section>
      <h1>Сетка</h1>
      <p className="lead">
        Произведение диапазонов. Перед запуском видна формула и число комбинаций. Скорость появляется после оценки: сервер считает одну комбинацию на выбранном ряде.
      </p>
      <p className="note">
        Ряд: {workspace.seriesId ? `${workspace.from || '—'} — ${workspace.to || '—'}` : 'не выбран на экране «Данные»'}.
        Идея: {workspace.ideaId || 'не выбрана'}.
      </p>
      <div className="row">
        <button className="secondary" onClick={() => update({ ...draftFromPreset(plugin, preset), workers: draft.workers })}>Пресет «MA, как на видео»</button>
      </div>
      {plugin.params.filter((param) => param.grid).map((param) => (
        <div key={param.key} className="card">
          <strong>{param.label}</strong>
          {param.unit ? <span className="note"> {param.unit}</span> : null}
          {param.type === 'enum' ? (
            <div className="checks">
              {(param.options || []).map((option) => (
                <label key={option}>
                  <input
                    type="checkbox"
                    checked={(draft.enums[param.key] || []).includes(option)}
                    onChange={(event) => {
                      const current = new Set(draft.enums[param.key] || []);
                      if (event.target.checked) current.add(option);
                      else current.delete(option);
                      update({ ...draft, enums: { ...draft.enums, [param.key]: [...current] } });
                    }}
                  />
                  {option}
                </label>
              ))}
            </div>
          ) : (
            <div className="row">
              <label>
                от
                <input
                  value={draft.numbers[param.key]?.from || ''}
                  onChange={(event) => update(setNumber(draft, param.key, 'from', event.target.value))}
                />
              </label>
              <label>
                до
                <input
                  value={draft.numbers[param.key]?.to || ''}
                  onChange={(event) => update(setNumber(draft, param.key, 'to', event.target.value))}
                />
              </label>
              <label>
                шаг
                <input
                  value={draft.numbers[param.key]?.step || ''}
                  onChange={(event) => update(setNumber(draft, param.key, 'step', event.target.value))}
                />
              </label>
            </div>
          )}
          {preset.note[param.key] ? <p className="note">{preset.note[param.key]}</p> : null}
        </div>
      ))}
      <div className="card">
        <label>
          <input
            type="checkbox"
            checked={draft.constraintEnabled}
            onChange={(event) => update({ ...draft, constraintEnabled: event.target.checked })}
          />
          Правило генератора fastPeriod &lt; slowPeriod
        </label>
        <div className="row">
          <label>Депозит теста, USDT<input value={draft.deposit} onChange={(event) => update({ ...draft, deposit: event.target.value })} /></label>
          <label>Ранняя остановка, % депозита<input value={draft.earlyStopPct} onChange={(event) => update({ ...draft, earlyStopPct: event.target.value })} /></label>
          <label>Размер заявки, USDT<input value={draft.orderNotional} onChange={(event) => update({ ...draft, orderNotional: event.target.value })} /></label>
          <label>Плечо<input value={draft.leverage} onChange={(event) => update({ ...draft, leverage: event.target.value })} /></label>
          <label>
            Потоки
            <input
              type="number"
              min={1}
              max={limits?.workersMax}
              step={1}
              value={draft.workers ?? ''}
              onChange={(event) => update({ ...draft, workers: event.target.value })}
            />
          </label>
        </div>
        <p className="note">Депозит 1000, порог 25% и размер заявки 1000 — примеры из спеки, не зашитый отбор. Плечо в перебор не входит и прибыль в тесте не умножает. Сигнал по закрытию бара включён всегда.</p>
        <p className="note">
          «Потоки» — сколько процессов считают этот прогон. По умолчанию половина ядер, верх поля на одно ядро меньше, чем есть у машины.
          Заполненное поле важнее переменной IBOT_WORKERS. Пустое поле оставляет переменную, а если её нет — ту же половину.
        </p>
      </div>
      <div className="card">
        {summary.summary ? (
          <>
            <p>{summary.summary.formula}</p>
            <p>
              Без правила: {int(summary.summary.raw)}. К прогону: {int(summary.summary.total)}. Отсечено правилом периода: {int(summary.summary.excluded)}.
            </p>
          </>
        ) : (
          <p>{summary.error}</p>
        )}
        {estimate ? (
          <p>
            Одна комбинация на {int(estimate.bars)} барах: {num(estimate.elapsedMs, 0)} мс, {num(estimate.perMinute, 1)} комбинаций в минуту, процессов {int(estimate.workers)}.
            Полный перебор примерно {minutesText(estimate.minutes)}.
          </p>
        ) : (
          <p className="note">Скорость ещё не измерена. Оценка полного перебора появится после кнопки ниже.</p>
        )}
        <div className="row">
          <button className="secondary" disabled={busy || !summary.summary} onClick={() => void measure()}>Оценить скорость</button>
          <button disabled={busy || !estimate} onClick={() => void start()}>Запустить прогон</button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {info ? <p className="ok">{info}</p> : null}
      </div>
    </section>
  );
}

function draftFromPreset(plugin: Plugin, preset: Preset): GridDraft {
  const draft = blankDraft(plugin);
  draft.numbers = { ...draft.numbers, ...preset.numbers };
  draft.enums = { ...draft.enums, ...preset.enums };
  return draft;
}

function setNumber(draft: GridDraft, key: string, field: 'from' | 'to' | 'step', value: string): GridDraft {
  return {
    ...draft,
    numbers: {
      ...draft.numbers,
      [key]: { ...(draft.numbers[key] || { from: '', to: '', step: '' }), [field]: value },
    },
  };
}
